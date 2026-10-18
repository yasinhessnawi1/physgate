#!/usr/bin/env bash
# One example design run of the harness on the example brief (scripts/demo/brief.py), with the
# pinned binary, the parameters in scripts/demo/params.json and a hard spend cap held by
# scripts/demo/spend_watch.py. An example run, never an experiment result.
#
#   demo_run.sh <label> --real    [--seed N]   the real API, on ANTHROPIC_API_KEY from the env file
#   demo_run.sh <label> --dry-run [--seed N]   the scripted endpoint: no model, nothing spent
#
# The label is the run id and the run directory's name (letters, digits, - and _).
#
# Layout under $PHYSGATE_DEMO_HOME (default ~/runs/demo):
#   tooling/                 the harness checkout the run is driven from; clean, or the run is refused.
#                            Once: git clone <repo> tooling && git -C tooling checkout <branch>
#                                  && (cd tooling && uv sync --frozen)
#   install-<commit>/        the hooks' read-only installation, built on first use
#   cost_trend.jsonl         one priced line per finished run
#   <label>/run/             the run directory: what the operator UI shows. Copy it, as is, to
#                            ~/physgate-runs/<label> on the machine that runs the app.
#   <label>/target/          the target repository the sessions work in
#   <label>/review-scratch/  where reviews are prepared (outside every checkout, by the harness's rule)
#   <label>/launch.log, brief.md, params.json, decompose.{out,err}, run.{out,err}, spend.jsonl, cost.json
#
# Environment: PHYSGATE_DEMO_HOME, PHYSGATE_CLAUDE_BIN (default ~/pinned/claude-2.1.301),
# PHYSGATE_RUN_ENV (default ~/.config/physgate-run.env; read with --real only, never printed),
# PHYSGATE_ROLE_PYTHON (the interpreter role sessions find as python3; default from params.json),
# PHYSGATE_CAP_USD (default 45) and PHYSGATE_KILL_AT_USD (default 42: one request can finish
# after the watcher's last reading, so the stop fires a little below the cap).
set -euo pipefail

usage() { sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
sha() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1"; else shasum -a 256 "$1"; fi | cut -d' ' -f1; }
[ $# -ge 2 ] || usage
LABEL="$1"; shift
MODE=""; SEED=21
while [ $# -gt 0 ]; do
  case "$1" in
    --real) MODE=real ;;
    --dry-run) MODE=dry ;;
    --seed) shift; SEED="$1" ;;
    *) usage ;;
  esac
  shift
done
[ -n "$MODE" ] || usage
[[ "$LABEL" =~ ^[A-Za-z0-9_-]{1,64}$ ]] || { echo "label: letters, digits, - and _ only" >&2; exit 2; }

H="${PHYSGATE_DEMO_HOME:-$HOME/runs/demo}"
TOOLING="$H/tooling"
BIN="${PHYSGATE_CLAUDE_BIN:-$HOME/pinned/claude-2.1.301}"
ENV_FILE="${PHYSGATE_RUN_ENV:-$HOME/.config/physgate-run.env}"
CAP_USD="${PHYSGATE_CAP_USD:-45}"
KILL_AT_USD="${PHYSGATE_KILL_AT_USD:-42}"
# The per-call cache sheet for a real run; the scripted endpoint reports no cache split, so
# a dry run is priced on the flat sheet.
if [ "$MODE" = dry ]; then PRICES="2026-09-27"; else PRICES="2026-10-16"; fi
OUT="$H/$LABEL"
RUN="$OUT/run"
TARGET="$OUT/target"
REVIEW="$OUT/review-scratch"
PY="$TOOLING/.venv/bin/python"
PHYSGATE="$TOOLING/.venv/bin/physgate"
DEMO="$TOOLING/scripts/demo"

[ -x "$PY" ] && [ -x "$PHYSGATE" ] || { echo "no harness at $TOOLING (clone it and uv sync --frozen)" >&2; exit 1; }
[ -z "$(git -C "$TOOLING" status --porcelain)" ] || { echo "tooling tree not clean; the run is refused" >&2; exit 1; }
[ -x "$BIN" ] || { echo "no pinned binary at $BIN" >&2; exit 1; }
[ ! -e "$OUT" ] || { echo "$OUT exists; a run is never resumed or overwritten by this script" >&2; exit 1; }
COMMIT="$(git -C "$TOOLING" rev-parse HEAD)"
INSTALL="$H/install-${COMMIT:0:12}"
mkdir -p "$OUT" "$REVIEW"
LOG="$OUT/launch.log"

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PHYSGATE_CLAUDE_BIN="$BIN"
export DISABLE_AUTOUPDATER=1
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL CLAUDE_CODE_OAUTH_TOKEN

ENDPOINT_PID=""; WATCH_PID=""
cleanup() {
  [ -n "$WATCH_PID" ] && kill "$WATCH_PID" 2>/dev/null || true
  [ -n "$ENDPOINT_PID" ] && kill "$ENDPOINT_PID" 2>/dev/null || true
  unset ANTHROPIC_API_KEY KEY
}
trap cleanup EXIT

# The target repository: a README and the two module directories, one commit, no address.
mkdir -p "$TARGET/modules/control" "$TARGET/modules/firmware"
cat > "$TARGET/README.md" <<'EOF'
# Example design run: a two-wheeled self-balancing robot

The target repository of an example run of the design harness, on the balance loop and the
firmware main loop of a Pololu Balboa 32U4. The role sessions work under `modules/`; the
design-state graph is kept by the harness beside this repository. An example, not a result.
EOF
touch "$TARGET/modules/control/.gitkeep" "$TARGET/modules/firmware/.gitkeep"
git -C "$TARGET" init -q -b master
git -C "$TARGET" -c user.name=example -c user.email=example@localhost add -A
git -C "$TARGET" -c user.name=example -c user.email=example@localhost commit -q -m "the target repository of an example design run"

# The brief and the parameters, recorded beside the run.
"$PY" "$DEMO/brief.py" > "$OUT/brief.md"
if [ -n "${PHYSGATE_ROLE_PYTHON:-}" ]; then
  "$PY" - "$DEMO/params.json" "$OUT/params.json" "$PHYSGATE_ROLE_PYTHON" <<'EOF'
import json, sys
params = json.load(open(sys.argv[1]))
params["role_python"] = sys.argv[3]
json.dump(params, open(sys.argv[2], "w"), indent=1)
EOF
else
  cp "$DEMO/params.json" "$OUT/params.json"
fi

{
  echo "== example run $LABEL ($MODE) $(date -u +%FT%TZ)"
  echo "commit $COMMIT"
  echo "binary $(sha "$BIN") $("$BIN" --version)"
  echo "brief sha256 $(sha "$OUT/brief.md")"
  echo "params sha256 $(sha "$OUT/params.json")"
  echo "seed $SEED; cap USD $CAP_USD, the stop fires at USD $KILL_AT_USD; prices $PRICES"
} | tee "$LOG"

if [ "$MODE" = dry ]; then
  "$PY" "$DEMO/dry_endpoint.py" --seed "$SEED" > "$OUT/endpoint.out" 2> "$OUT/endpoint.err" &
  ENDPOINT_PID=$!
  for _ in $(seq 1 120); do [ -s "$OUT/endpoint.out" ] && break; sleep 0.5; done
  [ -s "$OUT/endpoint.out" ] || { echo "the scripted endpoint did not start (see endpoint.err)" >&2; exit 1; }
  ANTHROPIC_BASE_URL="$("$PY" -c 'import json,sys; print(json.loads(open(sys.argv[1]).readline())["url"])' "$OUT/endpoint.out")"
  export ANTHROPIC_BASE_URL
  export ANTHROPIC_API_KEY="sk-ant-test-dummy-not-a-credential"
  echo "endpoint $ANTHROPIC_BASE_URL (scripted; nothing is spent)" | tee -a "$LOG"
else
  [ -r "$ENV_FILE" ] || { echo "no env file at $ENV_FILE" >&2; exit 1; }
  set -a; . "$ENV_FILE"; set +a
  # Only the key: the subscription's token is not offered to a key-paid run.
  unset CLAUDE_CODE_OAUTH_TOKEN ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL
  [ -n "${ANTHROPIC_API_KEY:-}" ] || { echo "ANTHROPIC_API_KEY is not in the env file" >&2; exit 1; }
  echo "endpoint default (the real API, auth api_key)" | tee -a "$LOG"
fi
KEY="$ANTHROPIC_API_KEY"

echo "== decompose $(date -u +%FT%TZ)" | tee -a "$LOG"
set +e
"$PHYSGATE" decompose "$OUT/brief.md" --seed "$SEED" --run-id "$LABEL" --params "$OUT/params.json" \
  --target "$TARGET" --run-dir "$RUN" > "$OUT/decompose.out" 2> "$OUT/decompose.err" < /dev/null
DCODE=$?
set -e
cat "$OUT/decompose.out" | tee -a "$LOG"
if [ "$DCODE" -ne 0 ]; then
  echo "decompose exit $DCODE; nothing more is called (see decompose.err)" | tee -a "$LOG"
  exit "$DCODE"
fi

echo "== run $(date -u +%FT%TZ)" | tee -a "$LOG"
set +e
"$PHYSGATE" run --run-dir "$RUN" --target "$TARGET" --install "$INSTALL" --review-root "$REVIEW" \
  > "$OUT/run.out" 2> "$OUT/run.err" < /dev/null &
RUN_PID=$!
"$PY" "$DEMO/spend_watch.py" --pid "$RUN_PID" --run-dir "$RUN" --review-root "$REVIEW" \
  --cap-usd "$CAP_USD" --kill-at-usd "$KILL_AT_USD" --prices "$PRICES" --log "$OUT/spend.jsonl" \
  > "$OUT/spend.out" 2> "$OUT/spend.err" &
WATCH_PID=$!
wait "$RUN_PID"; CODE=$?
wait "$WATCH_PID"; WCODE=$?
WATCH_PID=""
set -e
echo "run exit $CODE; watcher exit $WCODE ($(tail -c 300 "$OUT/spend.out" | tr -d '\n' | cut -c1-300))" | tee -a "$LOG"
"$PY" -c 'import json,sys
try:
    out = json.loads(open(sys.argv[1]).read())
except Exception as exc:
    print(f"run printed no outcome ({exc}); see run.err"); sys.exit(0)
print("step", out.get("step"), "| subtasks", out.get("subtasks"), "| open queue items", out.get("open_queue_items"))
print("tokens", out.get("tokens"))' "$OUT/run.out" | tee -a "$LOG"

echo "== cost $(date -u +%FT%TZ)" | tee -a "$LOG"
set +e
"$PHYSGATE" cost --run-dir "$RUN" --prices "$PRICES" --review-root "$REVIEW" --append "$H/cost_trend.jsonl" \
  > "$OUT/cost.json" 2> "$OUT/cost.err"
CCODE=$?
set -e
"$PY" - "$OUT/cost.json" "$OUT/spend.jsonl" "$CCODE" <<'EOF' | tee -a "$LOG"
import json, sys
cost, spend, code = sys.argv[1], sys.argv[2], int(sys.argv[3])
try:
    line = json.loads(open(cost).read())
    held = line.get("reconciliation") or {}
    print(f"harness cost line: USD {line.get('usd')} (NOK {line.get('nok')}), basis {line.get('basis')}, "
          f"prices {line.get('prices_date')}, partial {line.get('partial')}, lower bound {line.get('lower_bound')}; "
          f"binary's own figure over the calls it read: USD {held.get('binary_usd')}; cost exit {code}")
except Exception as exc:
    print(f"no harness cost line ({exc}; cost exit {code}): the run did not finish, or see cost.err")
try:
    last = json.loads(open(spend).read().splitlines()[-1])
    print(f"watcher: spent USD {last['spent_usd']} ({last['calls']} calls; binary figure of ended calls "
          f"USD {last['binary_usd_ended_calls']}; list price of all calls USD {last['list_price_usd_all_calls']}); "
          f"cap USD {last['cap_usd']}, stop at USD {last['kill_at_usd']}; {last.get('outcome')}")
except Exception as exc:
    print(f"no watcher readout ({exc})")
EOF

# The scan: counts only, nothing rewritten. The key's value is never printed.
count() { grep -rlF -- "$1" "$OUT" 2>/dev/null | wc -l | tr -d ' '; }
echo "scan key: $(count "$KEY") files; sk-ant-: $(count sk-ant-) files; oat01: $(count oat01) files" | tee -a "$LOG"
unset ANTHROPIC_API_KEY KEY
echo "== ended $(date -u +%FT%TZ), exit $CODE. Run directory for the app: $RUN" | tee -a "$LOG"
exit "$CODE"
