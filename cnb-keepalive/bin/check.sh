#!/bin/bash
# CNB workspace keepalive check v2: SSH holder + in-env self-heal + probes + one log line.
P="${CNB_KEEPALIVE_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
source "$P/target.env"
TS=$(date '+%F %T')
HOLD_OUT=$("$P/bin/hold.sh" 2>&1)
SSH_OK=0; ENSURE=""
if OUT=$(ssh -o ProxyCommand=none -o ConnectTimeout=20 -o BatchMode=yes -o UserKnownHostsFile="$P/known_hosts" "$CNB_SSH_TARGET" 'bash -s' < "$P/bin/ensure-remote.sh" 2>/dev/null); then
  SSH_OK=1; ENSURE=$(echo "$OUT" | tr '\n' ';')
fi
CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 25 "$CNB_PROJECT_URL" 2>/dev/null || echo 000)
FIXED=skip
[ -n "${CNB_FIXED_URL:-}" ] && FIXED=$(curl -s -o /dev/null -w "%{http_code}" --max-time 25 "$CNB_FIXED_URL" 2>/dev/null || echo 000)
echo "$TS hold=[$HOLD_OUT] ssh_ok=$SSH_OK ensure=[$ENSURE] cnbrun_http=$CODE fixed_http=$FIXED" >> "$P/logs/keepalive.log"
echo "ssh_ok=$SSH_OK cnbrun_http=$CODE fixed_http=$FIXED ensure=[$ENSURE]"
[ "$SSH_OK" = 1 ]
