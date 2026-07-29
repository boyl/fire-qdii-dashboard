#!/bin/zsh
set -euo pipefail

PROJECT_DIR="${0:A:h:h}"
PLIST_PATH="${HOME}/Library/LaunchAgents/com.fireqdii.local.plist"
LOG_DIR="${PROJECT_DIR}/data/logs"

if [[ ! -x "${PROJECT_DIR}/.venv/bin/python" ]]; then
  echo "尚未安装，请先运行 ./scripts/install_local.sh"
  exit 1
fi

mkdir -p "${HOME}/Library/LaunchAgents" "$LOG_DIR"

PROJECT_DIR="$PROJECT_DIR" PLIST_PATH="$PLIST_PATH" python3 - <<'PY'
import os
import plistlib
from pathlib import Path

project = Path(os.environ["PROJECT_DIR"]).resolve()
plist_path = Path(os.environ["PLIST_PATH"])
payload = {
    "Label": "com.fireqdii.local",
    "ProgramArguments": [
        str(project / ".venv/bin/python"),
        "-m",
        "uvicorn",
        "server.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "4310",
        "--no-access-log",
    ],
    "WorkingDirectory": str(project),
    "RunAtLoad": True,
    "KeepAlive": True,
    "ProcessType": "Background",
    "StandardOutPath": str(project / "data/logs/service.log"),
    "StandardErrorPath": str(project / "data/logs/service-error.log"),
}
with plist_path.open("wb") as handle:
    plistlib.dump(payload, handle)
PY

launchctl bootout "gui/$(id -u)" "$PLIST_PATH" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
launchctl enable "gui/$(id -u)/com.fireqdii.local"

for attempt in {1..60}; do
  if curl -fsS --max-time 2 http://127.0.0.1:4310/api/health >/dev/null 2>&1; then
    echo "后台服务已安装并启动，地址：http://127.0.0.1:4310"
    exit 0
  fi
  sleep 1
done

echo "后台服务已安装，但未能在 60 秒内启动。"
echo "请查看 ${LOG_DIR}/service-error.log"
exit 1
