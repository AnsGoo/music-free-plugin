# MusicBrainz Plugin (Go)

Go PDK implementation of MusicFree Extism scraper plugin.

## 环境搭建（开发机）

推荐 macOS / Linux。以下命令在仓库根目录执行。

1) 安装 Go（建议 1.25+）：

```bash
go version
```

2) 安装 `tinygo`（可选，体积更小）或直接使用 Go 原生编译：

```bash
# tinygo 可选，不装也可以
tinygo version
```

3) 安装 Extism CLI（可选，用于本地调试）：

```bash
curl -fsSL https://extism.org/install.sh | bash
extism --version
```

4) 拉取依赖并验证：

```bash
cd plugin/musicbrainz
go mod tidy
go test ./...
```

## Exported Methods

- `ScraperSong`（返回标准化元数据）
- `GetCover`

## Build

```bash
cd plugin/musicbrainz
chmod +x ./build.sh
./build.sh
```

Output:

- `plugin/musicbrainz/plugin.wasm`

