#!/bin/bash
# 拉起固定域名隧道 cloudflared（cnb.qdmzctyun.dpdns.org -> localhost:8081）
# 本文件放在 CNB 工作区的 /workspace 下，随平台代码备份漫游到新环境，
# 由 .cnb.yml 的启动阶段（auto-restore）在环境创建后自动执行。
set -u
BIN=/workspace/.bin/cloudflared
TOK=/workspace/.cf-tunnel-token
if pgrep -x cloudflared >/dev/null 2>&1; then echo "[extras] cloudflared 已在运行"; exit 0; fi
if [ ! -x "$BIN" ]; then
  mkdir -p /workspace/.bin
  curl -fsSL -o "$BIN" https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 && chmod +x "$BIN"
fi
[ -s "$TOK" ] || { echo "[extras] 缺少 $TOK，跳过"; exit 0; }
setsid nohup "$BIN" tunnel run --token-file "$TOK" > /tmp/cloudflared.log 2>&1 < /dev/null &
echo "[extras] cloudflared 已拉起"
