#!/usr/bin/env bash
# The two configurations' pins are read by name through picked(), which shellcheck cannot see.
# shellcheck disable=SC2034
#
# R-PG-02: the pre-flight refusals, then the three runs together. Every check below holds the
# checkout to CRITERIA.md §3; any mismatch stops the script before a review runs, and nothing
# is resumed.
#
#   experiments/R-PG-02/launch.sh [--preflight-only | --through-r4]
#
# Run it on the ARM virtual machine (Linux, the pinned linux-arm64 binary), from a clean clone of
# the run's commit, detached so a closed connection does not end it, naming the practice set and
# its runs for R3:
#
#   R_PG_02_PRACTICE=<practice set dir> R_PG_02_PRACTICE_RUNS=<its runs dir> \
#     setsid nohup experiments/R-PG-02/launch.sh > ~/runs/rpg02/launch-1.out 2>&1 < /dev/null &
#
# Stages, in order:
#   1. the machine, and every place this attempt writes is new (a run is never resumed);
#   2. the pick (K or F, CRITERIA.md §3) selects that configuration's pins; the run's commit:
#      HEAD is on origin/master, is the last commit that changed this directory (the last of
#      the pick and the manifest fills), descends from the picked configuration's commit (the
#      tuning-freeze commit), and the tree is clean;
#   3. the pinned hashes: gate, both bounds tables, spelling, catalogue, reviewers, the picked
#      configuration's rubrics tree and four digests, instrument tree and account paragraphs,
#      both sets' manifests, the binary and its version, the parameters files and the lane split;
#   4. each run's lane plan, as counts and a digest;
#   5. R3: the reachability scan over the three sets, the practice copies and runs and the
#      three review roots, and the reviewer's read allowance on the pinned binary;
#   6. the reviewer requests' defaults, by the instrument pilot's dry run (no model call);
#   7. R4: the fresh twins' precondition, and the old twins' count and records digest;
#   8. the three runs, started together: arm A and arm B on the fresh set, arm A on the old set.
#
# --preflight-only stops after stage 5; --through-r4 stops after stage 7. Neither reads the token.
# Only with one of them, R_PG_02_UNFROZEN=1 skips stage 2's commit checks, so the script can be
# tried before the freeze, and R_PG_02_PICK=K|F may then name the configuration to try; the log
# says so, and the run itself never skips them. There is no
# way to start one run alone. A void attempt is never resumed: set R_PG_02_ATTEMPT to a new
# number and start again.

set -euo pipefail

STOP_AFTER=run
case "${1:-}" in
  "") ;;
  --preflight-only) STOP_AFTER=preflight ;;
  --through-r4) STOP_AFTER=r4 ;;
  *) echo "usage: $0 [--preflight-only | --through-r4]" >&2; exit 2 ;;
esac

# ---- what CRITERIA.md §3 and R4 pin ----
# The pick between the two reviewer configurations (CRITERIA.md §3), filled by the pick commit:
# K or F, read from the last practice round's tally by the stop rule, never chosen.
PICK="[FILL AT PICK]"
GATE_TREE=1e169aac5679d743d4b0585090a45bcd06ea1a63
BOUNDS_ELECTRICAL_BLOB=3bbdc33b7e4ab1df2b2a32d48003fbffa876ebc0
BOUNDS_ELECTRICAL_SHA256=a5c3be61b6898b1a2408b8957c71fa3008c374f3de1c8fa56423c559c9019663
BOUNDS_CROSS_BLOB=b68fd58f31a9469124d4accc26a8a9c6f1dde7cf
BOUNDS_CROSS_SHA256=ddb96fc7582241392eb5db407f336c8d8a37c313272c400522ec11b4218fefed
SPELLING_BLOB=eaa4ce697092d27545a19c87c6d92fc6f1e966fc
CATALOGUE_SHA256=9bf73a7dfd74f49fc0b094a45df9564fdff5de129e170d06ce8d54851a841c88
REVIEWERS_TREE=e072e6a908535b5c42e78a30aa1ff0b95cb9ef3a
# K, kept: the last practice round's rubrics promoted, with the account's fixed paragraphs.
K_COMMIT=48929eb2f1ba0d770b02914e4a2b29a62a27e486
K_INJECT_TREE=93e5c3275997eea4633e5c141fbf80a6f271a029
K_ACCOUNT_SHA256=8580efd05af6fd2d304810950f00bb2c3d462302dddfd00b1d12373e340ab838
K_RUBRICS_TREE=b5d5a31e8073ec99d356f41b4086885607c2a4aa
K_RUBRIC_CONTROL=08a5cfbc1b6729843bd5f6d8cad5c3596faaeecc596fb472230905815a2677d6
K_RUBRIC_ELECTRICAL=5ca8c13584ac896abda9825d52a0a3b8177866024e68249ad75375c59086b445
K_RUBRIC_FIRMWARE=614ad78c9ebceba6903fba31267801e970162d80fbf10df0713064c99377c25e
K_RUBRIC_MECHANICAL=ee68896b4adce53b1e66330d1c8072e5afbac66a547d077abd4d0325ef8dadf8
# F, fallback: the first practice run's rubrics and template, unchanged; no account paragraphs.
F_COMMIT=82cbf3b6b77de5de5d6b4d1a5a3117b7656b1480
F_INJECT_TREE=375e9e882bc452b75f7395e71a13c8614fee1ba2
F_ACCOUNT_SHA256=none
F_RUBRICS_TREE=dd203340de8cee2f42878bb09ee72e64dfe1465b
F_RUBRIC_CONTROL=18be8569a3743d6f9f5ff554ac6fd7e7c86b082ffaad4c08d0a40a00bac111f5
F_RUBRIC_ELECTRICAL=a1b78302cf116ce471bf24a484de24a1e98e8679256e41d5f36b3dd4f48219b3
F_RUBRIC_FIRMWARE=e265ef4733443d1af8a8152a8831fa97f999c3fcae0acc8f12f48fe1faed5f8a
F_RUBRIC_MECHANICAL=3ca83fe1099481ff4c32681b7e63a594e907dd01bcd6a56a8160ed0a8e0783fa
OLD_TREE=77782679f15eae4301e86516541b4a3c5c6613b0
OLD_MANIFEST_SHA256=41553301d5b036f84df289ee6d8c87ecce4504d5a09969e05291e23c9ebc026a
FRESH_MANIFEST_SHA256="[FILL AT FREEZE]"
OLD_TWINS_COUNT=40
OLD_TWINS_RECORDS_SHA256=4a23d22dd255d41afa9934aba77caeb1ee8a819def1428741a5e41f1f8598d11
BINARY_VERSION=2.1.301
BINARY_SHA256=1e119036a802d359ba5f9886428e031586e8796f7a858d5a8ee179ac7b8604f0
FRESH_SEED=13
OLD_SEED=7

# ---- where things go; no review root may name the harness or sit in a checkout ----
CHECKOUT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HERE="$CHECKOUT/experiments/R-PG-02"
OLD="$CHECKOUT/corpora/injected-errors/v1"
FRESH="${R_PG_02_FRESH:-$HOME/runs/rpg02/sets/fresh-v1}"
# The practice set and its runs live outside the repository; R3 needs both named, never guessed.
PRACTICE="${R_PG_02_PRACTICE:-}"
PRACTICE_RUNS="${R_PG_02_PRACTICE_RUNS:-}"
BIN="${PHYSGATE_CLAUDE_BIN:-$HOME/pinned/claude-2.1.301}"
ENV_FILE="${R_PG_02_ENV_FILE:-$HOME/.config/physgate-run.env}"
N="${R_PG_02_ATTEMPT:-1}"
RUN_ROOT="${R_PG_02_RUN_ROOT:-$HOME/runs/rpg02}"
ATTEMPT="$RUN_ROOT/attempt-$N"
LOGS="$ATTEMPT/logs"
INSTALL="$ATTEMPT/install"
DRY="$ATTEMPT/dry"
SCRATCH_BASE="${R_PG_02_REVIEW_BASE:-$HOME/review-scratch}"
# The three runs, in the order they start; each one's set, seed, parameters, root and mode.
RUNS=(a-fresh b-fresh a-old)
set_of() { case "$1" in a-old) echo "$OLD" ;; *) echo "$FRESH" ;; esac; }
seed_of() { case "$1" in a-old) echo "$OLD_SEED" ;; *) echo "$FRESH_SEED" ;; esac; }
params_of() { case "$1" in a-old) echo "$HERE/params_old.json" ;; *) echo "$HERE/params_fresh.json" ;; esac; }
root_of() { case "$1" in a-fresh) echo "$SCRATCH_BASE/rp2-$N-1" ;; b-fresh) echo "$SCRATCH_BASE/rp2-$N-2" ;; a-old) echo "$SCRATCH_BASE/rp2-$N-3" ;; esac; }
mode_of() { case "$1" in b-fresh) echo "--generalist" ;; *) echo "" ;; esac; }

say() { echo "$*" | tee -a "${LOG:-/dev/null}" >&2; }
refuse() { say "REFUSED: $*"; exit 1; }

# ---- 1. the machine, and every place new ----
[ "$(uname -s)" = Linux ] || refuse "the run machine is the Linux ARM virtual machine (CRITERIA.md §3)"
[ -n "$PRACTICE" ] && [ -n "$PRACTICE_RUNS" ] \
  || refuse "name the practice set and its runs (R_PG_02_PRACTICE, R_PG_02_PRACTICE_RUNS) for R3"
for p in "$ATTEMPT" "$(root_of a-fresh)" "$(root_of b-fresh)" "$(root_of a-old)"; do
  [ ! -e "$p" ] || refuse "$p already exists: an attempt is never resumed (set R_PG_02_ATTEMPT)"
done
mkdir -p "$LOGS"
LOG="$LOGS/launch.log"
equal() { [ "$2" = "$3" ] || refuse "$1 is $2, not $3"; say "ok  $1 $3"; }
sha() { sha256sum "$1" | cut -d' ' -f1; }
py() { "$CHECKOUT/.venv/bin/python" -I "$@"; }
lanes_of() { py -c 'import json,sys; print(json.load(open(sys.argv[1]))["lanes"])' "$(params_of "$1")"; }
# shellcheck source=../../scripts/experiment/scan.sh
source "$CHECKOUT/scripts/experiment/scan.sh"
say "== R-PG-02 launch, attempt $N, $(date -u +%Y-%m-%dT%H:%M:%SZ), stop after: $STOP_AFTER"
cd "$CHECKOUT"

# ---- 2. the pick, and the run's commit ----
# Only a trial before the freeze may name the configuration to try; the run reads the pick.
if [ "${R_PG_02_UNFROZEN:-}" = 1 ] && [ "$STOP_AFTER" != run ] && [ -n "${R_PG_02_PICK:-}" ]; then
  PICK="$R_PG_02_PICK"
  say "TRIAL: configuration $PICK named by R_PG_02_PICK, not by the pick commit"
fi
case "$PICK" in
  K | F) ;;
  *) refuse "the pick is not filled (CRITERIA.md §3): K or F, read from the round's tally" ;;
esac
picked() { local name="${PICK}_$1"; echo "${!name}"; }
TOOLING_COMMIT="$(picked COMMIT)"
INJECT_TREE="$(picked INJECT_TREE)"
ACCOUNT_SHA256="$(picked ACCOUNT_SHA256)"
RUBRICS_TREE="$(picked RUBRICS_TREE)"
RUBRIC_CONTROL="$(picked RUBRIC_CONTROL)"
RUBRIC_ELECTRICAL="$(picked RUBRIC_ELECTRICAL)"
RUBRIC_FIRMWARE="$(picked RUBRIC_FIRMWARE)"
RUBRIC_MECHANICAL="$(picked RUBRIC_MECHANICAL)"
for v in "$TOOLING_COMMIT" "$RUBRICS_TREE"; do
  [[ "$v" =~ ^[0-9a-f]{40}$ ]] || refuse "configuration $PICK is not filled in (CRITERIA.md §3)"
done
say "ok  configuration $PICK, tuning-freeze commit $TOOLING_COMMIT"
git fetch -q origin
HEAD_SHA="$(git rev-parse HEAD)"
if [ "${R_PG_02_UNFROZEN:-}" = 1 ] && [ "$STOP_AFTER" != run ]; then
  say "SKIPPED: the run's-commit checks (R_PG_02_UNFROZEN=1, a trial before the freeze)"
else
  equal "HEAD, the commit that last changed experiments/R-PG-02" "$HEAD_SHA" \
    "$(git log -1 --format=%H -- experiments/R-PG-02)"
  git merge-base --is-ancestor HEAD origin/master || refuse "HEAD $HEAD_SHA is not on origin/master"
  git merge-base --is-ancestor "$TOOLING_COMMIT" HEAD \
    || refuse "HEAD does not descend from the tuning-freeze commit $TOOLING_COMMIT"
  [ -z "$(git status --porcelain)" ] || refuse "the checkout is not clean"
  say "ok  run commit $HEAD_SHA, clean, on origin/master, after the tuning freeze $TOOLING_COMMIT"
fi

# ---- 3. the pinned hashes ----
equal "gate tree" "$(git rev-parse HEAD:src/physgate/gate)" "$GATE_TREE"
equal "electrical bounds blob" "$(git rev-parse HEAD:knowledge/electrical/bounds.toml)" "$BOUNDS_ELECTRICAL_BLOB"
equal "electrical bounds sha256" "$(sha knowledge/electrical/bounds.toml)" "$BOUNDS_ELECTRICAL_SHA256"
equal "cross bounds blob" "$(git rev-parse HEAD:knowledge/cross/bounds.toml)" "$BOUNDS_CROSS_BLOB"
equal "cross bounds sha256" "$(sha knowledge/cross/bounds.toml)" "$BOUNDS_CROSS_SHA256"
equal "spelling blob" "$(git rev-parse HEAD:src/physgate/unit_spelling.py)" "$SPELLING_BLOB"
equal "reviewers tree" "$(git rev-parse HEAD:src/physgate/reviewers)" "$REVIEWERS_TREE"
equal "instrument tree" "$(git rev-parse HEAD:src/physgate/evaluation/inject)" "$INJECT_TREE"
equal "rubrics tree" "$(git rev-parse HEAD:knowledge/reviewers)" "$RUBRICS_TREE"
equal "control rubric" "$(sha knowledge/reviewers/control/rubric.md)" "$RUBRIC_CONTROL"
equal "electrical rubric" "$(sha knowledge/reviewers/electrical/rubric.md)" "$RUBRIC_ELECTRICAL"
equal "firmware rubric" "$(sha knowledge/reviewers/firmware/rubric.md)" "$RUBRIC_FIRMWARE"
equal "mechanical rubric" "$(sha knowledge/reviewers/mechanical/rubric.md)" "$RUBRIC_MECHANICAL"
equal "old set tree" "$(git rev-parse HEAD:corpora/injected-errors/v1)" "$OLD_TREE"
equal "old set manifest sha256" "$(sha "$OLD/MANIFEST.json")" "$OLD_MANIFEST_SHA256"
[ -f "$FRESH/MANIFEST.json" ] || refuse "no fresh set at $FRESH"
equal "fresh set manifest sha256" "$(sha "$FRESH/MANIFEST.json")" "$FRESH_MANIFEST_SHA256"
uv sync --frozen -q
equal "catalogue digest" \
  "$(py -c 'from physgate.gate.catalogue import catalogue_digest; print(catalogue_digest())')" \
  "$CATALOGUE_SHA256"
equal "account paragraphs sha256" \
  "$(py -c 'import physgate.evaluation.inject.materialise as m; print(getattr(m, "ACCOUNT_SHA256", "none"))')" \
  "$ACCOUNT_SHA256"
[ -x "$BIN" ] || refuse "no binary at $BIN"
equal "binary sha256" "$(sha "$BIN")" "$BINARY_SHA256"
equal "binary version" "$("$BIN" --version | cut -d' ' -f1)" "$BINARY_VERSION"
for f in params_fresh.json params_old.json; do
  py -c 'import sys; from pathlib import Path
from physgate.evaluation.inject.runner import InstrumentParams
InstrumentParams.model_validate_json(Path(sys.argv[1]).read_bytes())' "$HERE/$f" \
    || refuse "$f does not validate against the instrument's schema"
  say "ok  $f $(sha "$HERE/$f")"
done
py "$HERE/lanes.py" split "$HERE/params_fresh.json" "$HERE/params_old.json" | tee -a "$LOG" \
  || refuse "the lane split is not the rule's (lanes.py)"
export PHYSGATE_CLAUDE_BIN="$BIN"

# ---- 4. each run's lane plan ----
for run in "${RUNS[@]}"; do
  plan="$(py "$HERE/lanes.py" plan "$(set_of "$run")" "$(seed_of "$run")" "$(lanes_of "$run")")" \
    || refuse "the lane plan of $run: $plan"
  say "plan $run: $plan"
done

# ---- 5. R3: nothing reachable ----
mkdir -p "$SCRATCH_BASE"
py "$HERE/r3_scan.py" --checkout "$CHECKOUT" \
  --root "$(root_of a-fresh)" --root "$(root_of b-fresh)" --root "$(root_of a-old)" \
  --set "old=$OLD" --set "fresh=$FRESH" --set "practice=$PRACTICE" \
  --place "$PRACTICE_RUNS" --place "$ATTEMPT" | tee -a "$LOG" || refuse "R3 scan"
uv run --frozen pytest -q -p no:cacheprovider -m integration \
  tests/integration/hooks/test_a_corpus_is_withheld_through_the_real_tool_path.py \
  tests/integration/hooks/test_a_reviewer_reads_only_its_allowance_through_the_real_tool_path.py \
  > "$LOGS/r3_allowance.log" 2>&1 || refuse "R3 read allowance on the pinned binary ($LOGS/r3_allowance.log)"
say "ok  $(tail -n 1 "$LOGS/r3_allowance.log")"
uv run --frozen pytest -q -p no:cacheprovider \
  tests/unit/reviewers/test_what_a_reviewer_is_shown_does_not_say_it_is_evaluated.py \
  > "$LOGS/r3_shown.log" 2>&1 || refuse "R3 what a reviewer is shown ($LOGS/r3_shown.log)"
say "ok  $(tail -n 1 "$LOGS/r3_shown.log")"
say "ok  R3"
[ "$STOP_AFTER" = preflight ] && { say "stopped after the pre-flight, as asked"; exit 0; }

# ---- 6. the reviewer requests' defaults: the dry run, no model call ----
uv run --frozen python tests/integration/orchestrator/real_instrument_pilot.py \
  --dry-run --out "$DRY" > "$LOGS/dry-run.out" 2>&1 || refuse "the dry run exited non-zero"
py - "$DRY/result.json" "$HEAD_SHA" "$BINARY_VERSION" "$BINARY_SHA256" "$LOGS/request_defaults.json" <<'EOF' | tee -a "$LOG" || refuse "the dry run"
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
say "ok  request defaults recorded in $LOGS/request_defaults.json"

# ---- 7. R4: the fresh twins' precondition, and the old twins once more ----
py "$HERE/twins_fresh.py" "$FRESH" "$ATTEMPT/twins-fresh" | tee -a "$LOG" \
  || refuse "R4: the fresh twins do not hold their precondition"
py "$HERE/twins_old.py" "$OLD" "$ATTEMPT/twins-old" "$OLD_TWINS_COUNT" "$OLD_TWINS_RECORDS_SHA256" \
  | tee -a "$LOG" || refuse "R4: the old twins do not reproduce the tuning freeze's count and records"
say "ok  R4"
[ "$STOP_AFTER" = r4 ] && { say "stopped after R4, as asked"; exit 0; }

# ---- 8. the three runs, together ----
[ -f "$ENV_FILE" ] || refuse "no env file at $ENV_FILE"
CLAUDE_CODE_OAUTH_TOKEN="$(sed -n 's/^\(export \)\{0,1\}CLAUDE_CODE_OAUTH_TOKEN=//p' "$ENV_FILE" | head -n 1 | tr -d "\"'")"
[ -n "$CLAUDE_CODE_OAUTH_TOKEN" ] || refuse "no token in the env file"
say "ok  token found: yes"
export CLAUDE_CODE_OAUTH_TOKEN
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL
export DISABLE_AUTOUPDATER=1
# One installation for the three runs, built before any starts, so none builds it at once.
py -c 'import sys; from pathlib import Path
from physgate.orchestrator import cli
from physgate.orchestrator.install import prepare_install
prepare_install(Path(sys.argv[1]), cli._project_root())' "$INSTALL" > "$LOGS/install.log" 2>&1 \
  || refuse "the hooks' installation did not build ($LOGS/install.log)"

PIDS=()
STARTED=()
start_one() {
  local i="$1" run="${RUNS[$1]}"
  # shellcheck disable=SC2046 # the mode is empty or one flag
  setsid "$CHECKOUT/.venv/bin/physgate" inject \
    --corpus "$(set_of "$run")" \
    --run-dir "$ATTEMPT/$run" \
    --scratch "$(root_of "$run")" \
    --run-id "rp2-$N-$run" \
    --seed "$(seed_of "$run")" \
    --params "$(params_of "$run")" \
    --install "$INSTALL" \
    --lanes "$(lanes_of "$run")" \
    --review-clean-twins $(mode_of "$run") \
    > "$LOGS/$run.out" 2> "$LOGS/$run.err" < /dev/null &
  PIDS[i]=$!
  STARTED[i]="$(date -u +%s)"
  say "started $run, pid ${PIDS[$i]}, $(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
stop_all() {
  local pid
  for pid in "${PIDS[@]}"; do kill -TERM -- "-$pid" 2>/dev/null || true; done
}
say "== the three runs start $(date -u +%Y-%m-%dT%H:%M:%SZ): $ATTEMPT"
# All three or none: there is no way to start one alone.
start_one 0
start_one 1
start_one 2
[ $((STARTED[2] - STARTED[0])) -le 60 ] || { stop_all; refuse "the three runs did not start within one minute"; }
# A run that stops in its first minute voids the attempt: the others are stopped too.
sleep 60
for i in 0 1 2; do
  if ! kill -0 "${PIDS[$i]}" 2>/dev/null; then
    stop_all
    refuse "${RUNS[$i]} stopped within its first minute ($LOGS/${RUNS[$i]}.err); one run alone is not this experiment, and the attempt is void"
  fi
done
say "ok  the three runs are running"
CODES=()
for i in 0 1 2; do
  set +e
  wait "${PIDS[$i]}"
  CODES[i]=$?
  set -e
  say "== ${RUNS[$i]} ended $(date -u +%Y-%m-%dT%H:%M:%SZ), exit ${CODES[$i]}; last line: $(tail -n 1 "$LOGS/${RUNS[$i]}.out" 2>/dev/null)"
done
# The token never belongs in what the runs wrote: counts only, never a match.
for pattern in "$CLAUDE_CODE_OAUTH_TOKEN" sk-ant- oat01; do
  hits="$(count_files_with "$pattern" "$ATTEMPT")"
  [ "$pattern" = "$CLAUDE_CODE_OAUTH_TOKEN" ] && label=token || label="$pattern"
  say "scan $label: $hits files"
done
unset CLAUDE_CODE_OAUTH_TOKEN
say "== the experiment's runs ended $(date -u +%Y-%m-%dT%H:%M:%SZ)"
# Each run exits 1 when a review came to no pass or fail, which is a counted outcome; 2 is a refusal.
for code in "${CODES[@]}"; do [ "$code" -le 1 ] || exit "$code"; done
exit 0
