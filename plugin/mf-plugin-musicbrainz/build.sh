#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

go mod tidy
GOOS=wasip1 GOARCH=wasm go build -buildmode=c-shared -o plugin.wasm ./...
echo "Built: $SCRIPT_DIR/plugin.wasm"

