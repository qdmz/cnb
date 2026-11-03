#!/bin/bash
# Ensure a persistent SSH heartbeat connection to the CNB dev workspace exists.
P="${CNB_KEEPALIVE_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
source "$P/target.env"
if pgrep -f "ssh -N.*${CNB_SSH_TARGET%%@*}" >/dev/null 2>&1; then
  echo "holder alive: $(pgrep -f "ssh -N.*${CNB_SSH_TARGET%%@*}" | tr '\n' ' ')"
  exit 0
fi
setsid ssh -N \
  -o ProxyCommand=none \
  -o StrictHostKeyChecking=accept-new \
  -o ServerAliveInterval=25 -o ServerAliveCountMax=4 \
  -o ExitOnForwardFailure=yes \
  -o ConnectTimeout=25 \
  -o BatchMode=yes \
  -o UserKnownHostsFile="$P/known_hosts" \
  "$CNB_SSH_TARGET" >> "$P/logs/hold.log" 2>&1 < /dev/null &
sleep 6
if pgrep -f "ssh -N.*${CNB_SSH_TARGET%%@*}" >/dev/null 2>&1; then
  echo "holder started: $(pgrep -f "ssh -N.*${CNB_SSH_TARGET%%@*}" | tr '\n' ' ')"
else
  echo "holder FAILED to start; see logs/hold.log"
  tail -3 "$P/logs/hold.log"
  exit 1
fi
