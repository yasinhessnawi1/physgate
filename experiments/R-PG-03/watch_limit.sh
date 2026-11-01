#!/usr/bin/env bash
# R-PG-03, CRITERIA.md §10: the usage-limit watcher, for a block, an authoring session and the
# reality reading. Derived from R-PG-01b's abort_on_limit.sh, itself derived from the practice
# cycle's abort guard. It logs counts and causes only.
#
# Usage: watch_limit.sh <log> <kind> <pid> <dir> [<dir> ...] [-- <pid> <dir> [<dir> ...]] ...
#   <kind>  block      each group is an arm: its pid, its run directory and its scratch directory.
#                      At the first session that ends with usage_limit_reached every arm's group is
#                      stopped, so no further session runs into the limit; then every session the
#                      review roots' process records prove still running (checks.py stop-sessions,
#                      which signals nothing else), and every session's credential directory is
#                      removed. A block's directories are new, so every file in them counts.
#           authoring  one group: the step's pid and the authoring's records
#           reality    one group: the sessions' runner pid and its output directory
#                      These directories keep every earlier step's files for good (a cut turn's
#                      stream, a failed call's output), so only a file written after the watcher
#                      started counts: one modified after a stamp it makes at its start. A step here
#                      runs one session at a time and starts nothing after a session that ends on the
#                      limit (authoring.py ends the step with that turn; reality.py run writes
#                      STOPPED), so at a limit the watcher logs it and signals nothing: the step
#                      finishes its own records (the turn's outcome, audit and state; the failed
#                      call's file), which a kill would lose.
# Each <pid> was started under setsid, so it leads its own process group. The watcher notes each
# one's start time, and signals a group only while its leader is still that process. Off the run
# machine (Linux) it signals nothing. When everything it watches has ended it looks once more, and
# logs what it found.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="$1"; KIND="$2"; shift 2
case "$KIND" in block|authoring|reality) ;; *) echo "usage: $0 <log> block|authoring|reality <pid> <dir>... [-- ...]" >&2; exit 2 ;; esac
PIDS=(); DIRS=(); SCRATCH=(); STARTS=()
started() { ps -o lstart= -p "$1" 2>/dev/null | tr -s ' ' | sed 's/^ //; s/ $//'; }
while [ $# -ge 2 ]; do
  pid="$1"; shift
  PIDS+=("$pid"); STARTS+=("$(started "$pid")")
  group=()
  while [ $# -gt 0 ] && [ "$1" != "--" ]; do group+=("$1"); DIRS+=("$1"); shift; done
  [ "$KIND" = block ] && [ "${#group[@]}" -ge 2 ] && SCRATCH+=("${group[1]}")
  [ "${1:-}" = "--" ] && shift
done
same() { [ -n "${STARTS[$1]}" ] && [ "$(started "${PIDS[$1]}")" = "${STARTS[$1]}" ]; }
alive() { local i; for i in "${!PIDS[@]}"; do kill -0 "${PIDS[$i]}" 2>/dev/null && same "$i" && return 0; done; return 1; }
STAMP=""
if [ "$KIND" != block ]; then
  STAMP="$(mktemp "${TMPDIR:-/tmp}/rp3-watch.XXXXXX")" || exit 2
  trap 'rm -f "$STAMP"' EXIT
fi
files() { # the regular files under the directories with one of the suffixes given, NUL-separated
  local newer=() names=() s
  [ -n "$STAMP" ] && newer=(-newer "$STAMP")
  for s in "$@"; do names+=(-o -name "*$s"); done
  # find follows no symlink (-P); -type f never opens a FIFO, socket or device
  find "${DIRS[@]}" -type f \( "${names[@]:1}" \) "${newer[@]}" -print0 2>/dev/null
}
count() {
  lim=$(files .jsonl .json .err .txt | xargs -0 grep -l -D skip -- 'usage_limit_reached' 2>/dev/null | wc -l | tr -d ' ')
  r429=$(files .jsonl | xargs -0 grep -ho -D skip -- '"api_error_status": *429' 2>/dev/null | wc -l | tr -d ' ')
}
NOTED=0
while alive; do
  count
  if [ "$lim" -gt 0 ] && [ "$KIND" != block ]; then
    if [ "$NOTED" = 0 ]; then
      echo "LIMIT $(date -u +%FT%TZ) $KIND: usage_limit_reached files $lim, 429s $r429; nothing signalled: the step finishes its records and starts nothing more" | tee -a "$LOG"
      NOTED=1
    fi
  elif [ "$lim" -gt 0 ]; then
    if [ "$(uname -s)" != Linux ]; then
      echo "ABORT $(date -u +%FT%TZ) $KIND: usage_limit_reached files $lim, 429s $r429; nothing signalled off the run machine" | tee -a "$LOG"
      exit 1
    fi
    echo "ABORT $(date -u +%FT%TZ) $KIND: usage_limit_reached files $lim, 429s $r429; everything watched stopped" | tee -a "$LOG"
    for i in "${!PIDS[@]}"; do
      p="${PIDS[$i]}"
      if same "$i" && [ "$(ps -o pgid= -p "$p" 2>/dev/null | tr -d ' ')" = "$p" ]; then
        kill -TERM -- "-$p" 2>/dev/null
      fi
    done
    if [ "$KIND" = block ]; then
      sleep 2
      args=(); for s in "${SCRATCH[@]}"; do args+=(--scratch "$s"); done
      status=0
      out="$(uv run --frozen --project "$HERE/../.." python -I "$HERE/checks.py" stop-sessions "${args[@]}" 2>&1)" || status=$?
      echo "SESSIONS $(printf '%s' "$out" | tail -n 1)" | tee -a "$LOG"
      [ "$status" = 0 ] || echo "CREDENTIALS NOT CONFIRMED REMOVED (stop-sessions exit $status)" | tee -a "$LOG"
    fi
    exit 0
  fi
  sleep "${RP3_WATCH_SECONDS:-30}"
done
count
if [ "$lim" -gt 0 ]; then
  echo "LIMIT $(date -u +%FT%TZ) $KIND: everything ended; usage_limit_reached files $lim, 429s $r429" | tee -a "$LOG"
else
  echo "WATCHER $(date -u +%FT%TZ) $KIND: everything ended; usage_limit_reached files $lim, 429s $r429" >> "$LOG"
fi
