#!/usr/bin/env bash
#
# R-PG-01b: the launch checks L1 to L11, then both arms of a round at once. Every check holds the
# checkout to CRITERIA.md §2 and §14; any failure stops the script before a review runs, and
# nothing is resumed. Derived from R-PG-01's launch.sh (its diff is diffs/launch.sh.diff).
#
#   experiments/R-PG-01b/launch.sh --round <1|2> [--checks-only]
#
# Run it on Oracle, as the run account, from the run checkout ~/physgate-r-pg-01b-run at the run
# tag with a clean tree, under setsid nohup so a closed terminal does not end it:
#
#   setsid nohup experiments/R-PG-01b/launch.sh --round <r> > ~/runs/rpg01b/launch-<r>-<attempt>.log 2>&1 < /dev/null &
#
# Before it, the owner writes ~/runs/rpg01b/owner-<r>.json: {"account_label": "...",
# "no_other_session_during_round": true} (L1 records both).
#
# Stages, in order (CRITERIA.md §14):
#   L1  the host, the checkout at the run tag and clean; the account's label and the token's
#       digest prefix; the owner's confirmation; the slot draw and this attempt's slots;
#   L2  the run commit's paths against 8bc03fc and master's "scripts" and "sheet" commits;
#   L3  every pin of §2.2, the instrument tree §2.4 fills, the binary's digest and version;
#   L4  both arms' corpora;
#   L5-L7  every packet of both arms, with no session (packets_identity.py);
#   L8  R4, by R-PG-01's r4_twins.py;
#   L9  R3 for each arm's run, the reviewer's read allowance on the pinned binary, and the
#       reviewer requests' defaults by R-PG-01's dry run (scripted endpoint, no model call);
#   L10 the smoke of §10 on the run account (smoke.py): a whole read of arm F's sheet, no cut;
#   L11 the 5-hour projection, recorded (not a gate);
# then the usage-limit watcher and both arms at once, each `physgate inject` with §2.6's
# invocation; then, when both have ended, the round's end: §5.5's stream check, the rubric
# digests, R6, the void rules of §12 (counts and causes only) and the ledger line.
#
# --checks-only runs L1 to L9 and L11's recording, never L10 and never a review; it never reads
# the token and writes nothing under ~/runs/rpg01b: it needs RPB_RUNS, a records directory of its
# own outside it. Only with it may RPB_MASTER_REF name another ref than origin/master: a trial
# before the master-side commits are merged. The log says so; the run itself never takes either.
#
# §12's stops: L10's cut read or inapplicability, and a second cut read in a round (the round's
# end), are recorded in the slot records, and every later L1 refuses.
#
# §11's fallback, after two voids of a round by the 5-hour limit: the arms run one after the
# other in the drawn order; the second starts at the first 5-hour boundary, counted from the
# round's first session (L10's first smoke), after the first has ended, and never after the first
# arm's watcher stopped it.

set -euo pipefail

STOP_AFTER=run
ROUND=
while [ $# -gt 0 ]; do
  case "$1" in
    --round) ROUND="${2:-}"; shift 2 ;;
    --checks-only) STOP_AFTER=checks; shift ;;
    *) echo "usage: $0 --round <1|2> [--checks-only]" >&2; exit 2 ;;
  esac
done
case "$ROUND" in 1|2) ;; *) echo "usage: $0 --round <1|2> [--checks-only]" >&2; exit 2 ;; esac

# ---- where things go; none of these paths may name the harness or sit in a checkout ----
CHECKOUT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HERE="$CHECKOUT/experiments/R-PG-01b"
BIN="$HOME/pinned/claude-2.1.301"
ENV_FILE="$HOME/.config/physgate-run.env"
MASTER_REF=origin/master
RUNS="$HOME/runs/rpg01b"
if [ "$STOP_AFTER" = checks ]; then
  MASTER_REF="${RPB_MASTER_REF:-$MASTER_REF}"
  real() { python3 -I -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$1"; }
  [ -n "${RPB_RUNS:-}" ] || { echo "REFUSED: --checks-only needs RPB_RUNS, a records directory outside $RUNS" >&2; exit 1; }
  case "$(real "$RPB_RUNS")/" in
    "$(real "$RUNS")/"*) echo "REFUSED: RPB_RUNS lies under $RUNS, the run's records" >&2; exit 1 ;;
  esac
  RUNS="$RPB_RUNS"
elif [ -n "${RPB_MASTER_REF:-}${RPB_RUNS:-}" ]; then
  echo "REFUSED: RPB_MASTER_REF and RPB_RUNS are for --checks-only alone" >&2; exit 1
fi
CODE_8BC03FC="$RUNS/code-8bc03fc"
mkdir -p "$RUNS"
N=1; while [ -e "$RUNS/launch-$ROUND-$N" ]; do N=$((N + 1)); done
LAUNCH="$RUNS/launch-$ROUND-$N"
mkdir "$LAUNCH"

cd "$CHECKOUT"
LOG="$LAUNCH/launch.log"
say() { echo "$*" | tee -a "$LOG"; }
refuse() { say "REFUSED: $*"; exit 1; }
sha() { sha256sum "$1" | cut -d' ' -f1; }
# The records directory reaches the checks alone, never an arm's or a smoke's environment.
py() { RPB_RUNS="$RUNS" uv run --frozen python -I "$@"; }
check() { # name, then the command: its JSON line is logged and kept as $LAUNCH/<name>.json
  local name="$1" out; shift
  out="$("$@")" || { say "$out"; refuse "$name"; }
  printf '%s\n' "$out" > "$LAUNCH/$name.json"
  say "ok  $name $(printf '%s' "$out" | cut -c1-400)"
}
field() { python3 -I -c 'import json,sys; v=json.load(open(sys.argv[1]))
for k in sys.argv[2].split("."): v=v[k]
print(v if not isinstance(v,(list,dict)) else json.dumps(v))' "$LAUNCH/$1.json" "$2"; }

scan_written() { # how path...: rpb_scan or rpb_scan_token over those that exist; 1 on any hit
  local how="$1" p there=() out status=0
  shift
  for p in "$@"; do [ -e "$p" ] && there+=("$p"); done
  [ "${#there[@]}" -gt 0 ] || return 0
  out="$("$how" "${there[@]}")" || status=$?
  say "$how: $(printf '%s' "$out" | tr '\n' ';')"
  return "$status"
}

unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL CLAUDE_CODE_OAUTH_TOKEN
# The run account's token (token.sh): loaded for L10 into one unexported variable, given to the
# smoke and to each arm's process alone through rpb_exec_with_token, never an argument, never
# printed; every file this run wrote is scanned for it after L10 and after the round.
source "$HERE/token.sh"
export DISABLE_AUTOUPDATER=1 PHYSGATE_CLAUDE_BIN="$BIN"
say "== R-PG-01b launch, round $ROUND, launch $N, $(date -u +%Y-%m-%dT%H:%M:%SZ), stop after: $STOP_AFTER"
[ "$STOP_AFTER" = run ] || say "CHECKS ONLY: master ref $MASTER_REF, records $RUNS; no review runs"
uv sync --frozen -q

# ---- L1: the host, the checkout, the account, the slots ----
FLAGS=(--round "$ROUND" --master-ref "$MASTER_REF")
[ "$STOP_AFTER" = checks ] && FLAGS+=(--checks-only)
check L1 py "$HERE/checks.py" L1 "${FLAGS[@]}"
SLOT_I="$(field L1 slots.I)"; SLOT_F="$(field L1 slots.F)"; SEQUENTIAL="$(field L1 sequential)"
slot_paths() { # slot -> RUN SCRATCH INSTALL for it (§2.6)
  RUN="$RUNS/run-$1"; SCRATCH="$HOME/review-scratch/rpb-$1"; INSTALL="$RUNS/install-$1"
}

# ---- L2 to L4: the run commit, the pins, the corpora ----
check L2 py "$HERE/checks.py" L2 --master-ref "$MASTER_REF"
check L3 py "$HERE/checks.py" L3 --master-ref "$MASTER_REF"
check L4 py "$HERE/checks.py" L4 --master-ref "$MASTER_REF"

# ---- L5 to L7: every packet of both arms, and arm I's at 8bc03fc ----
if [ ! -e "$CODE_8BC03FC" ]; then
  git worktree add -q --detach "$CODE_8BC03FC" 8bc03fc65f3a555f8f4f737eb5eeea1c6f179670
fi
[ "$(git -C "$CODE_8BC03FC" rev-parse HEAD)" = 8bc03fc65f3a555f8f4f737eb5eeea1c6f179670 ] \
  && [ -z "$(git -C "$CODE_8BC03FC" status --porcelain)" ] || refuse "$CODE_8BC03FC is not 8bc03fc, clean"
(cd "$CODE_8BC03FC" && uv sync --frozen -q)
PACKETS="$HOME/review-scratch/rpb-packets-$ROUND-$N"
build() { # arm corpus out [project]
  local project=()
  [ -n "${4:-}" ] && project=(--project "$4")
  uv run --frozen "${project[@]}" python -I "$HERE/packets_identity.py" build \
    --arm "$1" --corpus "$CHECKOUT/$2" --root "$PACKETS" --out "$LAUNCH/$3"
}
check packets-I build I corpora/injected-errors/v1 packets-I.record
check packets-F build F corpora/injected-errors/v1-fullsheet packets-F.record
check packets-8bc03fc build I corpora/injected-errors/v1 packets-8bc03fc.record "$CODE_8BC03FC"
check L5-L7 py "$HERE/packets_identity.py" compare --i "$LAUNCH/packets-I.record" \
  --f "$LAUNCH/packets-F.record" --r-pg-01 "$LAUNCH/packets-8bc03fc.record"

# ---- L8: R4, the twins alone, at the run commit ----
check L8 py "$HERE/checks.py" L8 --into "$LAUNCH/r4"

# ---- L9: R3 for each arm's run, the read allowance, the request defaults ----
for slot in "$SLOT_I" "$SLOT_F"; do
  slot_paths "$slot"
  for p in "$RUN" "$INSTALL" "$SCRATCH"; do
    [ ! -e "$p" ] || refuse "$p already exists: a slot is never resumed"
  done
done
slot_paths "$SLOT_I"
check L9-r3-I py experiments/R-PG-01/r3_scan.py "$CHECKOUT" "$SCRATCH" "$RUN" "$INSTALL"
slot_paths "$SLOT_F"
check L9-r3-F py "$HERE/r3_scan_f.py" "$CHECKOUT" "$SCRATCH" "$RUN" "$INSTALL"
uv run --frozen pytest -q -p no:cacheprovider -m integration \
  tests/integration/hooks/test_a_corpus_is_withheld_through_the_real_tool_path.py \
  tests/integration/hooks/test_a_reviewer_reads_only_its_allowance_through_the_real_tool_path.py \
  > "$LAUNCH/r3_allowance.log" 2>&1 || refuse "R3 read allowance on the pinned binary ($LAUNCH/r3_allowance.log)"
say "ok  L9 allowance $(tail -n 1 "$LAUNCH/r3_allowance.log")"
uv run --frozen pytest -q -p no:cacheprovider \
  tests/unit/reviewers/test_what_a_reviewer_is_shown_does_not_say_it_is_evaluated.py \
  > "$LAUNCH/r3_shown.log" 2>&1 || refuse "R3 what a reviewer is shown ($LAUNCH/r3_shown.log)"
say "ok  L9 shown $(tail -n 1 "$LAUNCH/r3_shown.log")"
HEAD_SHA="$(git rev-parse HEAD)"
uv run --frozen python tests/integration/orchestrator/real_instrument_pilot.py \
  --dry-run --out "$LAUNCH/dry" > "$LAUNCH/dry-run.out" 2>&1 || refuse "the dry run exited non-zero"
py - "$LAUNCH/dry/result.json" "$HEAD_SHA" 2.1.301 "$(sha "$BIN")" "$LAUNCH/request_defaults.json" <<'EOF' > "$LAUNCH/L9-defaults.json" || { cat "$LAUNCH/L9-defaults.json" | tee -a "$LOG"; refuse "the dry run"; }
import json, sys
from pathlib import Path
result, head, version, binary, into = sys.argv[1:6]
r = json.loads(Path(result).read_text())
problems = []
if r.get("kind") != "dry-run": problems.append("not a dry run")
# The scripted plan includes a blocked review, so the command's exit is 1 by design; 0 is also
# a completed run. Anything else is a refusal or a crash.
if r.get("exit") not in (0, 1): problems.append(f"the command exited {r.get('exit')}")
if r.get("commit") != head or r.get("dirty") is not False: problems.append("not the run's commit, clean")
if r.get("binary_version") != version or r.get("binary_sha256") != binary: problems.append("not the pinned binary")
if any(r.get("scan", {}).get(k) != 0 for k in ("token", "sk-ant-", "oat01")): problems.append(f"scan {r.get('scan')}")
defaults = r.get("request_defaults") or {}
if not defaults.get("requests"): problems.append("no request was recorded")
Path(into).write_text(json.dumps(defaults, indent=1, sort_keys=True))
print(json.dumps({"dry_run": "ok" if not problems else "refused", "problems": problems,
                  "requests": defaults.get("requests"), "distinct": len(defaults.get("distinct", []))}))
sys.exit(1 if problems else 0)
EOF
say "ok  L9 request defaults $(cat "$LAUNCH/L9-defaults.json"), recorded in $LAUNCH/request_defaults.json"

# ---- L10: the smoke of §10, on the run account ----
if [ "$STOP_AFTER" = run ]; then
  rpb_load_token "$ENV_FILE" 2>> "$LOG" || refuse "the run account's token (see the line above)"
  say "ok  token loaded: one line of the token's shape"
  SMOKE_ROOT="$HOME/review-scratch/rpb-smoke-$ROUND-$N"
  set +e
  ( rpb_exec_with_token uv run --frozen python -I "$HERE/smoke.py" l10 --out "$LAUNCH/smoke" \
      --root "$SMOKE_ROOT" --sheet "$CHECKOUT/corpora/injected-errors/v1-fullsheet/sources.json" ) \
    > "$LAUNCH/L10.json"
  CODE=$?
  set -e
  say "L10 $(cat "$LAUNCH/L10.json")"
  # The launch's own records name the prefixes (this log, the dry run's scan record): the token
  # alone is looked for there; the smoke's own files are scanned for all three.
  { scan_written rpb_scan "$SMOKE_ROOT" "$LAUNCH/smoke" && scan_written rpb_scan_token "$LAUNCH"; } \
    || { rpb_drop_token; refuse "the token's scan found a hit after L10"; }
  case "$CODE" in
    0) say "ok  L10" ;;
    3) py "$HERE/checks.py" stop --round "$ROUND" --reason "L10 found a cut read" | tee -a "$LOG"
       refuse "L10 found a cut read: the round does not start, and the experiment stops (§12)" ;;
    4) py "$HERE/checks.py" stop --round "$ROUND" --reason "L10 cannot be applied" | tee -a "$LOG"
       refuse "L10 cannot be applied: the round does not start, and the experiment stops (§12)" ;;
    *) refuse "L10 failed (exit $CODE)" ;;
  esac
fi

# ---- L11: the 5-hour projection, recorded ----
check L11 py "$HERE/checks.py" L11 --round "$ROUND" --smoke "$LAUNCH/smoke/smoke.json" --launch "$LAUNCH"
[ "$STOP_AFTER" = checks ] && { say "stopped after the checks, as asked"; exit 0; }

# ---- the round: the watcher, then both arms at once (§2.6), each one review at a time ----
arm_start() { # arm slot -> starts it under setsid; PID
  local corpus
  [ "$1" = I ] && corpus=v1 || corpus=v1-fullsheet
  slot_paths "$2"
  rpb_exec_with_token setsid uv run --frozen physgate inject \
    --corpus "$HOME/physgate-r-pg-01b-run/corpora/injected-errors/$corpus" \
    --run-dir "$RUN" \
    --scratch "$SCRATCH" \
    --run-id "rpb-$2" \
    --seed 7 \
    --params "$HOME/physgate-r-pg-01b-run/experiments/R-PG-01/params.json" \
    --install "$INSTALL" \
    --review-clean-twins \
    > "$LAUNCH/arm-$2.log" 2>&1 < /dev/null &
  PID=$!
}
check start py "$HERE/checks.py" start --round "$ROUND" --slots "$SLOT_I,$SLOT_F" --launch "$LAUNCH"
say "== the round starts $(date -u +%Y-%m-%dT%H:%M:%SZ): slots $SLOT_I and $SLOT_F"
declare -A EXITS=()
run_arms() { # slot... : start them at once, watch them, wait for each
  local slots=("$@") pids=() triples=() slot i watcher
  for slot in "${slots[@]}"; do
    if [ "$slot" = "$SLOT_I" ]; then arm_start I "$slot"; else arm_start F "$slot"; fi
    pids+=("$PID"); slot_paths "$slot"; triples+=("$PID" "$RUN" "$SCRATCH")
  done
  "$HERE/abort_on_limit.sh" "$LAUNCH/watcher.log" "${triples[@]}" &
  watcher=$!
  for i in "${!slots[@]}"; do
    set +e; wait "${pids[$i]}"; EXITS[${slots[$i]}]=$?; set -e
  done
  wait "$watcher" || true
}
slot_of() { if [ "$1" = I ]; then echo "$SLOT_I"; else echo "$SLOT_F"; fi; }
if [ "$SEQUENTIAL" = True ]; then
  # §11's fallback after two voids by the 5-hour limit: one arm after the other, in the drawn
  # order, in consecutive windows; the second never starts after the first arm's abort.
  read -r FIRST SECOND <<< "$(field L1 arm_order | tr -d '[]",')"
  run_arms "$(slot_of "$FIRST")"
  SINCE="$(python3 -I -c 'import json, sys; print(json.load(open(sys.argv[1]))["first_started_utc"])' "$LAUNCH/smoke/smoke.json")"
  py "$HERE/checks.py" second-arm --launch "$LAUNCH" --since "$SINCE" > "$LAUNCH/second-arm.json"
  WAIT="$(field second-arm wait_s)"
  if [ "$WAIT" = None ]; then
    say "== the first arm was stopped at a usage limit: the second arm does not start (§11)"
  else
    say "== the second arm starts at the next 5-hour boundary from $SINCE: in ${WAIT}s"
    sleep "$WAIT"
    run_arms "$(slot_of "$SECOND")"
  fi
else
  run_arms "$SLOT_I" "$SLOT_F"
fi
# An arm never started (the fallback's second, after an abort) has no exit: null.
python3 -I -c 'import json,sys; a = sys.argv[1:]; print(json.dumps({a[k]: None if a[k + 1] == "none" else int(a[k + 1]) for k in range(0, len(a), 2)}))' \
  "$SLOT_I" "${EXITS[$SLOT_I]:-none}" "$SLOT_F" "${EXITS[$SLOT_F]:-none}" > "$LAUNCH/exits.json"
say "== the round ended $(date -u +%Y-%m-%dT%H:%M:%SZ), exits $(cat "$LAUNCH/exits.json")"

# ---- the round's end: §5.5, the rubric digests, R6, the void rules; then the ledger line ----
check after py "$HERE/checks.py" after --round "$ROUND" --launch "$LAUNCH"
py "$HERE/ledger.py" round --round "$ROUND" | tee -a "$LOG"
# The token never belongs in what the run wrote: counts only, never a match; a hit is no success.
WRITTEN=("$SMOKE_ROOT" "$LAUNCH/smoke" "$LAUNCH"/arm-*.log "$RUNS/slots.json" "$RUNS"/ledger-round-*)
for slot in "$SLOT_I" "$SLOT_F"; do
  slot_paths "$slot"
  WRITTEN+=("$RUN" "$INSTALL" "$SCRATCH")
done
if ! { scan_written rpb_scan "${WRITTEN[@]}" && scan_written rpb_scan_token "$LAUNCH"; }; then
  rpb_drop_token
  refuse "the token's scan found a hit in what the round wrote"
fi
rpb_drop_token
say "== done $(date -u +%Y-%m-%dT%H:%M:%SZ)"
