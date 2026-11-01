#!/usr/bin/env bash
# R-PG-01b, CRITERIA.md §11 and §12: the usage-limit watcher, derived from the one the reviewer
# calibration run of 22.10.2026 used (its diff is diffs/abort_on_limit.sh.diff). It stops every arm
# of the round at the first session that ends on a usage limit, so no further session runs into
# the limit; the attempt is void. It logs counts and causes only.
# Usage: abort_on_limit.sh <log> <pid> <run dir> <review root> [<pid> <run dir> <review root> ...]
# Each <pid> is an arm launch.sh started under setsid, so it leads its own process group. The
# watcher notes each one's start time, and signals a group only while its leader is still that
# process. On a limit it stops every arm's group, then every session the review roots' process
# records prove still running (checks.py stop-sessions, which signals nothing else), and removes
# every session's credential directory under the review roots. Off the run machine (Linux) it
# signals nothing. When every arm has ended it looks once more, and logs what it found.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="$1"; shift
PIDS=(); DIRS=(); ROOTS=(); STARTS=()
started() { ps -o lstart= -p "$1" 2>/dev/null | tr -s ' ' | sed 's/^ //; s/ $//'; }
while [ $# -ge 3 ]; do PIDS+=("$1"); DIRS+=("$2" "$3"); ROOTS+=("$3"); STARTS+=("$(started "$1")"); shift 3; done
same() { [ -n "${STARTS[$1]}" ] && [ "$(started "${PIDS[$1]}")" = "${STARTS[$1]}" ]; }
alive() { local i; for i in "${!PIDS[@]}"; do kill -0 "${PIDS[$i]}" 2>/dev/null && same "$i" && return 0; done; return 1; }
count() {
  # -r follows no symlink below the roots; -D skip never opens a FIFO, socket or device
  lim=$(grep -rl -D skip --include='*.jsonl' --include='*.json' --include='*.err' --include='*.txt' 'usage_limit_reached' "${DIRS[@]}" 2>/dev/null | wc -l | tr -d ' ')
  r429=$(grep -rho -D skip --include='*.jsonl' '"api_error_status": *429' "${DIRS[@]}" 2>/dev/null | wc -l | tr -d ' ')
}
while alive; do
  count
  if [ "$lim" -gt 0 ]; then
    if [ "$(uname -s)" != Linux ]; then
      echo "ABORT $(date -u +%FT%TZ): usage_limit_reached files $lim, 429s $r429; attempt void; nothing signalled off the run machine" | tee -a "$LOG"
      exit 1
    fi
    echo "ABORT $(date -u +%FT%TZ): usage_limit_reached files $lim, 429s $r429; every arm stopped; attempt void" | tee -a "$LOG"
    for i in "${!PIDS[@]}"; do
      p="${PIDS[$i]}"
      if same "$i" && [ "$(ps -o pgid= -p "$p" 2>/dev/null | tr -d ' ')" = "$p" ]; then
        kill -TERM -- "-$p" 2>/dev/null
      fi
    done
    sleep 2
    args=(); for r in "${ROOTS[@]}"; do args+=(--root "$r"); done
    # A login file not confirmed removed is logged here, and stops the launcher at the round's end.
    status=0
    out="$(uv run --frozen --project "$HERE/../.." python -I "$HERE/checks.py" stop-sessions "${args[@]}" 2>&1)" || status=$?
    echo "SESSIONS $(printf '%s' "$out" | tail -n 1)" | tee -a "$LOG"
    [ "$status" = 0 ] || echo "CREDENTIALS NOT CONFIRMED REMOVED (stop-sessions exit $status)" | tee -a "$LOG"
    exit 0
  fi
  sleep "${RPB_WATCH_SECONDS:-30}"
done
count
if [ "$lim" -gt 0 ]; then
  echo "LIMIT $(date -u +%FT%TZ): every arm ended; usage_limit_reached files $lim, 429s $r429; attempt void" | tee -a "$LOG"
else
  echo "WATCHER $(date -u +%FT%TZ): every arm ended; usage_limit_reached files $lim, 429s $r429" >> "$LOG"
fi
