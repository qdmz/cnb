#!/bin/bash
# Runs inside a ssh call: ensure lxdapi (8081) and cloudflared are running in the workspace.
pgrep -f "/workspace/lxdapi/server/lxdapi" >/dev/null || {
  cd /workspace/lxdapi/server && setsid nohup ./lxdapi > /tmp/lxdapi.log 2>&1 < /dev/null &
  echo "lxdapi restarted"
}
pgrep -x cloudflared >/dev/null || {
  if [ -s ~/.cf-tunnel-token ] && [ -x ~/cloudflared ]; then
    setsid nohup ~/cloudflared tunnel run --token-file ~/.cf-tunnel-token > /tmp/cloudflared.log 2>&1 < /dev/null &
    echo "cloudflared restarted"
  else
    echo "cloudflared NOT started: token or binary missing"
  fi
}
echo "remote ensured"
