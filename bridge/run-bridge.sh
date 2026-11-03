#!/usr/bin/env bash
# chat-bridge 启动包装：从 600 权限配置文件读密码和 token
set -euo pipefail
CONF="/home/hatch/.config/chat-bridge/server.env"
[ -f "$CONF" ] || { echo "missing $CONF" >&2; exit 1; }
set -a; source "$CONF"; set +a
exec python3 /home/hatch/workspace/chat-bridge/bridge.py
