#!/usr/bin/env bash
#
# R-PG-01: the pre-flight refusals, then the run. Every check below holds the checkout to
# CRITERIA.md §2; any mismatch stops the script before a review runs, and nothing is resumed.
#
#   experiments/R-PG-01/launch.sh [--preflight-only | --through-r4]
#
# Run it from a clean checkout of the run's commit, on the macOS laptop, under nohup so a closed
# terminal does not end it; it keeps the machine awake itself:
#
#   nohup experiments/R-PG-01/launch.sh > ~/rpg01-runs/launch-1.out 2>&1 &
#
# Stages, in order:
#   1. the run's commit: HEAD is on origin/master and is the last commit that changed this
#      directory (the commit that froze CRITERIA.md); the tree is clean;
#   2. the pinned hashes: gate, bounds, spelling, instrument, reviewers, rubrics and the four
#      rubric digests, the catalogue, the corpus tree and manifest, the binary and its version,
#      and the parameters file against the instrument's schema;
#   3. R3: the reachability scan, and the reviewer's read allowance on the pinned binary;
#   4. the reviewer requests' defaults, measured by the instrument pilot's dry run (scripted
#      endpoint, a dummy token, no model call);
#   5. R4: the 40 clean twins alone through the gate, 40/40 with the pinned records sha256;
#   6. the run: `physgate inject` with §2's parameters, seed 7, the twins reviewed.
#
# --preflight-only stops after stage 3; --through-r4 stops after stage 5. Neither reads the token.
# Only with one of them, R_PG_01_UNFROZEN=1 skips stage 1's commit checks, so the script can be
# tried on its branch before the freeze; the log says so, and the run itself never skips them.
# A killed run is never resumed: set R_PG_01_ATTEMPT to a new number and start again.

set -euo pipefail

STOP_AFTER=run
case "${1:-}" in
  "") ;;
  --preflight-only) STOP_AFTER=preflight ;;
  --through-r4) STOP_AFTER=r4 ;;
  *) echo "usage: $0 [--preflight-only | --through-r4]" >&2; exit 2 ;;
esac

# ---- what CRITERIA.md §2 pins ----
GATE_TREE=29e7c8061e4f5e54b815afd41bf98f9e6455a7c3
BOUNDS_BLOB=cdeb9736d93362120f8f08f0244ab449b7bd5f90
BOUNDS_SHA256=b75d14d541243108d02f0afc1414a8cd61493f694325c9c2e4f09e30cfa27071
SPELLING_BLOB=eaa4ce697092d27545a19c87c6d92fc6f1e966fc
CATALOGUE_SHA256=171b054b61f703fee2aaf750b4ff107754bbf0726882e18531cb92db0028d69f
INJECT_TREE=af7ead4ac5579c86b6e19ffe7a02991ac9872eca
REVIEWERS_TREE=7df979eecb5b9acba572c5687747ea33586a87e1
RUBRICS_TREE=dd203340de8cee2f42878bb09ee72e64dfe1465b
RUBRIC_CONTROL=18be8569a3743d6f9f5ff554ac6fd7e7c86b082ffaad4c08d0a40a00bac111f5
RUBRIC_ELECTRICAL=a1b78302cf116ce471bf24a484de24a1e98e8679256e41d5f36b3dd4f48219b3
RUBRIC_FIRMWARE=e265ef4733443d1af8a8152a8831fa97f999c3fcae0acc8f12f48fe1faed5f8a
RUBRIC_MECHANICAL=3ca83fe1099481ff4c32681b7e63a594e907dd01bcd6a56a8160ed0a8e0783fa
CORPUS_TREE=77782679f15eae4301e86516541b4a3c5c6613b0
MANIFEST_SHA256=41553301d5b036f84df289ee6d8c87ecce4504d5a09969e05291e23c9ebc026a
BINARY_VERSION=2.1.301
BINARY_SHA256=1f04c69e1c24e4d0a716a863af0aad8fc64d49a499334c29701f073700276b99
R4_RECORDS_SHA256=ea3d581a027abd3538c3aa5271f169ca8ddc2d868e5f7fe104739ef1ccb8e75c
SEED=7

# ---- where things go; none of these paths may name the harness or sit in a checkout ----
CHECKOUT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HERE="$CHECKOUT/experiments/R-PG-01"
CORPUS="$CHECKOUT/corpora/injected-errors/v1"
BIN="${PHYSGATE_CLAUDE_BIN:-$HOME/pinned/claude-2.1.301-macos}"
ENV_FILE="${R_PG_01_ENV_FILE:-$HOME/dev/physgate/.env}"
N="${R_PG_01_ATTEMPT:-1}"
RUN_ROOT="${R_PG_01_RUN_ROOT:-$HOME/rpg01-runs}"
RUN="$RUN_ROOT/run-$N"
INSTALL="$RUN_ROOT/install-$N"
DRY="$RUN_ROOT/dry-$N"
R4="$RUN_ROOT/r4-$N"
LOGS="$RUN_ROOT/logs-$N"
REVIEW_ROOT="${R_PG_01_REVIEW_ROOT:-$HOME/review-scratch/rp1-$N}"

cd "$CHECKOUT"
mkdir -p "$LOGS"
LOG="$LOGS/launch.log"
say() { echo "$*" | tee -a "$LOG"; }
refuse() { say "REFUSED: $*"; exit 1; }
equal() { [ "$2" = "$3" ] || refuse "$1 is $2, not $3"; say "ok  $1 $3"; }
sha() { shasum -a 256 "$1" | cut -d' ' -f1; }
py() { uv run --frozen python -I "$@"; }

say "== R-PG-01 launch, attempt $N, $(date -u +%Y-%m-%dT%H:%M:%SZ), stop after: $STOP_AFTER"
[ "$(uname -s)" = Darwin ] || refuse "the run machine is the macOS laptop (CRITERIA.md §2)"

# ---- 1. the run's commit ----
git fetch -q origin
HEAD_SHA="$(git rev-parse HEAD)"
if [ "${R_PG_01_UNFROZEN:-}" = 1 ] && [ "$STOP_AFTER" != run ]; then
  say "SKIPPED: the run's-commit checks (R_PG_01_UNFROZEN=1, a trial before the freeze)"
else
  FROZE="$(git log -1 --format=%H -- experiments/R-PG-01)"
  equal "HEAD, the commit that last changed experiments/R-PG-01" "$HEAD_SHA" "$FROZE"
  git merge-base --is-ancestor HEAD origin/master || refuse "HEAD $HEAD_SHA is not on origin/master"
  [ -z "$(git status --porcelain)" ] || refuse "the checkout is not clean"
  say "ok  run commit $HEAD_SHA, clean, on origin/master"
fi

# ---- 2. the pinned hashes ----
equal "gate tree" "$(git rev-parse HEAD:src/physgate/gate)" "$GATE_TREE"
equal "bounds blob" "$(git rev-parse HEAD:knowledge/electrical/bounds.toml)" "$BOUNDS_BLOB"
equal "bounds sha256" "$(sha knowledge/electrical/bounds.toml)" "$BOUNDS_SHA256"
equal "spelling blob" "$(git rev-parse HEAD:src/physgate/unit_spelling.py)" "$SPELLING_BLOB"
equal "instrument tree" "$(git rev-parse HEAD:src/physgate/evaluation/inject)" "$INJECT_TREE"
equal "reviewers tree" "$(git rev-parse HEAD:src/physgate/reviewers)" "$REVIEWERS_TREE"
equal "rubrics tree" "$(git rev-parse HEAD:knowledge/reviewers)" "$RUBRICS_TREE"
equal "control rubric" "$(sha knowledge/reviewers/control/rubric.md)" "$RUBRIC_CONTROL"
equal "electrical rubric" "$(sha knowledge/reviewers/electrical/rubric.md)" "$RUBRIC_ELECTRICAL"
equal "firmware rubric" "$(sha knowledge/reviewers/firmware/rubric.md)" "$RUBRIC_FIRMWARE"
equal "mechanical rubric" "$(sha knowledge/reviewers/mechanical/rubric.md)" "$RUBRIC_MECHANICAL"
equal "corpus tree" "$(git rev-parse HEAD:corpora/injected-errors/v1)" "$CORPUS_TREE"
equal "corpus manifest sha256" "$(sha "$CORPUS/MANIFEST.json")" "$MANIFEST_SHA256"
uv sync --frozen -q
equal "catalogue digest" \
  "$(py -c 'from physgate.gate.catalogue import catalogue_digest; print(catalogue_digest())')" \
  "$CATALOGUE_SHA256"
[ -x "$BIN" ] || refuse "no binary at $BIN"
equal "binary sha256" "$(sha "$BIN")" "$BINARY_SHA256"
equal "binary version" "$("$BIN" --version | cut -d' ' -f1)" "$BINARY_VERSION"
py -c 'import sys; from pathlib import Path
from physgate.evaluation.inject.runner import InstrumentParams
InstrumentParams.model_validate_json(Path(sys.argv[1]).read_bytes())' "$HERE/params.json" \
  || refuse "params.json does not validate against the instrument's schema"
say "ok  params.json $(sha "$HERE/params.json")"
export PHYSGATE_CLAUDE_BIN="$BIN"

# ---- 3. R3: nothing reachable ----
for p in "$RUN" "$INSTALL" "$DRY" "$R4" "$REVIEW_ROOT"; do
  [ ! -e "$p" ] || refuse "$p already exists: a run is never resumed (set R_PG_01_ATTEMPT)"
done
py "$HERE/r3_scan.py" "$CHECKOUT" "$REVIEW_ROOT" "$RUN" "$INSTALL" | tee -a "$LOG" \
  || refuse "R3 scan"
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

# ---- 4. the reviewer requests' defaults: the dry run, no model call ----
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

# ---- 5. R4: the twins alone, at the run's commit ----
py "$HERE/r4_twins.py" "$CORPUS" "$R4" "$R4_RECORDS_SHA256" | tee -a "$LOG" \
  || refuse "R4: the clean twins do not give 40/40 with records $R4_RECORDS_SHA256"
say "ok  R4"
[ "$STOP_AFTER" = r4 ] && { say "stopped after R4, as asked"; exit 0; }

# ---- 6. the run ----
[ -f "$ENV_FILE" ] || refuse "no env file at $ENV_FILE"
CLAUDE_CODE_OAUTH_TOKEN="$(sed -n 's/^CLAUDE_CODE_OAUTH_TOKEN=//p' "$ENV_FILE" | head -n 1 | tr -d "\"'")"
[ -n "$CLAUDE_CODE_OAUTH_TOKEN" ] || refuse "no token in the env file"
say "ok  token found: yes"
export CLAUDE_CODE_OAUTH_TOKEN
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL
export DISABLE_AUTOUPDATER=1
say "== the run starts $(date -u +%Y-%m-%dT%H:%M:%SZ): $RUN"
set +e
caffeinate -i uv run --frozen physgate inject \
  --corpus "$CORPUS" \
  --run-dir "$RUN" \
  --scratch "$REVIEW_ROOT" \
  --run-id "rp1-$N" \
  --seed "$SEED" \
  --params "$HERE/params.json" \
  --install "$INSTALL" \
  --review-clean-twins \
  > "$LOGS/run.log" 2>&1 < /dev/null
CODE=$?
set -e
# The token never belongs in what the run wrote: counts only, never a match.
for pattern in "$CLAUDE_CODE_OAUTH_TOKEN" sk-ant- oat01; do
  hits="$(grep -rlF -- "$pattern" "$RUN" "$INSTALL" "$LOGS" 2>/dev/null | wc -l | tr -d ' ')"
  [ "$pattern" = "$CLAUDE_CODE_OAUTH_TOKEN" ] && label=token || label="$pattern"
  say "scan $label: $hits files"
done
unset CLAUDE_CODE_OAUTH_TOKEN
say "== the run ended $(date -u +%Y-%m-%dT%H:%M:%SZ), exit $CODE; last line:"
tail -n 1 "$LOGS/run.log" | tee -a "$LOG"
exit "$CODE"
