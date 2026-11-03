#!/bin/bash
# CNB workspace auto-relaunch: trigger | adopt | status
# Armed only when $P/ARMED exists (created after .cnb.yml api_trigger config is pushed).
P="${CNB_KEEPALIVE_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
source "$P/target.env"
if [ -f "$P/secrets/cnb-token3.txt" ]; then TOK=$(tr -d '[:space:]' < "$P/secrets/cnb-token3.txt"); else TOK=$(tr -d '[:space:]' < "$P/secrets/cnb-token2.txt"); fi
API="https://api.cnb.cool"
SLUG="${CNB_REPO_SLUG:-ypvps/qdmz}"
STATE="$P/logs/relaunch-state.env"
TS=$(date '+%F %T')
log(){ echo "$TS relaunch: $*" >> "$P/logs/keepalive.log"; }

running_json(){
  curl -s --max-time 30 -H "Authorization: Bearer $TOK" "$API/workspace/list?slug=$SLUG&status=running&page_size=5"
}
parse_first(){ # $1=json $2=field
  python3 -c "import json,sys; d=json.loads(sys.argv[1]); l=d.get('list') or []; print(l[0].get(sys.argv[2],'') if l else '')" "$1" "$2"
}

case "${1:-status}" in
trigger)
  [ -f "$P/ARMED" ] || { echo "NOT_ARMED"; exit 3; }
  R=$(running_json); PID=$(parse_first "$R" pipeline_id)
  [ -n "$PID" ] && { echo "ALREADY_RUNNING $PID"; exit 2; }
  if [ -f "$STATE" ]; then
    source "$STATE"
    AGE=$(( $(date +%s) - ${TRIGGERED_EPOCH:-0} ))
    [ "$AGE" -lt 1200 ] && { echo "IN_PROGRESS age=${AGE}s"; exit 0; }
  fi
  OLD_SN=$(echo "$CNB_SSH_TARGET" | sed 's/@.*//; s/-[0-9]*\..*//')
  RESP=$(curl -s --max-time 60 -X POST -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" -d '{"event":"api_trigger"}' "$API/$SLUG/-/build/start")
  echo "TRIGGERED_EPOCH=$(date +%s)" > "$STATE"; echo "OLD_SN=$OLD_SN" >> "$STATE"
  log "trigger sent, resp: $RESP"
  echo "TRIGGERED resp=$RESP"
  ;;
adopt)
  R=$(running_json); PID=$(parse_first "$R" pipeline_id); BIZ=$(parse_first "$R" business_id)
  [ -z "$PID" ] && { echo "NOT_UP_YET"; exit 0; }
  OLD_USER="${CNB_SSH_TARGET%@*}"; OLD_PID="${OLD_USER%%.*}"
  [ "$PID" = "$OLD_PID" ] && { echo "SAME_AS_BEFORE $PID"; exit 0; }
  SN="${PID%-001}"
  NEW_TARGET=""
  for TF in "$P/secrets/cnb-token3.txt" "$P/secrets/cnb-token2.txt"; do
    [ -f "$TF" ] || continue
    T=$(tr -d '[:space:]' < "$TF")
    DET=$(curl -s --max-time 30 -H "Authorization: Bearer $T" "$API/$SLUG/-/workspace/detail/$SN")
    HIT=$(printf '%s' "$DET" | python3 -c "import json,sys; print(json.load(sys.stdin).get('remoteSsh',''))" 2>/dev/null)
    [ -z "$HIT" ] && HIT=$(printf '%s' "$DET" | grep -oE "cnb-[a-z0-9-]+-[0-9]{3}\.[0-9a-f-]{36}-[a-z0-9]+@cnb\.space" | head -1)
    [ -n "$HIT" ] && { NEW_TARGET="$HIT"; break; }
  done
  [ -z "$NEW_TARGET" ] && { echo "DERIVE_FAILED new_pid=$PID sn=$SN (no token with repo-cnb-detail, detail API gave no ssh string)"; log "adopt failed: no ssh string for $SN"; exit 1; }
  if ! ssh -o ProxyCommand=none -o ConnectTimeout=20 -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$P/known_hosts" "$NEW_TARGET" 'echo alive' 2>/dev/null | grep -q alive; then
    echo "SSH_PROBE_FAILED target=$NEW_TARGET"; log "adopt ssh probe failed $NEW_TARGET"; exit 1
  fi
  cat > "$P/target.env" <<EOF2
CNB_SSH_TARGET=$NEW_TARGET
CNB_PROJECT_URL=https://${BIZ}-8081.cnb.run/
CNB_EDITOR_URL=https://${PID}-codebuddy.cnb.space/
EOF2
  for hp in $(pgrep -f "ssh -N"); do kill "$hp" 2>/dev/null; done; sleep 1
  "$P/bin/hold.sh" >/dev/null 2>&1
  OUT=$("$P/bin/check.sh" 2>&1)
  rm -f "$STATE"
  log "adopted $PID business=$BIZ check: $OUT"
  echo "ADOPTED pid=$PID project=https://${BIZ}-8081.cnb.run/ fixed=https://cnb.qdmzctyun.dpdns.org/ check=[$OUT]"
  ;;
status)
  [ -f "$P/ARMED" ] && echo "armed" || echo "not_armed"
  [ -f "$STATE" ] && cat "$STATE"
  R=$(running_json); PID=$(parse_first "$R" pipeline_id)
  echo "running: ${PID:-none}"
  ;;
esac
