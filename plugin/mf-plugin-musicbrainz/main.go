package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	pdk "github.com/extism/go-pdk"
)

const (
	apiVersion             = "musicfree.plugin.scraper.v1"
	defaultAPIBaseURL      = "https://musicbrainz.org"
	mbWebServicePath       = "/ws/2"
	defaultCoverArtBaseURL = "https://coverartarchive.org"
	defaultUserAgent       = "MusicFree/Plugin-MusicBrainz"
)

func plgLogf(format string, args ...any) {
	_, _ = fmt.Fprintf(os.Stderr, "[mf-plugin-musicbrainz] "+format+"\n", args...)
}

func truncRunes(s string, max int) string {
	s = strings.TrimSpace(s)
	r := []rune(s)
	if len(r) <= max {
		return s
	}
	return string(r[:max]) + "…"
}

func songBrief(in callInput) string {
	return fmt.Sprintf("title=%q artist=%q album=%q", truncRunes(in.Song.Title, 48), truncRunes(in.Song.Artist, 48), truncRunes(in.Song.Album, 32))
}

func albumBrief(in callInput) string {
	return fmt.Sprintf("album=%q artist=%q", truncRunes(in.Album.AlbumName, 48), truncRunes(in.Album.AlbumArtist, 48))
}

func artistBrief(in callInput) string {
	return fmt.Sprintf("artist=%q", truncRunes(in.Artist.ArtistName, 64))
}

// normalizeAPIBaseURL trims the server root; optional suffix /ws/2 is stripped so old configs still work.
func normalizeAPIBaseURL(s string) string {
	root := strings.TrimRight(strings.TrimSpace(s), "/")
	root = strings.TrimSuffix(root, mbWebServicePath)
	root = strings.TrimRight(root, "/")
	if root == "" {
		return defaultAPIBaseURL
	}
	return root
}

func mbWebServiceBase(in callInput) string {
	root := defaultAPIBaseURL
	if in.Config != nil {
		if raw, ok := in.Config["api_base_url"]; ok {
			s := strings.TrimSpace(fmt.Sprint(raw))
			if s != "" {
				root = normalizeAPIBaseURL(s)
			}
		}
	}
	return root + mbWebServicePath
}

// coverArtReleaseFrontURL builds Cover Art Archive style URL: {origin}/release/{id}/front-500
func coverArtReleaseFrontURL(in callInput, releaseID string) string {
	base := defaultCoverArtBaseURL
	if in.Config != nil {
		if raw, ok := in.Config["cover_art_base_url"]; ok {
			s := strings.TrimSpace(fmt.Sprint(raw))
			if s != "" {
				base = strings.TrimRight(s, "/")
			}
		}
	}
	if base == "" {
		base = defaultCoverArtBaseURL
	}
	rid := strings.TrimSpace(releaseID)
	return fmt.Sprintf("%s/release/%s/front-500", base, rid)
}

func userAgent(in callInput) string {
	if in.Config == nil {
		return defaultUserAgent
	}
	raw, ok := in.Config["user_agent"]
	if !ok {
		return defaultUserAgent
	}
	s := strings.TrimSpace(fmt.Sprint(raw))
	if s == "" {
		return defaultUserAgent
	}
	return s
}

func jsonRequestHeaders(in callInput) map[string]string {
	return map[string]string{
		"Accept":     "application/json",
		"User-Agent": userAgent(in),
	}
}

type callInput struct {
	APIVersion string                 `json:"apiVersion"`
	Config     map[string]interface{} `json:"config"`
	Song       struct {
		Title  string `json:"title"`
		Artist string `json:"artist"`
		Album  string `json:"album"`
	} `json:"song"`
	Album struct {
		AlbumName   string `json:"albumName"`
		AlbumArtist string `json:"albumArtist"`
	} `json:"album"`
	Artist struct {
		ArtistName string `json:"artistName"`
	} `json:"artist"`
}

type callError struct {
	Code      string `json:"code"`
	Message   string `json:"message"`
	Retryable bool   `json:"retryable"`
}

type callOutput struct {
	OK    bool        `json:"ok"`
	Data  interface{} `json:"data,omitempty"`
	Error *callError  `json:"error,omitempty"`
}

type musicInfo struct {
	Title      string `json:"title,omitempty"`
	Artist     string `json:"artist,omitempty"`
	Album      string `json:"album,omitempty"`
	Genre      string `json:"genre,omitempty"`
	Year       int    `json:"year,omitempty"`
	Track      int    `json:"track,omitempty"`
	DiscNumber int    `json:"discNumber,omitempty"`
}

type coverOut struct {
	FileName string `json:"fileName"`
	MimeType string `json:"mimeType"`
}

type mbSearchResult struct {
	Recordings []struct {
		ID           string `json:"id"`
		Title        string `json:"title"`
		ArtistCredit []struct {
			Name string `json:"name"`
		} `json:"artist-credit"`
		Releases []struct {
			ID    string `json:"id"`
			Title string `json:"title"`
			Date  string `json:"date"`
		} `json:"releases"`
		Tags []struct {
			Name string `json:"name"`
		} `json:"tags"`
	} `json:"recordings"`
}

type mbReleaseSearchResult struct {
	Releases []struct {
		ID           string `json:"id"`
		Title        string `json:"title"`
		Date         string `json:"date"`
		Status       string `json:"status"`
		ArtistCredit []struct {
			Name string `json:"name"`
		} `json:"artist-credit"`
	} `json:"releases"`
}

type mbArtistSearchResult struct {
	Artists []struct {
		Name           string `json:"name"`
		Disambiguation string `json:"disambiguation"`
	} `json:"artists"`
}

func outputOK(data interface{}) int32 {
	_ = pdk.OutputJSON(callOutput{OK: true, Data: data})
	return 0
}

func outputErr(code, message string, retryable bool) int32 {
	_ = pdk.OutputJSON(callOutput{
		OK: false,
		Error: &callError{
			Code:      code,
			Message:   message,
			Retryable: retryable,
		},
	})
	return 0
}

func parseInput() (callInput, error) {
	var in callInput
	if err := pdk.InputJSON(&in); err != nil {
		return in, err
	}
	if strings.TrimSpace(in.APIVersion) == "" {
		in.APIVersion = apiVersion
	}
	return in, nil
}

func requestJSON(method, url string, headers map[string]string, body []byte, out interface{}) error {
	req := pdk.NewHTTPRequest(methodFromString(method), url)
	for k, v := range headers {
		req.SetHeader(k, v)
	}
	if len(body) > 0 {
		req.SetBody(body)
	}
	resp := req.Send()
	if resp.Status() < 200 || resp.Status() >= 300 {
		return fmt.Errorf("http_%d", resp.Status())
	}
	return json.Unmarshal(resp.Body(), out)
}

func methodFromString(method string) pdk.HTTPMethod {
	switch strings.ToUpper(method) {
	case "POST":
		return pdk.MethodPost
	case "PUT":
		return pdk.MethodPut
	default:
		return pdk.MethodGet
	}
}

func searchReleases(in callInput, albumName, albumArtist string) (*mbReleaseSearchResult, error) {
	albumName = strings.TrimSpace(albumName)
	albumArtist = strings.TrimSpace(albumArtist)
	if albumName == "" {
		return nil, fmt.Errorf("missing_album")
	}
	q := fmt.Sprintf(`release:"%s"`, albumName)
	if albumArtist != "" {
		q = fmt.Sprintf(`release:"%s" AND artist:"%s"`, albumName, albumArtist)
	}
	base := mbWebServiceBase(in)
	u := fmt.Sprintf("%s/release?query=%s&fmt=json&limit=5", base, urlQueryEscape(q))
	var result mbReleaseSearchResult
	err := requestJSON("GET", u, jsonRequestHeaders(in), nil, &result)
	if err != nil {
		return nil, err
	}
	if len(result.Releases) == 0 {
		return nil, fmt.Errorf("no_match")
	}
	return &result, nil
}

func searchArtistsMB(in callInput, artistName string) (*mbArtistSearchResult, error) {
	artistName = strings.TrimSpace(artistName)
	if artistName == "" {
		return nil, fmt.Errorf("missing_artist")
	}
	q := fmt.Sprintf(`artist:"%s"`, artistName)
	base := mbWebServiceBase(in)
	u := fmt.Sprintf("%s/artist?query=%s&fmt=json&limit=5", base, urlQueryEscape(q))
	var result mbArtistSearchResult
	err := requestJSON("GET", u, jsonRequestHeaders(in), nil, &result)
	if err != nil {
		return nil, err
	}
	if len(result.Artists) == 0 {
		return nil, fmt.Errorf("no_match")
	}
	return &result, nil
}

func searchMusicBrainz(in callInput) (*mbSearchResult, error) {
	title := strings.TrimSpace(in.Song.Title)
	artist := strings.TrimSpace(in.Song.Artist)
	if title == "" || artist == "" {
		return nil, fmt.Errorf("missing_title_or_artist")
	}
	q := fmt.Sprintf(`recording:"%s" AND artist:"%s"`, title, artist)
	if strings.TrimSpace(in.Song.Album) != "" {
		q = fmt.Sprintf(`recording:"%s" AND artist:"%s" AND release:"%s"`, title, artist, strings.TrimSpace(in.Song.Album))
	}
	base := mbWebServiceBase(in)
	url := fmt.Sprintf("%s/recording?query=%s&fmt=json&limit=5", base, urlQueryEscape(q))
	var result mbSearchResult
	err := requestJSON("GET", url, jsonRequestHeaders(in), nil, &result)
	if err != nil {
		return nil, err
	}
	if len(result.Recordings) == 0 {
		return nil, fmt.Errorf("no_match")
	}
	return &result, nil
}

func urlQueryEscape(s string) string {
	r := strings.NewReplacer(" ", "%20", "\"", "%22", ":", "%3A", "/", "%2F", "?", "%3F", "&", "%26", "+", "%2B")
	return r.Replace(s)
}

func buildMusicInfo(r *mbSearchResult) musicInfo {
	item := r.Recordings[0]
	info := musicInfo{
		Title: item.Title,
	}
	if len(item.ArtistCredit) > 0 {
		info.Artist = item.ArtistCredit[0].Name
	}
	if len(item.Releases) > 0 {
		info.Album = item.Releases[0].Title
		if len(item.Releases[0].Date) >= 4 {
			var year int
			fmt.Sscanf(item.Releases[0].Date[:4], "%d", &year)
			if year > 0 {
				info.Year = year
			}
		}
	}
	if len(item.Tags) > 0 {
		info.Genre = item.Tags[0].Name
	}
	return info
}

func writeCoverAndReturn(data []byte) (coverOut, error) {
	sum := sha256.Sum256(data)
	key := "sha256-" + hex.EncodeToString(sum[:])
	ext := ".jpg"
	mime := "image/jpeg"
	if len(data) >= 8 && string(data[:8]) == "\x89PNG\r\n\x1a\n" {
		ext = ".png"
		mime = "image/png"
	} else if len(data) >= 12 && string(data[:4]) == "RIFF" && string(data[8:12]) == "WEBP" {
		ext = ".webp"
		mime = "image/webp"
	}
	fileName := key + ext
	dst := filepath.Join("/coverArt", fileName)
	tmp := dst + ".tmp"
	if err := os.WriteFile(tmp, data, 0o644); err != nil {
		return coverOut{}, err
	}
	if err := os.Rename(tmp, dst); err != nil {
		_ = os.Remove(tmp)
		return coverOut{}, err
	}
	return coverOut{FileName: fileName, MimeType: mime}, nil
}

//go:wasmexport ScraperSong
func ScraperSong() int32 {
	in, err := parseInput()
	if err != nil {
		plgLogf("stage=ScraperSong err=invalid_input detail=%v", err)
		return outputErr("invalid_request", err.Error(), false)
	}
	plgLogf("stage=ScraperSong start %s", songBrief(in))
	result, err := searchMusicBrainz(in)
	if err != nil {
		plgLogf("stage=ScraperSong err detail=%s", truncRunes(err.Error(), 160))
		if strings.Contains(err.Error(), "no_match") {
			return outputErr("no_match", "No matched result in MusicBrainz", false)
		}
		return outputErr("network", err.Error(), true)
	}
	raw, _ := json.Marshal(result)
	pdk.SetVar("last_search", raw)
	plgLogf("stage=ScraperSong ok")
	return outputOK(buildMusicInfo(result))
}

//go:wasmexport GetCover
func GetCover() int32 {
	in, err := parseInput()
	if err != nil {
		plgLogf("stage=GetCover err=invalid_input detail=%v", err)
		return outputErr("invalid_request", err.Error(), false)
	}
	plgLogf("stage=GetCover start %s", songBrief(in))
	result, err := searchMusicBrainz(in)
	if err != nil || len(result.Recordings) == 0 || len(result.Recordings[0].Releases) == 0 {
		plgLogf("stage=GetCover err=no_release")
		return outputErr("no_match", "No cover release id from MusicBrainz", false)
	}
	releaseID := strings.TrimSpace(result.Recordings[0].Releases[0].ID)
	if releaseID == "" {
		plgLogf("stage=GetCover err=empty_release_id")
		return outputErr("no_match", "No cover release id from MusicBrainz", false)
	}
	coverURL := coverArtReleaseFrontURL(in, releaseID)
	req := pdk.NewHTTPRequest(pdk.MethodGet, coverURL)
	req.SetHeader("Accept", "image/*")
	req.SetHeader("User-Agent", userAgent(in))
	resp := req.Send()
	if resp.Status() < 200 || resp.Status() >= 300 {
		plgLogf("stage=GetCover err=http status=%d", resp.Status())
		return outputErr("no_match", fmt.Sprintf("cover_api_status_%d", resp.Status()), false)
	}
	out, err := writeCoverAndReturn(resp.Body())
	if err != nil {
		plgLogf("stage=GetCover err=write_cover detail=%v", err)
		return outputErr("internal", err.Error(), false)
	}
	plgLogf("stage=GetCover ok file=%s", out.FileName)
	return outputOK(out)
}

//go:wasmexport GetAlbumInfo
func GetAlbumInfo() int32 {
	in, err := parseInput()
	if err != nil {
		plgLogf("stage=GetAlbumInfo err=invalid_input detail=%v", err)
		return outputErr("invalid_request", err.Error(), false)
	}
	plgLogf("stage=GetAlbumInfo start %s", albumBrief(in))
	res, err := searchReleases(in, in.Album.AlbumName, in.Album.AlbumArtist)
	if err != nil {
		plgLogf("stage=GetAlbumInfo err detail=%s", truncRunes(err.Error(), 160))
		if strings.Contains(err.Error(), "no_match") {
			return outputErr("no_match", "No release in MusicBrainz", false)
		}
		if strings.Contains(err.Error(), "missing_album") {
			return outputErr("invalid_request", "albumName is required", false)
		}
		return outputErr("network", err.Error(), true)
	}
	rel := res.Releases[0]
	artistOut := strings.TrimSpace(in.Album.AlbumArtist)
	if len(rel.ArtistCredit) > 0 && strings.TrimSpace(rel.ArtistCredit[0].Name) != "" {
		artistOut = rel.ArtistCredit[0].Name
	}
	// CAA 按 release 维度存图：评分第一的发行未必有封面，依次尝试搜索结果中的多条 release。
	coverName := ""
	for _, cand := range res.Releases {
		releaseID := strings.TrimSpace(cand.ID)
		if releaseID == "" {
			continue
		}
		coverURL := coverArtReleaseFrontURL(in, releaseID)
		req := pdk.NewHTTPRequest(pdk.MethodGet, coverURL)
		req.SetHeader("Accept", "image/*")
		req.SetHeader("User-Agent", userAgent(in))
		resp := req.Send()
		if resp.Status() >= 200 && resp.Status() < 300 && len(resp.Body()) > 0 {
			if co, err := writeCoverAndReturn(resp.Body()); err == nil {
				coverName = co.FileName
				break
			}
		}
	}
	plgLogf("stage=GetAlbumInfo ok name=%q", strings.TrimSpace(rel.Title))
	return outputOK(map[string]string{
		"albumName":         strings.TrimSpace(rel.Title),
		"albumArtist":       strings.TrimSpace(artistOut),
		"albumCover":        coverName,
		"albumReleaseDate":  strings.TrimSpace(rel.Date),
		"albumIntroduction": "",
	})
}

//go:wasmexport GetArtistInfo
func GetArtistInfo() int32 {
	in, err := parseInput()
	if err != nil {
		plgLogf("stage=GetArtistInfo err=invalid_input detail=%v", err)
		return outputErr("invalid_request", err.Error(), false)
	}
	plgLogf("stage=GetArtistInfo start %s", artistBrief(in))
	res, err := searchArtistsMB(in, in.Artist.ArtistName)
	if err != nil {
		plgLogf("stage=GetArtistInfo err detail=%s", truncRunes(err.Error(), 160))
		if strings.Contains(err.Error(), "no_match") {
			return outputErr("no_match", "No artist in MusicBrainz", false)
		}
		if strings.Contains(err.Error(), "missing_artist") {
			return outputErr("invalid_request", "artistName is required", false)
		}
		return outputErr("network", err.Error(), true)
	}
	ar := res.Artists[0]
	intro := strings.TrimSpace(ar.Disambiguation)
	plgLogf("stage=GetArtistInfo ok name=%q", strings.TrimSpace(ar.Name))
	return outputOK(map[string]string{
		"artistName":         strings.TrimSpace(ar.Name),
		"artistAvatar":       "",
		"artistIntroduction": intro,
		"nationality":        "",
	})
}

func main() {}
