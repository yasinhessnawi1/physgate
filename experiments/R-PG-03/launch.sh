#!/usr/bin/env bash
#
# R-PG-03: the pre-flight refusals, then one block's three arms together (CRITERIA.md §3, §5, §10,
# §13). Every check holds the checkouts to the frozen file and its fills; any failure stops the
# script before a review runs, and nothing is resumed. Derived from R-PG-02's and R-PG-01b's.
#
#   experiments/R-PG-03/launch.sh --block <x1|y1|z1|z2|y2|x2|s|p1|p2> [--checks-only]
#
# Run it on the ARM virtual machine, as the run account, from the run checkout ~/physgate-r-pg-03-run
# at R with a clean tree (and R_K at ~/physgate-r-pg-03-run-k), under setsid nohup:
#
#   setsid nohup experiments/R-PG-03/launch.sh --block x1 > ~/runs/rpg03/launch-x1.log 2>&1 < /dev/null &
#
# Before it, the owner writes ~/runs/rpg03/owner/block-<b>-<attempt>.json:
#   {"account_label": "...", "no_other_session_on_the_run_account": true}
# and, before the first block, ~/runs/rpg03/owner/window.json:
#   {"weekly_limit_reset_confirmed_utc": "2026-11-05T07:00:00Z"}   (read from the usage page)
# W5 is 80 M unless the owner raises it at launch: RP3_W5=<tokens>, recorded in the log.
# The practice cycle's records, for the false-finding control's count before the first block:
#   RP3_PRACTICE_ROUND1=<the kept round's run dir> RP3_PRACTICE_REPEATK=<the noise run's run dir>
#
# Stages, in order:
#   L1  the host, no claude or inject process alive, no login file left; the block's place in the
#       fixed order, its void attempts and its earliest date; the owner's confirmations;
#   L2  R and R_K: the five paths, R_K's promotions line for line, the rubric and generalist_of
#       digests, the knowledge trees, every tree, blob and digest "Commits filled" records;
#   L3  the pinned binary's digest and version;
#   L4  the parameters (R-PG-02's but lanes) and the 3/3/2 split; the block's seeded lane plan;
#   L5  the block's corpus: "Set filled"'s manifest, "Sheet filled"'s sheet, the converter re-run;
#   L6  R4: the twins' precondition again (R-PG-02's twins_fresh.py, unedited);
#   L7  R3: the scan over every set and place (R-PG-02's r3_scan.py, unedited), and the reviewer's
#       read allowance on the pinned binary;
#   L8  the prompt identity check (prompt_identity.py): A2 at R against gr2-r1-run-tree, A1 and B at
#       R_K against eae78c0, every tree fed the same test-corpus bytes;
#   L9  first block only: the false-finding control's five keys counted again (reality.py ff-count);
#   L10 first block only: the whole-read smoke on the run account (streams.py smoke);
#   L11 the 5-hour projection with every ledger line, R-PG-01b's included (ledger.py project);
# then the watcher and the three arms at once, A2 at R, A1 and B at R_K, each one `physgate inject`
# on the block's seed, starting within one minute of each other; an arm that stops in its first
# minute stops the others and voids the attempt. When all have ended: the attempt's end (void causes,
# the stream check, the rubric digests, R6, the lanes), its ledger line, the login files and the
# token's scan of everything written.
#
# --checks-only runs L1 to L9 and L11 (L10 never), never reads the token and never starts a review;
# it needs RP3_RUNS, a records directory of its own outside ~/runs/rpg03, and may name another
# master ref (RP3_MASTER_REF) and skip the host and date checks (RP3_TRIAL_HOST=1). The log says so.

set -euo pipefail

STOP_AFTER=run
BLOCK=
while [ $# -gt 0 ]; do
  case "$1" in
    --block) BLOCK="${2:-}"; shift; [ $# -gt 0 ] && shift ;;
    --checks-only) STOP_AFTER=checks; shift ;;
    *) echo "usage: $0 --block <b> [--checks-only]" >&2; exit 2 ;;
  esac
done
case "$BLOCK" in x1|y1|z1|z2|y2|x2|s|p1|p2) ;; *) echo "usage: $0 --block <b> [--checks-only]" >&2; exit 2 ;; esac

CHECKOUT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HERE="$CHECKOUT/experiments/R-PG-03"
R_K_CHECKOUT="${RP3_R_K:-$HOME/physgate-r-pg-03-run-k}"
BIN="${PHYSGATE_CLAUDE_BIN:-$HOME/pinned/claude-2.1.301}"
ENV_FILE="$HOME/.config/physgate-run.env"
MASTER_REF=origin/master
RUNS="$HOME/runs/rpg03"
TRIAL_HOST=0
if [ "$STOP_AFTER" = checks ]; then
  MASTER_REF="${RP3_MASTER_REF:-$MASTER_REF}"
  real() { python3 -I -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$1"; }
  [ -n "${RP3_RUNS:-}" ] || { echo "REFUSED: --checks-only needs RP3_RUNS, a records directory outside $RUNS" >&2; exit 1; }
  case "$(real "$RP3_RUNS")/" in
    "$(real "$RUNS")/"*) echo "REFUSED: RP3_RUNS lies under $RUNS, the run's records" >&2; exit 1 ;;
  esac
  RUNS="$RP3_RUNS"
  TRIAL_HOST="${RP3_TRIAL_HOST:-0}"
elif [ -n "${RP3_MASTER_REF:-}${RP3_RUNS:-}${RP3_TRIAL_HOST:-}" ]; then
  echo "REFUSED: RP3_MASTER_REF, RP3_RUNS and RP3_TRIAL_HOST are for --checks-only alone" >&2; exit 1
fi
export RP3_RUNS="$RUNS"
SETS="$RUNS/sets"
W5="${RP3_W5:-80000000}"
SEED_OF() { case "$1" in x1) echo 53 ;; y1) echo 59 ;; z1) echo 83 ;; z2) echo 89 ;; y2) echo 67 ;; x2) echo 61 ;; s) echo 71 ;; p1) echo 73 ;; p2) echo 79 ;; esac; }
CORPUS_OF() { case "$1" in p1) echo fresh-v1c-a01-a20 ;; p2) echo fresh-v1c-a21-a40 ;; *) echo "fresh-v2-$1" ;; esac; }
PER_CLASS_OF() { case "$1" in s) echo 10 ;; *) echo 5 ;; esac; }
ARMS=(A2 A1 B)
lower() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }
checkout_of() { case "$1" in A2) echo "$CHECKOUT" ;; *) echo "$R_K_CHECKOUT" ;; esac; }
params_of() { case "$1" in B) echo "$HERE/params_b.json" ;; *) echo "$HERE/params_a.json" ;; esac; }
lanes_of() { case "$1" in B) echo 2 ;; *) echo 3 ;; esac; }
mode_of() { case "$1" in B) echo "--generalist" ;; *) echo "" ;; esac; }

mkdir -p "$RUNS"
N=1; while [ -e "$RUNS/blocks/$BLOCK-$N" ]; do N=$((N + 1)); done
LAUNCH="$RUNS/blocks/$BLOCK-$N"
mkdir -p "$LAUNCH"
LOG="$LAUNCH/launch.log"
cd "$CHECKOUT"
say() { echo "$*" | tee -a "$LOG"; }
refuse() { say "REFUSED: $*"; exit 1; }
py() { uv run --frozen python -I "$@"; }
check() { # name, then the command: its JSON line is logged and kept as $LAUNCH/<name>.json
  local name="$1" out; shift
  out="$("$@")" || { say "$out"; refuse "$name"; }
  printf '%s\n' "$out" > "$LAUNCH/$name.json"
  say "ok  $name $(printf '%s' "$out" | cut -c1-400)"
}
scan_written() { # how path...: rp3_scan or rp3_scan_token over those that exist; 1 on any hit
  local how="$1" p there=() out status=0
  shift
  for p in "$@"; do [ -e "$p" ] && there+=("$p"); done
  [ "${#there[@]}" -gt 0 ] || return 0
  out="$("$how" "${there[@]}")" || status=$?
  say "$how: $(printf '%s' "$out" | tr '\n' ';')"
  return "$status"
}

unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL CLAUDE_CODE_OAUTH_TOKEN
# The run account's token (token.sh): loaded for L10 and the arms into one unexported variable,
# given to each child alone through rp3_exec_with_token, never an argument, never printed; every
# file this launch wrote is scanned for it after L10 and after the block.
# shellcheck source=token.sh
source "$HERE/token.sh"
# shellcheck source=../../scripts/experiment/scan.sh
source "$CHECKOUT/scripts/experiment/scan.sh"
export DISABLE_AUTOUPDATER=1 PHYSGATE_CLAUDE_BIN="$BIN"
say "== R-PG-03 launch, block $BLOCK, attempt $N, $(date -u +%Y-%m-%dT%H:%M:%SZ), stop after: $STOP_AFTER"
[ "$STOP_AFTER" = run ] || say "CHECKS ONLY: master ref $MASTER_REF, records $RUNS; no review runs"
[ "$W5" = 80000000 ] || say "W5 RAISED by the owner at launch: $W5"
uv sync --frozen -q
(cd "$R_K_CHECKOUT" && uv sync --frozen -q)
CK=(--master-ref "$MASTER_REF")

# ---- L1: the host, the order, the owner ----
if [ "$TRIAL_HOST" = 1 ]; then say "TRIAL: the host check is skipped"; else check L1-host py "$HERE/checks.py" "${CK[@]}" host; fi
if [ "$TRIAL_HOST" = 1 ]; then say "TRIAL: the order and owner checks are skipped"; else
  check L1-order py "$HERE/checks.py" "${CK[@]}" order --block "$BLOCK"
  check L1-owner py "$HERE/checks.py" "${CK[@]}" owner --block "$BLOCK" --attempt "$N"
fi

# ---- L2: R and R_K ----
check L2-commits py "$HERE/checks.py" "${CK[@]}" commits --r "$CHECKOUT" --r-k "$R_K_CHECKOUT"
check L2-generalist uv run --frozen --project "$R_K_CHECKOUT" python -I "$R_K_CHECKOUT/experiments/R-PG-03/checks.py" "${CK[@]}" generalist

# ---- L3: the binary ----
check L3-binary py "$HERE/checks.py" "${CK[@]}" binary

# ---- L4: the parameters, the split, the plan ----
for f in params_a.json params_b.json; do
  py -c 'import sys; from pathlib import Path
from physgate.evaluation.inject.runner import InstrumentParams
InstrumentParams.model_validate_json(Path(sys.argv[1]).read_bytes())' "$HERE/$f" \
    || refuse "$f does not validate against the instrument's schema"
done
check L4-split py "$HERE/lanes.py" split
check L4-plan py "$HERE/lanes.py" plan "$SETS/$(CORPUS_OF "$BLOCK")" "$BLOCK"

# ---- L5: the corpus and the sheet ----
check L5-sets py "$HERE/checks.py" "${CK[@]}" sets --sets "$SETS" --block "$BLOCK"
SHEET_SHA="$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["sheet"])' "$LAUNCH/L5-sets.json")"
check L5-sheet py "$HERE/sheet_check.py" corpus "$SETS/$(CORPUS_OF "$BLOCK")" --sheet-sha256 "$SHEET_SHA" --into "$LAUNCH/sheet"

# ---- L6: R4, the twins' precondition again ----
check L6-r4 py "$CHECKOUT/experiments/R-PG-02/twins_fresh.py" "$SETS/$(CORPUS_OF "$BLOCK")" "$LAUNCH/r4" --any-count

# ---- L7: R3 ----
ROOTS=()
for arm in "${ARMS[@]}"; do ROOTS+=(--root "$HOME/review-scratch/rp3-$BLOCK-$N-$(lower "$arm")"); done
for arm in "${ARMS[@]}"; do
  [ ! -e "$HOME/review-scratch/rp3-$BLOCK-$N-$(lower "$arm")" ] || refuse "a review root of this attempt exists: an attempt is never resumed"
done
PLACES=(--place "$HOME/runs/rpg01b" --place "$HOME/runs/rpg02" --place "$HOME/runs/gr1" --place "$HOME/runs/gr2")
for p in "$RUNS"/blocks/* "$RUNS"/authoring "$RUNS"/reality "$HOME"/review-scratch/rp3-* "$HOME"/review-scratch/rpb-*; do
  [ -e "$p" ] && [ "$p" != "$LAUNCH" ] && PLACES+=(--place "$p")
done
check L7-r3 py "$HERE/checks.py" "${CK[@]}" r3 --checkout "$CHECKOUT" --r-k "$R_K_CHECKOUT" "${ROOTS[@]}" --sets "$SETS" "${PLACES[@]}"
uv run --frozen pytest -q -p no:cacheprovider -m integration \
  tests/integration/hooks/test_a_corpus_is_withheld_through_the_real_tool_path.py \
  tests/integration/hooks/test_a_reviewer_reads_only_its_allowance_through_the_real_tool_path.py \
  > "$LAUNCH/r3_allowance.log" 2>&1 || refuse "R3 read allowance on the pinned binary ($LAUNCH/r3_allowance.log)"
say "ok  L7 allowance $(tail -n 1 "$LAUNCH/r3_allowance.log")"

# ---- L8: the prompt identity check ----
code_at() { # sha -> a clean detached worktree of it under the records, synced
  local dir="$RUNS/code-$1"
  if [ ! -e "$dir" ]; then git worktree add -q --detach "$dir" "$1"; fi
  [ "$(git -C "$dir" rev-parse HEAD)" = "$(git rev-parse "$1^{commit}")" ] && [ -z "$(git -C "$dir" status --porcelain)" ] \
    || refuse "$dir is not $1, clean"
  (cd "$dir" && uv sync --frozen -q)
  echo "$dir"
}
KEPT="$(code_at 8c51f481742cb60dc971586724db718f69ff8508)"
NOISE="$(code_at eae78c09b73d587691d463f7d557929124146094)"
[ "$(git rev-parse 'gr2-r1-run-tree^{commit}')" = 8c51f481742cb60dc971586724db718f69ff8508 ] || refuse "the tag gr2-r1-run-tree is not 8c51f48"
IDENT="$LAUNCH/identity"
mkdir -p "$IDENT"
check L8-corpus py "$HERE/prompt_identity.py" corpus --into "$IDENT/corpus"
# Every packet is built at one fixed path (each build removes it when done), so two trees' packets
# can be compared byte for byte.
build_at() { # project arm out -> exit 5 if that tree's loader refuses the corpus
  uv run --frozen --project "$1" python -I "$HERE/prompt_identity.py" build --arm "$2" \
    --corpus "$CORPUS_USED" --root "$HOME/review-scratch/rp3-identity-$BLOCK-$N" --out "$IDENT/$2-$3.json"
}
CORPUS_USED="$IDENT/corpus"
status=0; build_at "$KEPT" A2 kept > "$IDENT/probe.out" || status=$?
if [ "$status" = 5 ]; then
  say "RECORDED: the kept round's loader refuses a field the complete sheet adds; both trees are fed the older form"
  rm -f "$IDENT/A2-kept.json"
  py "$HERE/prompt_identity.py" corpus --into "$IDENT/corpus-again" --older-sheet "$IDENT/corpus-older" > /dev/null
  CORPUS_USED="$IDENT/corpus-older"
  build_at "$KEPT" A2 kept > /dev/null || refuse "the kept round's tree cannot build its packets"
elif [ "$status" != 0 ]; then refuse "the kept round's tree cannot build its packets"; fi
build_at "$CHECKOUT" A2 run > /dev/null || refuse "R cannot build A2's packets"
for arm in A1 B; do
  build_at "$NOISE" "$arm" noise > /dev/null || refuse "eae78c0 cannot build $arm's packets"
  build_at "$R_K_CHECKOUT" "$arm" run > /dev/null || refuse "R_K cannot build $arm's packets"
done
for arm in A2 A1 B; do
  old=noise; [ "$arm" = A2 ] && old=kept
  check "L8-$arm" py "$HERE/prompt_identity.py" compare --new "$IDENT/$arm-run.json" --old "$IDENT/$arm-$old.json"
done

FIRST="$(python3 -I -c 'import json,sys
try: d = json.load(open(sys.argv[1]))
except FileNotFoundError: d = {}
print(0 if any(a.get("valid") is not None for a in d.get("attempts", [])) else 1)' "$RUNS/blocks.json")"

# ---- L9: the false-finding control's keys, counted again (first block) ----
if [ "$FIRST" = 1 ]; then
  [ -n "${RP3_PRACTICE_ROUND1:-}" ] && [ -n "${RP3_PRACTICE_REPEATK:-}" ] \
    || refuse "name the practice records for the false-finding control's count (RP3_PRACTICE_ROUND1, RP3_PRACTICE_REPEATK)"
  check L9-ff py "$HERE/reality.py" ff-count --practice "round-1=$RP3_PRACTICE_ROUND1" --practice "repeat-K=$RP3_PRACTICE_REPEATK"
fi

# ---- L10: the whole-read smoke (first block), on the run account ----
SMOKE_ROOT="$HOME/review-scratch/rp3-smoke-$BLOCK-$N"
if [ "$STOP_AFTER" = run ] && [ "$FIRST" = 1 ]; then
  rp3_load_token "$ENV_FILE" 2>> "$LOG" || refuse "the run account's token (see the line above)"
  say "ok  token loaded: one line of the token's shape"
  SMOKE_STARTED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  set +e
  ( rp3_exec_with_token uv run --frozen python -I "$HERE/streams.py" smoke \
      --sheet "$SETS/$(CORPUS_OF "$BLOCK")/sources.json" --out "$LAUNCH/smoke" --root "$SMOKE_ROOT" ) > "$LAUNCH/L10.json"
  CODE=$?
  set -e
  say "L10 $(cat "$LAUNCH/L10.json")"
  py "$HERE/ledger.py" session --kind smoke --label "smoke before block $BLOCK" --root "$SMOKE_ROOT" \
    --account "$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["account_label"])' "$LAUNCH/L1-owner.json")" \
    --window "$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1])).get("window_confirmed_utc", "?"))' "$LAUNCH/L1-owner.json")" \
    --started "$SMOKE_STARTED" --ended "$(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "$LOG"
  { scan_written rp3_scan "$SMOKE_ROOT" "$LAUNCH/smoke" && scan_written rp3_scan_token "$LAUNCH"; } \
    || { rp3_drop_token; refuse "the token's scan found a hit after L10"; }
  [ "$CODE" = 0 ] || { rp3_drop_token; refuse "the smoke did not pass (exit $CODE): the first block does not start"; }
fi

# ---- L11: the 5-hour projection ----
check L11 py "$HERE/ledger.py" project --block "$BLOCK" --w5 "$W5"
[ "$STOP_AFTER" = checks ] && { say "stopped after the checks, as asked"; exit 0; }

# ---- the block: the watcher, then the three arms at once ----
[ -n "${RP3_TOKEN:-}" ] || { rp3_load_token "$ENV_FILE" 2>> "$LOG" || refuse "the run account's token (see the line above)"; }
INSTALL_R="$LAUNCH/install-r"; INSTALL_K="$LAUNCH/install-r-k"
uv run --frozen python -I -c 'import sys; from pathlib import Path
from physgate.orchestrator import cli
from physgate.orchestrator.install import prepare_install
prepare_install(Path(sys.argv[1]), cli._project_root())' "$INSTALL_R" > "$LAUNCH/install-r.log" 2>&1 || refuse "R's installation did not build"
(cd "$R_K_CHECKOUT" && uv run --frozen python -I -c 'import sys; from pathlib import Path
from physgate.orchestrator import cli
from physgate.orchestrator.install import prepare_install
prepare_install(Path(sys.argv[1]), cli._project_root())' "$INSTALL_K") > "$LAUNCH/install-r-k.log" 2>&1 || refuse "R_K's installation did not build"
install_of() { case "$1" in A2) echo "$INSTALL_R" ;; *) echo "$INSTALL_K" ;; esac; }
run_of() { echo "$LAUNCH/$(lower "$1")"; }
scratch_of() { echo "$HOME/review-scratch/rp3-$BLOCK-$N-$(lower "$1")"; }
python3 -I -c 'import json,sys; a = sys.argv[1:]
print(json.dumps({"runs": dict(zip(a[0::3], a[1::3])), "scratch": dict(zip(a[0::3], a[2::3]))}))' \
  A2 "$(run_of A2)" "$(scratch_of A2)" A1 "$(run_of A1)" "$(scratch_of A1)" B "$(run_of B)" "$(scratch_of B)" > "$LAUNCH/runs.json"
check start py "$HERE/checks.py" "${CK[@]}" start --block "$BLOCK" --attempt "$N" --runs "$LAUNCH/runs.json"
BLOCK_STARTED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
PIDS=(); STARTED=()
start_one() {
  local i="$1" arm="${ARMS[$1]}" co
  co="$(checkout_of "$arm")"
  # shellcheck disable=SC2046 # the mode is empty or one flag
  rp3_exec_with_token setsid "$co/.venv/bin/physgate" inject \
    --corpus "$SETS/$(CORPUS_OF "$BLOCK")" \
    --run-dir "$(run_of "$arm")" \
    --scratch "$(scratch_of "$arm")" \
    --run-id "rp3-$BLOCK-$N-$(lower "$arm")" \
    --seed "$(SEED_OF "$BLOCK")" \
    --params "$(params_of "$arm")" \
    --install "$(install_of "$arm")" \
    --lanes "$(lanes_of "$arm")" \
    --per-class "$(PER_CLASS_OF "$BLOCK")" \
    --review-clean-twins $(mode_of "$arm") \
    > "$LAUNCH/$(lower "$arm").out" 2> "$LAUNCH/$(lower "$arm").err" < /dev/null &
  PIDS[i]=$!
  STARTED[i]="$(date -u +%s)"
  say "started $arm, pid ${PIDS[$i]}, $(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
stop_all() { local pid; for pid in "${PIDS[@]}"; do kill -TERM -- "-$pid" 2>/dev/null || true; done; }
say "== block $BLOCK starts $(date -u +%Y-%m-%dT%H:%M:%SZ): $LAUNCH"
# All three or none: there is no way to start one arm alone.
start_one 0
start_one 1
start_one 2
"$HERE/watch_limit.sh" "$LAUNCH/watcher.log" block \
  "${PIDS[0]}" "$(run_of A2)" "$(scratch_of A2)" -- "${PIDS[1]}" "$(run_of A1)" "$(scratch_of A1)" -- \
  "${PIDS[2]}" "$(run_of B)" "$(scratch_of B)" &
WATCHER=$!
if [ $((STARTED[2] - STARTED[0])) -gt 60 ]; then
  stop_all; echo "the arms did not start within one minute" > "$LAUNCH/first_minute.txt"
fi
sleep 60
for i in 0 1 2; do
  if ! kill -0 "${PIDS[$i]}" 2>/dev/null; then
    stop_all
    echo "${ARMS[$i]} stopped within its first minute" >> "$LAUNCH/first_minute.txt"
    say "VOID: ${ARMS[$i]} stopped within its first minute; the others are stopped (§5 R8)"
  fi
done
declare -A EXITS=()
for i in 0 1 2; do
  set +e; wait "${PIDS[$i]}"; EXITS[${ARMS[$i]}]=$?; set -e
  say "== ${ARMS[$i]} ended $(date -u +%Y-%m-%dT%H:%M:%SZ), exit ${EXITS[${ARMS[$i]}]}"
done
wait "$WATCHER" || true
python3 -I -c 'import json,sys; a = sys.argv[1:]; print(json.dumps({a[k]: int(a[k + 1]) for k in range(0, len(a), 2)}))' \
  A2 "${EXITS[A2]}" A1 "${EXITS[A1]}" B "${EXITS[B]}" > "$LAUNCH/exits.json"
BLOCK_ENDED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# ---- the attempt's end: its checks, its ledger line, the logins, the token's scan ----
AFTER_OK=1
py "$HERE/checks.py" "${CK[@]}" after --block "$BLOCK" --attempt "$N" --launch "$LAUNCH" \
  --sheet "$SETS/$(CORPUS_OF "$BLOCK")/sources.json" --sets "$SETS" | tee -a "$LOG" || AFTER_OK=0
VOID="$(python3 -I -c 'import json,sys; d = json.load(open(sys.argv[1])); print("; ".join(d["void_causes"]))' "$LAUNCH/after.json" 2>/dev/null || echo "the end check did not complete")"
LEDGER_OK=1
py "$HERE/ledger.py" block --block "$BLOCK" --attempt "$N" \
  --scratch "$(scratch_of A2)" --scratch "$(scratch_of A1)" --scratch "$(scratch_of B)" \
  --account "$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["account_label"])' "$LAUNCH/L1-owner.json")" \
  --window "$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1])).get("window_confirmed_utc", "?"))' "$LAUNCH/L1-owner.json")" \
  --started "$BLOCK_STARTED" --ended "$BLOCK_ENDED" ${VOID:+--void "$VOID"} | tee -a "$LOG" || LEDGER_OK=0
CREDENTIALS_OK=1; py "$HERE/checks.py" "${CK[@]}" credentials | tee -a "$LOG" || CREDENTIALS_OK=0
WRITTEN=("$LAUNCH"/*.out "$LAUNCH"/*.err "$LAUNCH/a2" "$LAUNCH/a1" "$LAUNCH/b" "$LAUNCH/install-r" "$LAUNCH/install-r-k" \
  "$(scratch_of A2)" "$(scratch_of A1)" "$(scratch_of B)" "$RUNS/blocks.json" "$RUNS/ledger.jsonl")
SCAN_OK=1
{ scan_written rp3_scan "${WRITTEN[@]}" && scan_written rp3_scan_token "$LAUNCH"; } || SCAN_OK=0
rp3_drop_token
[ "$CREDENTIALS_OK" = 1 ] || refuse "a login file of the block's sessions remains, or its removal is not confirmed"
[ "$SCAN_OK" = 1 ] || refuse "the token's scan found a hit in what the block wrote"
[ "$LEDGER_OK" = 1 ] || refuse "the ledger line"
[ "$AFTER_OK" = 1 ] || refuse "the attempt is void ($VOID): it is re-attempted whole, never resumed (§11)"
say "== done $(date -u +%Y-%m-%dT%H:%M:%SZ): block $BLOCK attempt $N is valid"
