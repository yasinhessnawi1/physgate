#!/usr/bin/env bash
# R-LAW-01, CRITERIA.md §12's run order, from a clean checkout of the experiment's commit.
#
#   law_launch.sh preflight <work dir>
#   law_launch.sh calibrate <work dir>
#   law_launch.sh measure   <work dir>
#
# preflight: the checkout is clean and on a commit that holds inputs/digests.json and slice.json;
#   the pinned binary's digest and version; the work dir holds lines, flaws, the slice and the
#   re-gate records; no VOID or STOPPED marker. Reads no token and starts no session.
# calibrate: CRITERIA.md §6, round 1 on the slice (coder 1 and coder 2 at once, two lanes each, then
#   the adjudicator), §5.5, the bank rule, the projection check (a deviation stops here), and
#   round 2 if any bank item is taken. Ends by printing the files the "Prompt filled" commit
#   records. Never starts a measured session.
# measure: only once the "Prompt filled" commit is HEAD (prompts/final/ holds the last version run
#   on the slice, each file at the sha256 prompts.json records): reality on the injected versions
#   and the measured coding at once (two lanes each), then the rejection controls and the twin
#   versions, then §5.5, the adjudication, the cross-model audit, the reality scoring and the G
#   match. The tally is run by hand after it (law_tally.py).
#
# A watcher (abort_on_limit's pattern) stops the whole phase at the first usage limit, the third
# rate-limit error or the void marker. Nothing is resumed without being told: a stopped phase is
# resumed only by running the same phase again with RLAW_RESUME=1, which keeps every built packet
# dir, every finished session and every computed code, and logs the resume in
# ledger/interruptions.jsonl (each stop and resume is a deviation the RESULT counts).
#
# Environment: RLAW_CLAUDE_BIN, the pinned binary (on this laptop ~/pinned/claude-2.1.301-macos).
# The sessions use the account this machine's Claude Code is logged in to, which must be the
# development account; no token is read or printed here.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
PY="$REPO/.venv/bin/python"
SESS="$HERE/law_sessions.sh"
OPUS=claude-opus-5-5
FABLE=claude-fable-5-1

PHASE="${1:?preflight, calibrate or measure}"
WORK="$(cd "${2:?work dir}" && pwd)"
LOG="$WORK/launch.log"
export RLAW_LEDGER="$WORK/ledger/ledger.jsonl"
mkdir -p "$WORK/ledger"

say() { echo "$(date -u +%FT%TZ) $*" | tee -a "$LOG"; }
die() { say "STOP: $*"; exit 1; }

preflight() {
  [ -z "$(git -C "$REPO" status --porcelain -- experiments/R-LAW-01 src knowledge)" ] || die "checkout not clean"
  [ -f "$HERE/inputs/digests.json" ] || die "inputs not filled"
  [ -f "$HERE/slice.json" ] || die "slice not filled"
  cmp -s "$HERE/slice.json" "$WORK/slice.json" || die "work slice.json differs from the committed one"
  for f in lines.jsonl flaws.jsonl units_s1.jsonl units_s6.jsonl regate.jsonl; do
    [ -s "$WORK/$f" ] || die "work dir lacks $f"
  done
  [ ! -e "$WORK/ledger/VOID" ] || die "VOID: the result is void"
  [ ! -e "$WORK/ledger/STOPPED" ] || [ "${RLAW_RESUME:-0}" = 1 ] || die "STOPPED: resume only with RLAW_RESUME=1"
  : "${RLAW_CLAUDE_BIN:?set RLAW_CLAUDE_BIN}"
  "$RLAW_CLAUDE_BIN" --version | grep -q '^2\.1\.301 ' || die "binary is not 2.1.301"
  "$PY" -I -c "import json,sys; c=json.load(open('$WORK/group_counts.json')); e=json.load(open('$WORK/extract_counts.json')); sys.exit(0 if (e['lines'],c['after_c'],c['after_d'])==(993,367,348) else 1)" \
    || die "the frozen counts do not hold (a deviation: nothing runs)"
  say "preflight holds at $(git -C "$REPO" rev-parse HEAD)"
}

watch() { # pid: stop the phase at a usage limit, a third 429, or VOID
  local pid="$1"
  while kill -0 "$pid" 2>/dev/null; do
    lim=$(grep -rl --include='*.json' --include='*.err' 'usage_limit_reached' "$WORK/sessions" 2>/dev/null | wc -l)
    r429=$(grep -rho --include='*.json' '"api_error_status": *429' "$WORK/sessions" 2>/dev/null | wc -l)
    if [ "$lim" -gt 0 ] || [ "$r429" -ge 3 ] || [ -e "$WORK/ledger/VOID" ]; then
      say "ABORT: usage-limit files $lim, 429s $r429, void $( [ -e "$WORK/ledger/VOID" ] && echo yes || echo no)"
      echo "aborted by the watcher" >> "$WORK/ledger/STOPPED"
      printf '{"event": "stop", "reason": "the watcher stopped phase %s", "step": "launch", "utc": "%s"}\n' \
        "$PHASE" "$(date -u +%FT%TZ)" >> "$WORK/ledger/interruptions.jsonl"
      kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid"
      return 0
    fi
    sleep 30
  done
}

sessions() { # step kind packets out model lanes [ids]
  bash "$SESS" run "$@" | tee -a "$LOG"
}

codes() { # step who packets out; on a resume, a step whose codes exist is kept
  if [ -f "$WORK/codes.jsonl" ] && "$PY" -I -c "import json,sys; sys.exit(0 if any(json.loads(l)['step']=='$1' and json.loads(l)['who']=='$2' for l in open('$WORK/codes.jsonl') if l.strip()) else 1)"; then
    say "codes for $1/$2 exist; kept"; return 0
  fi
  "$PY" -I "$HERE/law_verify.py" codes "$WORK" "$1" "$2" "$3" "$4" | tee -a "$LOG"
}

build() { # dir command...: build packets once; on a resume an existing dir is kept as built
  local d="$1"; shift
  if [ -e "$d" ]; then
    [ "${RLAW_RESUME:-0}" = 1 ] || die "$d exists; a phase is never re-run (RLAW_RESUME=1 resumes)"
    say "$d exists; kept"; return 0
  fi
  "$@" | tee -a "$LOG"
}

round() { # n prompts-dir
  local n="$1" pr="$2" pk="$WORK/packets/slice-r$1" se="$WORK/sessions/slice-r$1"
  export RLAW_PROMPTS="$pr"
  build "$pk/c1" "$PY" -I "$HERE/law_packets.py" coders "$WORK" slice "$pk"
  sessions "slice-r$n-c1" coder "$pk/c1" "$se/c1" "$OPUS" 2 &
  local a=$!
  sessions "slice-r$n-c2" coder "$pk/c2" "$se/c2" "$OPUS" 2 &
  local b=$!
  wait "$a" && wait "$b" || die "a coder step of round $n stopped"
  codes "slice-r$n" c1 "$pk/c1" "$se/c1"
  codes "slice-r$n" c2 "$pk/c2" "$se/c2"
  build "$pk/adj" "$PY" -I "$HERE/law_packets.py" adjudicator "$WORK" "slice-r$n" "$pk/adj"
  if ls "$pk/adj"/P*.md >/dev/null 2>&1; then
    sessions "slice-r$n-adj" adjudicator "$pk/adj" "$se/adj" "$OPUS" 4 || die "the adjudicator of round $n stopped"
    codes "slice-r$n" adj "$pk/adj" "$se/adj"
  fi
}

calibrate() {
  preflight
  build "$WORK/prompts/v0" "$PY" -I "$HERE/law_packets.py" prompts "$WORK/prompts/v0"
  round 1 "$WORK/prompts/v0"
  build "$WORK/bank.json" "$PY" -I "$HERE/law_slice.py" bank "$WORK" "$WORK/prompts/v1"
  bash "$SESS" projection "$RLAW_LEDGER" slice-r1-c1 slice-r1-c2 slice-r1-adj | tee -a "$LOG" \
    || { echo '["the projection check after calibration round 1 failed"]' > "$WORK/deviations.json"; die "projection check failed: a deviation before any measured session"; }
  if "$PY" -I -c "import json,sys; sys.exit(0 if json.load(open('$WORK/bank.json'))['round_2'] else 1)"; then
    round 2 "$WORK/prompts/v1"
    FINAL=v1
  else
    FINAL=v0
  fi
  say "calibration done; the final prompt is $FINAL. For the \"Prompt filled\" commit copy:"
  say "  $WORK/prompts/v0 (and v1 if run) -> experiments/R-LAW-01/prompts/, $WORK/prompts/$FINAL -> prompts/final, and bank.json"
}

measure() {
  preflight
  local fin="$HERE/prompts/final"
  [ -f "$fin/prompts.json" ] || die "no committed final prompt: the Prompt filled commit comes first"
  "$PY" -I - "$fin" <<'PY' || die "a committed prompt file differs from its recorded sha256"
import hashlib, json, sys, pathlib
d = pathlib.Path(sys.argv[1]); meta = json.loads((d / "prompts.json").read_text())
bad = [n for n, s in meta["sha256"].items() if hashlib.sha256((d / n).read_bytes()).hexdigest() != s]
sys.exit(1 if bad else 0)
PY
  export RLAW_PROMPTS="$fin"
  local pk="$WORK/packets" se="$WORK/sessions"
  build "$pk/reality" "$PY" -I "$HERE/law_reality.py" packets "$WORK" "$pk/reality"
  build "$pk/measured" "$PY" -I "$HERE/law_packets.py" coders "$WORK" measured "$pk/measured"
  for d in "$pk/reality" "$pk/measured/c1" "$pk/measured/c2"; do
    "$PY" -I "$HERE/law_packets.py" blind "$d" >> "$LOG" || die "a packet in $d is not blind"
  done
  sessions reality-injected reality "$pk/reality" "$se/reality" "$OPUS" 2 "$pk/reality/injected.txt" &
  local r=$!
  ( sessions measured-c1 coder "$pk/measured/c1" "$se/measured/c1" "$OPUS" 1 & a=$!
    sessions measured-c2 coder "$pk/measured/c2" "$se/measured/c2" "$OPUS" 1 & b=$!
    wait "$a" && wait "$b" ) &
  local c=$!
  wait "$r" || die "reality on the injected versions stopped"
  build "$pk/controls" "$PY" -I "$HERE/law_reality.py" controls "$WORK" "$pk/reality" "$se/reality" "$pk/controls"
  RLAW_SHARED_OUT=1 sessions reality-twin reality "$pk/reality" "$se/reality" "$OPUS" 1 "$pk/reality/twin.txt" &
  local t=$!
  sessions controls reality "$pk/controls" "$se/controls" "$OPUS" 1 || die "the controls stopped"
  wait "$t" || die "reality on the twin versions stopped"
  wait "$c" || die "the measured coding stopped"
  codes measured c1 "$pk/measured/c1" "$se/measured/c1"
  codes measured c2 "$pk/measured/c2" "$se/measured/c2"
  build "$pk/adj" "$PY" -I "$HERE/law_packets.py" adjudicator "$WORK" measured "$pk/adj"
  if ls "$pk/adj"/P*.md >/dev/null 2>&1; then
    sessions measured-adj adjudicator "$pk/adj" "$se/adj" "$OPUS" 4 || die "the adjudication stopped"
    codes measured adj "$pk/adj" "$se/adj"
  fi
  build "$pk/audit" "$PY" -I "$HERE/law_packets.py" audit "$pk/measured/c1" "$pk/audit"
  sessions audit coder "$pk/audit" "$se/audit" "$FABLE" 4 || die "the audit stopped"
  codes audit audit "$pk/audit" "$se/audit"
  "$PY" -I "$HERE/law_reality.py" score "$WORK" "$pk/reality" "$se/reality" "$pk/controls" "$se/controls" "${RLAW_PRIOR:?set RLAW_PRIOR to the prior adjudication output}" | tee -a "$LOG"
  "$PY" -I "$HERE/law_regate.py" match "$WORK" | tee -a "$LOG"
  say "measured sessions done; next: law_tally.py $WORK"
}

case "$PHASE" in
  preflight) preflight ;;
  calibrate|measure)
    set +e
    set -m  # the phase runs in a process group of its own, so the watcher stops all of it
    bash "$0" "_$PHASE" "$WORK" &
    PID=$!
    set +m
    watch "$PID" &
    W=$!
    wait "$PID"; CODE=$?
    kill "$W" 2>/dev/null || true
    say "phase $PHASE ended, exit $CODE"
    exit "$CODE" ;;
  _calibrate|_measure)
    if [ "${RLAW_RESUME:-0}" = 1 ]; then
      why="$( [ -e "$WORK/ledger/STOPPED" ] && tr '\n' ' ' < "$WORK/ledger/STOPPED" || echo "no STOPPED marker" )"
      printf '{"event": "resume", "reason": "phase %s resumed after: %s", "step": "launch", "utc": "%s"}\n' \
        "${PHASE#_}" "$why" "$(date -u +%FT%TZ)" >> "$WORK/ledger/interruptions.jsonl"
      [ -e "$WORK/ledger/STOPPED" ] && mv "$WORK/ledger/STOPPED" "$WORK/ledger/STOPPED.$(date -u +%Y%m%dT%H%M%SZ)"
      say "resuming phase ${PHASE#_}"
    fi
    "${PHASE#_}" ;;
  *) die "unknown phase $PHASE" ;;
esac
