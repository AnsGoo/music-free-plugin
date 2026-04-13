import hashlib
import json
import os
import re
import sys
import urllib.parse

import extism

API_VERSION = "musicfree.plugin.scraper.v1"
LASTFM_BASE = "https://ws.audioscrobbler.com/2.0/"


def _plg(msg: str) -> None:
    """Plugin diagnostics → stderr (host unified logger when WASI capture is on)."""
    print(f"[mf-plugin-lastfm] {msg}", file=sys.stderr, flush=True)


def _trunc(s: str, max_len: int) -> str:
    t = (s or "").strip()
    if len(t) <= max_len:
        return t
    return t[:max_len] + "…"


def _http_resp_status(resp) -> int:
    sc = getattr(resp, "status_code", None)
    if callable(sc):
        return int(sc())
    return int(sc)


def _http_resp_body_bytes(resp) -> bytes:
    """
    读取 Extism HttpResponse body。
    extism_ffi.HttpResponse 的 body 多为 **属性** `data`（bytes），而 prelude 误写成 `self._inner.data()`，
    会导致 'HttpResponse' object has no attribute 'data'（方法不存在）。此处兼容属性 / 方法两种形态。
    """
    raw_top = getattr(resp, "data", None)
    if isinstance(raw_top, (bytes, bytearray, memoryview)):
        return bytes(raw_top)
    inner = getattr(resp, "_inner", None)
    if inner is not None:
        raw = getattr(inner, "data", None)
        if isinstance(raw, (bytes, bytearray, memoryview)):
            return bytes(raw)
        if callable(raw):
            try:
                b = raw()
                if isinstance(b, (bytes, bytearray, memoryview)):
                    return bytes(b)
            except Exception:
                pass
        for name in ("body", "bytes"):
            fn = getattr(inner, name, None)
            if callable(fn):
                try:
                    b = fn()
                    if isinstance(b, (bytes, bytearray, memoryview)):
                        return bytes(b)
                except Exception:
                    continue
    db = getattr(resp, "data_bytes", None)
    if callable(db):
        return db()
    ds = getattr(resp, "data_str", None)
    if callable(ds):
        return ds().encode("utf-8")
    raise AttributeError("HttpResponse: cannot read body bytes")


def _http_resp_body_text(resp) -> str:
    return _http_resp_body_bytes(resp).decode("utf-8", errors="replace")


def _input():
    data = extism.input_json()
    if not isinstance(data, dict):
        raise Exception("invalid input payload")
    if data.get("apiVersion") != API_VERSION:
        raise Exception(f"invalid apiVersion: {data.get('apiVersion')}")
    return data


def _ok(payload):
    extism.output_json({"ok": True, "data": payload})


def _err(code: str, message: str, retryable: bool = False):
    extism.output_json(
        {
            "ok": False,
            "error": {
                "code": code,
                "message": message,
                "retryable": retryable,
            },
        }
    )


def _config_get(data: dict, key: str, default=""):
    cfg = data.get("config") or {}
    if not isinstance(cfg, dict):
        return default
    return cfg.get(key, default)


def _api_key(data: dict) -> str:
    api_key = str(_config_get(data, "api_key", "")).strip()
    if not api_key:
        raise Exception("missing config.api_key")
    return api_key


def _shared_secret(data: dict) -> str:
    shared_secret = str(_config_get(data, "shared_secret", "")).strip()
    if not shared_secret:
        raise Exception("missing config.shared_secret")
    return shared_secret


def _session_key(data: dict) -> str:
    return str(_config_get(data, "session_key", "")).strip()


def _song(data: dict):
    song = data.get("song") or {}
    if not isinstance(song, dict):
        return "", "", ""
    title = str(song.get("title", "")).strip()
    artist = str(song.get("artist", "")).strip()
    album = str(song.get("album", "")).strip()
    return title, artist, album


def _album_query(data: dict):
    a = data.get("album") or {}
    if not isinstance(a, dict):
        return "", ""
    name = str(a.get("albumName", "")).strip()
    artist = str(a.get("albumArtist", "")).strip()
    return name, artist


def _artist_query(data: dict):
    a = data.get("artist") or {}
    if not isinstance(a, dict):
        return ""
    return str(a.get("artistName", "")).strip()


def _api_sig(params: dict, secret: str) -> str:
    pairs = []
    for k in sorted(params.keys()):
        if k in ("api_sig", "format"):
            continue
        pairs.append(f"{k}{params[k]}")
    raw = "".join(pairs) + secret
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _build_url(method: str, params: dict) -> str:
    q = dict(params or {})
    q["method"] = method
    q["format"] = "json"
    return f"{LASTFM_BASE}?{urllib.parse.urlencode(q)}"


def _call_json(data: dict, method: str, params: dict):
    api_key = _api_key(data)
    q = dict(params or {})
    q["api_key"] = api_key
    secret = _shared_secret(data)
    session_key = _session_key(data)
    if session_key:
        q["sk"] = session_key
    q["api_sig"] = _api_sig({"method": method, **q}, secret)
    url = _build_url(method, q)
    resp = extism.Http.request(url, meth="GET")
    st = _http_resp_status(resp)
    if st != 200:
        body = ""
        try:
            body = _http_resp_body_text(resp)
        except Exception:
            body = ""
        body = (body or "").strip()
        if len(body) > 400:
            body = body[:400] + "...(truncated)"
        if body:
            raise Exception(f"http {st}: {body}")
        raise Exception(f"http {st}")
    try:
        return json.loads(_http_resp_body_text(resp))
    except Exception as e:
        raise Exception(f"invalid json: {e}")


def _http_get_bytes(url: str):
    resp = extism.Http.request(url, meth="GET")
    st = _http_resp_status(resp)
    if st != 200:
        raise Exception(f"http {st}")
    return _http_resp_body_bytes(resp)


def _artist_info_with_auth(data: dict, artist: str):
    return _call_json(
        data,
        "artist.getinfo",
        {
            "artist": artist,
            "lang": "zh",
            "autocorrect": "1",
        },
    )


def _track_get_info(data: dict, title: str, artist: str):
    return _call_json(
        data,
        "track.getInfo",
        {"track": title, "artist": artist, "autocorrect": "1", "lang": "zh"},
    )


def _lfm_api_ok(info) -> bool:
    """Last.fm 常在 HTTP 200 下返回 JSON 内的 error 字段。"""
    return isinstance(info, dict) and not info.get("error")


def _normalize_album_obj(alb) -> dict:
    if isinstance(alb, list) and len(alb) > 0:
        alb = alb[0]
    if not isinstance(alb, dict):
        return {}
    return alb


def _album_artist_name_from_obj(alb: dict, fallback: str) -> str:
    """Last.fm 有时返回 artist 为 {\"name\":...}，有时为纯字符串。"""
    ar = alb.get("artist")
    if isinstance(ar, dict):
        n = str(ar.get("name", "")).strip()
        return n or fallback
    if isinstance(ar, str):
        s = ar.strip()
        return s or fallback
    return fallback


def _wiki_as_dict(wiki) -> dict:
    """wiki 通常为对象；少数情况下可能是字符串或其它类型。"""
    if isinstance(wiki, dict):
        return wiki
    return {}


def _year_from_date_str(s: str) -> int:
    s = (s or "").strip()
    if len(s) >= 4 and s[:4].isdigit():
        y = int(s[:4])
        if 1000 <= y <= 9999:
            return y
    m = re.search(r"\b(19|20)\d{2}\b", s)
    if m:
        return int(m.group(0))
    return 0


def _metadata_from_track(tr: dict, fallback_title: str, fallback_artist: str) -> dict:
    alb = _normalize_album_obj(tr.get("album"))
    genre = ""
    tt = tr.get("toptags") or {}
    tags = tt.get("tag") or []
    if isinstance(tags, dict):
        tags = [tags]
    if tags and isinstance(tags[0], dict):
        genre = str(tags[0].get("name", "")).strip()

    year = 0
    rd = str(alb.get("releasedate") or alb.get("released") or "").strip()
    year = _year_from_date_str(rd)
    if year == 0:
        wiki = tr.get("wiki") or {}
        if isinstance(wiki, dict):
            year = _year_from_date_str(str(wiki.get("published", "")))

    track_num = 0
    attr = tr.get("@attr") or {}
    if isinstance(attr, dict):
        try:
            tn = attr.get("track") or attr.get("position")
            if tn is not None and str(tn).strip().isdigit():
                track_num = int(str(tn).strip())
        except Exception:
            track_num = 0

    disc_num = 0
    if isinstance(attr, dict):
        try:
            dn = attr.get("discnumber") or attr.get("disc")
            if dn is not None and str(dn).strip().isdigit():
                disc_num = int(str(dn).strip())
        except Exception:
            disc_num = 0

    artist_name = ""
    ar = tr.get("artist")
    if isinstance(ar, dict):
        artist_name = str(ar.get("name", "")).strip()
    elif isinstance(ar, str):
        artist_name = ar.strip()

    return {
        "title": str(tr.get("name", "") or fallback_title).strip(),
        "artist": artist_name or fallback_artist,
        "album": str(alb.get("title", "")).strip(),
        "genre": genre,
        "year": year,
        "track": track_num,
        "discNumber": disc_num,
    }


def _mime_and_ext(body: bytes) -> tuple[str, str]:
    if len(body) >= 8 and body[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png", ".png"
    if len(body) >= 12 and body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return "image/jpeg", ".jpg"


def _write_cover_file(body: bytes) -> tuple[str, str]:
    mime, ext = _mime_and_ext(body)
    sha = hashlib.sha256(body).hexdigest()
    file_name = f"sha256-{sha}{ext}"
    target = f"/coverArt/{file_name}"
    if not os.path.exists(target):
        with open(target + ".tmp", "wb") as f:
            f.write(body)
        os.replace(target + ".tmp", target)
    return file_name, mime


def _best_album_image_url(album_obj: dict) -> str:
    images = album_obj.get("image") or []
    if not isinstance(images, list):
        return ""
    best = ""
    for item in images:
        if not isinstance(item, dict):
            continue
        url = str(item.get("#text", "")).strip()
        size = str(item.get("size", "")).strip()
        if not url:
            continue
        if size in ("mega", "extralarge"):
            return url
        if not best:
            best = url
    return best


def _best_image_url(artist_obj: dict) -> str:
    images = artist_obj.get("image") or []
    if not isinstance(images, list):
        return ""
    best = ""
    for item in images:
        if not isinstance(item, dict):
            continue
        url = str(item.get("#text", "")).strip()
        size = str(item.get("size", "")).strip()
        if not url:
            continue
        if size in ("mega", "extralarge"):
            return url
        if not best:
            best = url
    return best


@extism.plugin_fn
def ScraperSong():
    try:
        data = _input()
        _ = _api_key(data)
        _ = _shared_secret(data)
        title, artist, _album = _song(data)
        _plg(
            f"stage=ScraperSong start title={_trunc(title, 48)!r} artist={_trunc(artist, 48)!r}"
        )
        if not title or not artist:
            _plg("stage=ScraperSong err=missing_title_or_artist")
            _err("invalid_request", "song.title and song.artist are required", False)
            return
        info = _track_get_info(data, title, artist)
        if not _lfm_api_ok(info):
            _plg("stage=ScraperSong err=api_not_ok")
            _err("no_match", str(info.get("message", "track not found on Last.fm")), False)
            return
        tr = info.get("track") or {}
        if not isinstance(tr, dict) or not tr:
            _plg("stage=ScraperSong err=empty_track")
            _err("no_match", "track not found on Last.fm", False)
            return
        out = _metadata_from_track(tr, title, artist)
        _plg("stage=ScraperSong ok")
        _ok(out)
    except Exception as e:
        msg = str(e)
        _plg(f"stage=ScraperSong err exception {_trunc(msg, 200)!r}")
        if "not found" in msg.lower() or "# 6" in msg:
            _err("no_match", "track not found on Last.fm", False)
            return
        if "missing config" in msg.lower():
            _err("invalid_config", msg, False)
            return
        _err("network", msg, True)


@extism.plugin_fn
def GetCover():
    """优先：曲目关联专辑封面 (track.getInfo)；其次 album.getinfo；最后艺人头像。"""
    try:
        data = _input()
        _ = _api_key(data)
        _ = _shared_secret(data)
        title, artist, album_hint = _song(data)
        _plg(
            f"stage=GetCover start title={_trunc(title, 48)!r} artist={_trunc(artist, 48)!r} "
            f"album_hint={_trunc(album_hint, 40)!r}"
        )
        image_url = ""

        if title and artist:
            try:
                info = _track_get_info(data, title, artist)
                if _lfm_api_ok(info):
                    tr = info.get("track") or {}
                    alb = _normalize_album_obj(tr.get("album"))
                    image_url = _best_album_image_url(alb) if alb else ""
            except Exception:
                image_url = ""

        album_name = album_hint
        album_artist = artist
        if not image_url and album_name and album_artist:
            try:
                ainfo = _call_json(
                    data,
                    "album.getinfo",
                    {
                        "album": album_name,
                        "artist": album_artist,
                        "autocorrect": "1",
                        "lang": "zh",
                    },
                )
                alb = ainfo.get("album") or {}
                image_url = _best_album_image_url(alb) if isinstance(alb, dict) else ""
            except Exception:
                pass

        if not image_url and album_name and not album_artist:
            try:
                sr = _call_json(
                    data,
                    "album.search",
                    {"album": album_name, "limit": "3"},
                )
                matches = ((sr.get("results") or {}).get("albummatches") or {}).get(
                    "album"
                ) or []
                if isinstance(matches, dict):
                    matches = [matches]
                if matches:
                    album_artist = str((matches[0] or {}).get("artist", "")).strip()
                if album_artist:
                    ainfo = _call_json(
                        data,
                        "album.getinfo",
                        {
                            "album": album_name,
                            "artist": album_artist,
                            "autocorrect": "1",
                            "lang": "zh",
                        },
                    )
                    alb = ainfo.get("album") or {}
                    image_url = _best_album_image_url(alb) if isinstance(alb, dict) else ""
            except Exception:
                pass

        if not image_url and artist:
            info = _artist_info_with_auth(data, artist)
            artist_obj = info.get("artist") or {}
            if isinstance(artist_obj, dict):
                image_url = _best_image_url(artist_obj)

        if not image_url:
            _plg("stage=GetCover err=no_match")
            _err("no_match", "cover not found", False)
            return

        body = _http_get_bytes(image_url)
        if not body:
            _plg("stage=GetCover err=empty_image_body")
            _err("no_match", "empty image body", False)
            return

        file_name, mime = _write_cover_file(body)
        _plg(f"stage=GetCover ok file={file_name!r}")
        _ok({"fileName": file_name, "mimeType": mime})
    except Exception as e:
        _plg(f"stage=GetCover err exception {_trunc(str(e), 200)!r}")
        _err("network", str(e), True)


@extism.plugin_fn
def GetAlbumInfo():
    try:
        data = _input()
        _ = _api_key(data)
        _ = _shared_secret(data)
        album_name, album_artist = _album_query(data)
        _plg(
            f"stage=GetAlbumInfo start album={_trunc(album_name, 48)!r} "
            f"artist={_trunc(album_artist, 48)!r}"
        )
        if not album_name:
            _plg("stage=GetAlbumInfo err=missing_album_name")
            _err("invalid_request", "albumName is required", False)
            return
        if not album_artist:
            sr = _call_json(
                data,
                "album.search",
                {"album": album_name, "limit": "3"},
            )
            matches = ((sr.get("results") or {}).get("albummatches") or {}).get(
                "album"
            ) or []
            if isinstance(matches, dict):
                matches = [matches]
            album_artist = ""
            if matches:
                album_artist = str((matches[0] or {}).get("artist", "")).strip()
            if not album_artist:
                _err(
                    "no_match",
                    "Album artist unknown; set albumArtist in query for Last.fm",
                    False,
                )
                return
        info = _call_json(
            data,
            "album.getinfo",
            {
                "album": album_name,
                "artist": album_artist,
                "autocorrect": "1",
                "lang": "zh",
            },
        )
        alb = info.get("album") or {}
        if not isinstance(alb, dict):
            _err("no_match", "unexpected Last.fm album payload", False)
            return
        image_url = _best_album_image_url(alb)
        cover_name = ""
        if image_url:
            body = _http_get_bytes(image_url)
            if body:
                cover_name = _write_cover_file(body)[0]
        wiki = _wiki_as_dict(alb.get("wiki"))
        intro = str(wiki.get("summary", "")).strip()
        released = str(alb.get("releasedate", "")).strip()
        if not released:
            released = str(alb.get("released", "")).strip()
        out = {
            "albumName": str(alb.get("name", "") or album_name).strip(),
            "albumArtist": _album_artist_name_from_obj(alb, album_artist),
            "albumCover": cover_name,
            "albumReleaseDate": released,
            "albumIntroduction": intro,
        }
        _plg(f"stage=GetAlbumInfo ok name={_trunc(out['albumName'], 48)!r}")
        _ok(out)
    except Exception as e:
        msg = str(e)
        _plg(f"stage=GetAlbumInfo err exception {_trunc(msg, 200)!r}")
        if "not found" in msg.lower():
            _err("no_match", "album not found on Last.fm", False)
            return
        _err("network", msg, True)


@extism.plugin_fn
def GetArtistInfo():
    try:
        data = _input()
        _ = _api_key(data)
        _ = _shared_secret(data)
        name = _artist_query(data)
        _plg(f"stage=GetArtistInfo start artist={_trunc(name, 64)!r}")
        if not name:
            _plg("stage=GetArtistInfo err=missing_artist_name")
            _err("invalid_request", "artistName is required", False)
            return
        info = _artist_info_with_auth(data, name)
        artist_obj = info.get("artist") or {}
        if not isinstance(artist_obj, dict):
            _plg("stage=GetArtistInfo err=unexpected_payload")
            _err("no_match", "unexpected Last.fm artist payload", False)
            return
        display = str(artist_obj.get("name", "") or name).strip()
        image_url = _best_image_url(artist_obj)
        avatar = ""
        if image_url:
            body = _http_get_bytes(image_url)
            if body:
                avatar = _write_cover_file(body)[0]
        wiki = _wiki_as_dict(artist_obj.get("wiki"))
        intro = str(wiki.get("summary", "")).strip()
        _plg(f"stage=GetArtistInfo ok name={_trunc(display, 64)!r}")
        _ok(
            {
                "artistName": display,
                "artistAvatar": avatar,
                "artistIntroduction": intro,
                "nationality": "",
            }
        )
    except Exception as e:
        _plg(f"stage=GetArtistInfo err exception {_trunc(str(e), 200)!r}")
        _err("network", str(e), True)

