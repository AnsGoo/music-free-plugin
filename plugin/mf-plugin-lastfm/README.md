# Last.fm Python 插件

MusicFree 的 Last.fm Extism（Python PDK）刮削插件。

## 文件

- `plugin.py`: 插件源码（Python PDK）
- `manifest.json`: 插件声明
- `build.sh`: 构建脚本（会生成 `plugin.wasm`）

## 能力（导出函数）

| 导出 | 说明 |
|------|------|
| `ScraperSong` | `track.getInfo` 刮削曲目元数据（标题/艺人/专辑/流派/年份等） |
| `GetCover` | 优先曲目关联**专辑**封面，其次 `album.getinfo`，最后艺人头像 |
| `GetAlbumInfo` | `album.getinfo` / `album.search`，专辑封面与简介 |
| `GetArtistInfo` | `artist.getinfo`，艺人头像与简介 |

## 配置参数

`config.api_key`、`config.shared_secret`（均为必填）

你可以在前端“元数据刮削 -> 插件配置（JSON）”里填写：

```json
{
  "api_key": "YOUR_LASTFM_API_KEY",
  "shared_secret": "YOUR_LASTFM_SHARED_SECRET"
}
```

## 构建说明

此插件需要 `extism-py` 编译器（Python PDK）与 binaryen 的 `wasm-merge/wasm-opt`。

## 环境搭建（开发机）

推荐 macOS / Linux。以下命令在仓库根目录执行。

1) 安装 Python 与 pip：

```bash
python3 --version
python3 -m pip --version
```

2) 安装 `extism-py`：

```bash
python3 -m pip install --user extism-py
```

3) 安装 binaryen（必须包含 `wasm-merge` 与 `wasm-opt`）：

```bash
# macOS (Homebrew)
brew install binaryen

# Ubuntu / Debian
sudo apt-get update && sudo apt-get install -y binaryen
```

4) 确保 PATH 包含用户本地 bin（避免找不到 extism-py）：

```bash
export PATH="$HOME/.local/bin:$PATH"
which extism-py
which wasm-merge
which wasm-opt
```

5) 在本目录执行构建：

```bash
cd plugin/lastfm
chmod +x ./build.sh
./build.sh
```

完成后会输出 `plugin.wasm`。

## 安装到运行时目录

将下列文件打包为 zip 上传（或直接放入插件目录）：

- `manifest.json`
- `plugin.wasm`

运行时目录示例：

```text
backend/data/plugins/lastfm/
  manifest.json
  plugin.wasm
```

