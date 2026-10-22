#!/usr/bin/env bash
# R-LAW-01, CRITERIA.md §12's run order, from a clean checkout of the experiment's commit.
#
#   law_launch.sh preflight <work dir>
#   law_launch.sh calibrate <work dir>
#   law_launch.sh measure   <work dir>
#
# preflight: no VOID, no recorded deviation (deviations.json) and no STOPPED marker unless resuming;
#   RLAW_PRIOR, if set (measure needs it), is the prior adjudication's output at the digest
#   inputs/digests.json records; the checkout is clean and on a commit that holds
#   inputs/digests.json and slice.json; the pinned binary's version; the work dir holds lines,
#   flaws, the slice and the re-gate records. Reads no token and starts no session.
# calibrate: CRITERIA.md §6, round 1 on the slice (coder 1 and coder 2 at once, two lanes each, then
#   the adjudicator), §5.5, the bank rule, the projection check (a deviation stops here; a ledger
#   it cannot read is a stop, resumable), and round 2 if any bank item is taken. Ends by printing
#   the files the "Prompt filled" commit records. Never starts a measured session.
# measure: only once the "Prompt filled" commit is HEAD (prompts/final/ holds the last version run
#   on the slice, each file at the sha256 prompts.json records, and RLAW_PRIOR held to its
#   digest before any session): reality on the injected versions
#   and the measured coding at once (two lanes each), then the rejection controls and the twin
#   versions, then §5.5, the adjudication, the cross-model audit, the reality scoring and the G
#   match. The tally is run by hand after it (law_tally.py).
#
# Every packet dir is blind-checked (law_packets.py blind) before its sessions start.
#
# Stops. A failed call stops the run in the session driver (law_sessions.sh run), and a watcher
# (law_sessions.sh watch) stops it at a usage-limit file or a third rate-limit error of this phase,
# or at the void marker. Either writes STOPPED: no new session starts, the ones in flight end on
# their own, and the phase ends only when the last of them is settled (only VOID kills them). The
# watcher and the driver read only evidence from the phase now running (ledger/phase-start is
# touched as it starts), so a resume is never stopped by the files of the stop it resumes from.
# Nothing is resumed without being told: a stopped phase is resumed only by running the same phase
# again with RLAW_RESUME=1, which keeps every built packet dir, every finished session and every
# computed code, and logs the resume in ledger/interruptions.jsonl. Each stop, failed call and
# resume is an interruption RESULT reports; none is a deviation or changes whether the decision is
# taken.
#
# Environment: RLAW_CLAUDE_BIN, the pinned binary (on this laptop ~/pinned/claude-2.1.301-macos);
# RLAW_PRIOR, the prior adjudication's output (measure).
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
event() { # kind reason: one timed line in interruptions.jsonl
  "$PY" -I -c 'import json, sys; print(json.dumps({"event": sys.argv[1], "step": "launch", "reason": sys.argv[2], "utc": sys.argv[3]}, sort_keys=True))' \
    "$1" "$2" "$(date -u +%FT%TZ)" >> "$WORK/ledger/interruptions.jsonl"
}
die() { # once sessions may run, a stop of the phase is a stop of the run: STOPPED, logged
  say "STOP: $*"
  if [ "${RUNNING:-0}" = 1 ] && [ ! -e "$WORK/ledger/STOPPED" ]; then
    echo "$*" >> "$WORK/ledger/STOPPED"
    event stop "phase ${PHASE#_} stopped: $*"
  fi
  exit 1
}
blind() { "$PY" -I "$HERE/law_packets.py" blind "$1" >> "$LOG" || die "a packet in $1 is not blind"; }

prior_ok() { # file: the prior adjudication's output at the digest inputs/digests.json records
  "$PY" -I - "$HERE/inputs/digests.json" "$1" <<'PRIOR' >/dev/null 2>&1
import hashlib, json, sys
want = json.load(open(sys.argv[1]))["prior_adjudication"]
try:
    have = hashlib.sha256(open(sys.argv[2], "rb").read()).hexdigest()
except OSError:
    sys.exit(1)
sys.exit(0 if have == want else 1)
PRIOR
}

preflight() {
  [ ! -e "$WORK/ledger/VOID" ] || die "VOID: the result is void"
  [ ! -e "$WORK/deviations.json" ] || die "a deviation is recorded in deviations.json: nothing runs"
  [ ! -e "$WORK/ledger/STOPPED" ] || [ "${RLAW_RESUME:-0}" = 1 ] || die "STOPPED: resume only with RLAW_RESUME=1"
  if [ -n "${RLAW_PRIOR:-}" ] || [ "${PHASE#_}" = measure ]; then
    [ -n "${RLAW_PRIOR:-}" ] || die "set RLAW_PRIOR to the prior adjudication's output"
    prior_ok "$RLAW_PRIOR" || die "RLAW_PRIOR is not the prior adjudication at the digest inputs/digests.json records"
  fi
  [ -z "$(git -C "$REPO" status --porcelain -- experiments/R-LAW-01 src knowledge)" ] || die "checkout not clean"
  [ -f "$HERE/inputs/digests.json" ] || die "inputs not filled"
  [ -f "$HERE/slice.json" ] || die "slice not filled"
  cmp -s "$HERE/slice.json" "$WORK/slice.json" || die "work slice.json differs from the committed one"
  for f in lines.jsonl flaws.jsonl units_s1.jsonl units_s6.jsonl regate.jsonl; do
    [ -s "$WORK/$f" ] || die "work dir lacks $f"
  done
  : "${RLAW_CLAUDE_BIN:?set RLAW_CLAUDE_BIN}"
  "$RLAW_CLAUDE_BIN" --version | grep -q '^2\.1\.301 ' || die "binary is not 2.1.301"
  "$PY" -I -c "import json,sys; c=json.load(open('$WORK/group_counts.json')); e=json.load(open('$WORK/extract_counts.json')); sys.exit(0 if (e['lines'],c['after_c'],c['after_d'])==(993,367,348) else 1)" \
    || die "the frozen counts do not hold (a deviation: nothing runs)"
  say "preflight holds at $(git -C "$REPO" rev-parse HEAD)"
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
  blind "$pk/c1"; blind "$pk/c2"
  sessions "slice-r$n-c1" coder "$pk/c1" "$se/c1" "$OPUS" 2 &
  local a=$!
  sessions "slice-r$n-c2" coder "$pk/c2" "$se/c2" "$OPUS" 2 &
  local b=$!
  wait "$a" && wait "$b" || die "a coder step of round $n stopped"
  codes "slice-r$n" c1 "$pk/c1" "$se/c1"
  codes "slice-r$n" c2 "$pk/c2" "$se/c2"
  build "$pk/adj" "$PY" -I "$HERE/law_packets.py" adjudicator "$WORK" "slice-r$n" "$pk/adj"
  blind "$pk/adj"
  if ls "$pk/adj"/P*.md >/dev/null 2>&1; then
    sessions "slice-r$n-adj" adjudicator "$pk/adj" "$se/adj" "$OPUS" 4 || die "the adjudicator of round $n stopped"
    codes "slice-r$n" adj "$pk/adj" "$se/adj"
  fi
}

projection_check() { # §12's projection after round 1: exit 1 is the frozen deviation; exit 2
  # (a ledger it cannot read) or any other failure is a stop of the run, resumable, not a deviation
  local out pc=0
  out="$(bash "$SESS" projection "$RLAW_LEDGER" slice-r1-c1 slice-r1-c2 slice-r1-adj)" || pc=$?
  printf '%s\n' "$out" | tee -a "$LOG"
  case "$pc" in
    0) ;;
    1) echo '["the projection check after calibration round 1 failed"]' > "$WORK/deviations.json"
       die "projection check failed: a deviation before any measured session" ;;
    *) die "the projection check could not read the ledger (exit $pc): a stop, not a deviation" ;;
  esac
}

calibrate() {
  build "$WORK/prompts/v0" "$PY" -I "$HERE/law_packets.py" prompts "$WORK/prompts/v0"
  round 1 "$WORK/prompts/v0"
  build "$WORK/bank.json" "$PY" -I "$HERE/law_slice.py" bank "$WORK" "$WORK/prompts/v1"
  projection_check
  if "$PY" -I -c "import json,sys; sys.exit(0 if json.load(open('$WORK/bank.json'))['round_2'] else 1)"; then
    round 2 "$WORK/prompts/v1"
    FINAL=v1
  else
    FINAL=v0
  fi
  say "calibration done; the final prompt is $FINAL. For the \"Prompt filled\" commit copy:"
  say "  $WORK/prompts/v0 (and v1 if run) -> experiments/R-LAW-01/prompts/, $WORK/prompts/$FINAL -> prompts/final, and bank.json"
}

measure_ready() { # the committed final prompt, every file at its recorded sha256
  local fin="$HERE/prompts/final"
  [ -f "$fin/prompts.json" ] || die "no committed final prompt: the Prompt filled commit comes first"
  "$PY" -I - "$fin" <<'PY' || die "a committed prompt file differs from its recorded sha256"
import hashlib, json, sys, pathlib
d = pathlib.Path(sys.argv[1]); meta = json.loads((d / "prompts.json").read_text())
bad = [n for n, s in meta["sha256"].items() if hashlib.sha256((d / n).read_bytes()).hexdigest() != s]
sys.exit(1 if bad else 0)
PY
}

measure() {
  export RLAW_PROMPTS="$HERE/prompts/final"
  local pk="$WORK/packets" se="$WORK/sessions"
  build "$pk/reality" "$PY" -I "$HERE/law_reality.py" packets "$WORK" "$pk/reality"
  build "$pk/measured" "$PY" -I "$HERE/law_packets.py" coders "$WORK" measured "$pk/measured"
  for d in "$pk/reality" "$pk/measured/c1" "$pk/measured/c2"; do blind "$d"; done
  sessions reality-injected reality "$pk/reality" "$se/reality" "$OPUS" 2 "$pk/reality/injected.txt" &
  local r=$!
  ( sessions measured-c1 coder "$pk/measured/c1" "$se/measured/c1" "$OPUS" 1 & a=$!
    sessions measured-c2 coder "$pk/measured/c2" "$se/measured/c2" "$OPUS" 1 & b=$!
    wait "$a" && wait "$b" ) &
  local c=$!
  wait "$r" || die "reality on the injected versions stopped"
  build "$pk/controls" "$PY" -I "$HERE/law_reality.py" controls "$WORK" "$pk/reality" "$se/reality" "$pk/controls"
  blind "$pk/controls"
  RLAW_SHARED_OUT=1 sessions reality-twin reality "$pk/reality" "$se/reality" "$OPUS" 1 "$pk/reality/twin.txt" &
  local t=$!
  sessions controls reality "$pk/controls" "$se/controls" "$OPUS" 1 || die "the controls stopped"
  wait "$t" || die "reality on the twin versions stopped"
  wait "$c" || die "the measured coding stopped"
  codes measured c1 "$pk/measured/c1" "$se/measured/c1"
  codes measured c2 "$pk/measured/c2" "$se/measured/c2"
  build "$pk/adj" "$PY" -I "$HERE/law_packets.py" adjudicator "$WORK" measured "$pk/adj"
  blind "$pk/adj"
  if ls "$pk/adj"/P*.md >/dev/null 2>&1; then
    sessions measured-adj adjudicator "$pk/adj" "$se/adj" "$OPUS" 4 || die "the adjudication stopped"
    codes measured adj "$pk/adj" "$se/adj"
  fi
  build "$pk/audit" "$PY" -I "$HERE/law_packets.py" audit "$pk/measured/c1" "$pk/audit"
  blind "$pk/audit"
  sessions audit coder "$pk/audit" "$se/audit" "$FABLE" 4 || die "the audit stopped"
  codes audit audit "$pk/audit" "$se/audit"
  "$PY" -I "$HERE/law_reality.py" score "$WORK" "$pk/reality" "$se/reality" "$pk/controls" "$se/controls" "$RLAW_PRIOR" | tee -a "$LOG"
  "$PY" -I "$HERE/law_regate.py" match "$WORK" | tee -a "$LOG"
  say "measured sessions done; next: law_tally.py $WORK"
}

case "$PHASE" in
  preflight) preflight ;;
  calibrate|measure)
    set +e
    # evidence older than this is another phase's, or the stop this one resumes from
    touch "$WORK/ledger/phase-start"
    set -m  # the phase runs in a process group of its own, which the watcher watches
    bash "$0" "_$PHASE" "$WORK" &
    PID=$!
    set +m
    bash "$SESS" watch "$WORK" "$PID" "$WORK/ledger/phase-start" "$PHASE" > >(tee -a "$LOG") 2>&1 &
    W=$!
    wait "$PID"; CODE=$?
    # sessions the phase left in flight end on their own (none starts once STOPPED is written):
    # the phase is over when the last of them is settled
    while kill -0 -- "-$PID" 2>/dev/null; do sleep 5; done
    { kill "$W" && wait "$W"; } 2>/dev/null
    say "phase $PHASE ended, exit $CODE"
    exit "$CODE" ;;
  _calibrate|_measure)
    preflight
    if [ "$PHASE" = _measure ]; then measure_ready; fi
    if [ "${RLAW_RESUME:-0}" = 1 ]; then
      why="$( [ -e "$WORK/ledger/STOPPED" ] && tr '\n' ' ' < "$WORK/ledger/STOPPED" || echo "no STOPPED marker" )"
      event resume "phase ${PHASE#_} resumed after: $why"
      [ -e "$WORK/ledger/STOPPED" ] && mv "$WORK/ledger/STOPPED" "$WORK/ledger/STOPPED.$(date -u +%Y%m%dT%H%M%SZ)"
      say "resuming phase ${PHASE#_}"
    fi
    RUNNING=1  # from here a stop of the phase is a stop of the run
    "${PHASE#_}" ;;
  *) die "unknown phase $PHASE" ;;
esac
