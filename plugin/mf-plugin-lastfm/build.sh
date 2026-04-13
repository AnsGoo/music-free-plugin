#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if ! command -v extism-py >/dev/null 2>&1; then
  echo "extism-py 未安装，请先安装 Python PDK 编译器。"
  echo "参考: https://github.com/extism/python-pdk"
  exit 1
fi

extism-py plugin.py -o plugin.wasm
echo "Built: $ROOT_DIR/plugin.wasm"

