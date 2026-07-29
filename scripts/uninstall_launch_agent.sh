#!/bin/zsh
set -euo pipefail

PLIST_PATH="${HOME}/Library/LaunchAgents/com.fireqdii.local.plist"

launchctl bootout "gui/$(id -u)" "$PLIST_PATH" 2>/dev/null || true
if [[ -f "$PLIST_PATH" ]]; then
  mv "$PLIST_PATH" "${HOME}/.Trash/com.fireqdii.local.plist"
fi

echo "后台服务已移除；数据库与项目文件没有删除。"
