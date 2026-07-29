#!/bin/zsh
set -euo pipefail

PROJECT_DIR="${0:A:h:h}"
cd "$PROJECT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
NODE_BIN_DIR="${NODE_BIN_DIR:-}"

if [[ -n "$NODE_BIN_DIR" ]]; then
  export PATH="$NODE_BIN_DIR:$PATH"
fi

node_version_ok() {
  node -e 'const [major, minor] = process.versions.node.split(".").map(Number); process.exit(major > 20 || (major === 20 && minor >= 19) ? 0 : 1)' 2>/dev/null
}

if ! node_version_ok; then
  NODE_CANDIDATES=(
    "${HOME}"/.nvm/versions/node/v2[2-9]*/bin(N)
    "${HOME}"/.nvm/versions/node/v20.1[9]*/bin(N)
  )
  if (( ${#NODE_CANDIDATES[@]} > 0 )); then
    export PATH="${NODE_CANDIDATES[1]}:$PATH"
  fi
fi

if ! node_version_ok; then
  echo "需要 Node.js 20.19+，请升级后重试。"
  exit 1
fi

"$PYTHON_BIN" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
npm install
npm run build

echo "安装完成。运行 ./scripts/start_local.sh 打开工具。"
echo "如需登录后自动运行，再执行 ./scripts/install_launch_agent.sh。"
