#!/bin/zsh
set -euo pipefail

PROJECT_DIR="${0:A:h:h}"
cd "$PROJECT_DIR"

if [[ ! -x .venv/bin/python ]]; then
  echo "尚未安装，请先运行 ./scripts/install_local.sh"
  exit 1
fi

exec .venv/bin/python run_local.py
