#!/usr/bin/env bash
# R-LAW-01, CRITERIA.md §4, §7 and §12: one blind session per packet, and the token guard.
#
#   law_sessions.sh run <step> <coder|adjudicator|reality> <packets dir> <out dir> <model> <lanes> [<ids file>]
#   law_sessions.sh spent <ledger>
#   law_sessions.sh projection <ledger> <round-1 step>...
#
# run: every packet of <packets dir> (or those listed in <ids file>), each a session of the pinned
#   binary with the pinned model, effort high, no tools, no settings, no MCP, no session
#   persistence, an empty working directory, the step's system prompt and JSON schema. A try
#   whose output lacks a valid form for some finding is retried once (law_verify.py valid).
#   Every try appends one line to the ledger: step, packet, try, model asked for, models the
#   output names, tokens (input, output, cache read and cache creation), exit code, validity.
#   Before each session the ledger's total is read: at 60,000,000 tokens every session stops and
#   the file VOID is written beside the ledger (the result is void, CRITERIA.md §12). A usage
#   limit or a third rate-limit error in this step's output stops every session and writes
#   STOPPED. Prints counts of sessions, tries, failures and tokens only.
# spent: the ledger's token total over every try.
# projection: after calibration round 1, spent + (tokens per session measured in the named
#   round-1 steps) x (the table's 590 sessions less the sessions already run) must be at most
#   60,000,000; exit 1 otherwise (a deviation before any measured session).
#
# Environment:
#   RLAW_PROMPTS  the directory law_packets.py prompts wrote for the version in force (required)
#   RLAW_LEDGER   the ledger file (required; one per run of the experiment)
#   RLAW_CLAUDE_BIN  the pinned binary, held to its sha256 and version, or
#   RLAW_STANDIN  a scripted stand-in executable, for dry runs and tests only: every output and
#                 ledger line is then marked, and the tally refuses marked outputs
#   RLAW_SHEET_SHA256  with a stand-in only: the fixture sheet's digest
#   RLAW_RESUME=1 skip packets whose first try exists (otherwise a non-empty out dir is refused)
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
PY="${RLAW_PY:-$REPO/.venv/bin/python}"
[ -x "$PY" ] || PY=python3
GUARD=60000000
TABLE_SESSIONS=590
PIN_MAC=1f04c69e1c24e4d0a716a863af0aad8fc64d49a499334c29701f073700276b99
PIN_LINUX=1e119036a802d359ba5f9886428e031586e8796f7a858d5a8ee179ac7b8604f0
PIN_VERSION="2.1.301"
EFFORT=high

sha() { if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }

spent() {
  python3 -I - "$1" <<'PY'
import json, sys, os
p = sys.argv[1]
t = 0
if os.path.exists(p):
    for line in open(p):
        if line.strip():
            t += int(json.loads(line).get("tokens") or 0)
print(t)
PY
}

projection() {
  local ledger="$1"; shift
  python3 -I - "$ledger" "$GUARD" "$TABLE_SESSIONS" "$@" <<'PY'
import json, sys
ledger, guard, table = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
steps = set(sys.argv[4:])
rows = [json.loads(x) for x in open(ledger) if x.strip()]
spent = sum(int(r.get("tokens") or 0) for r in rows)
r1 = [r for r in rows if r["step"] in steps]
sessions_r1 = len({(r["step"], r["packet"]) for r in r1})
sessions_all = len({(r["step"], r["packet"]) for r in rows})
per = (sum(int(r.get("tokens") or 0) for r in r1) / sessions_r1) if sessions_r1 else 0.0
remaining = max(table - sessions_all, 0)
projected = spent + per * remaining
ok = sessions_r1 > 0 and projected <= guard
print(json.dumps({"spent": spent, "round_1_sessions": sessions_r1, "tokens_per_session": round(per),
                  "sessions_remaining": remaining, "projected": round(projected), "guard": guard,
                  "holds": ok}))
sys.exit(0 if ok else 1)
PY
}

case "${1:-}" in
  spent) spent "$2"; exit 0 ;;
  projection) shift; projection "$@"; exit $? ;;
  run) shift ;;
  *) sed -n '2,32p' "$0" >&2; exit 2 ;;
esac

[ $# -ge 6 ] || { echo "run needs: step kind packets out model lanes [ids]" >&2; exit 2; }
STEP="$1"; KIND="$2"; PACKETS="$(cd "$3" && pwd)"; OUT="$4"; MODEL="$5"; LANES="$6"; IDS="${7:-}"
: "${RLAW_PROMPTS:?set RLAW_PROMPTS}"; : "${RLAW_LEDGER:?set RLAW_LEDGER}"
case "$KIND" in
  coder) SYS="$RLAW_PROMPTS/coder_prompt.txt"; SCHEMA="$RLAW_PROMPTS/coder_schema.json" ;;
  adjudicator) SYS="$RLAW_PROMPTS/adjudicator_prompt.txt"; SCHEMA="$RLAW_PROMPTS/adjudicator_schema.json" ;;
  reality) SYS="$RLAW_PROMPTS/reality_prompt.txt"; SCHEMA="$RLAW_PROMPTS/reality_schema.json" ;;
  *) echo "kind must be coder, adjudicator or reality" >&2; exit 2 ;;
esac
case "$MODEL" in claude-opus-5-5|claude-fable-5-1) ;; *) echo "model is not a pinned one" >&2; exit 2 ;; esac
[ -f "$SYS" ] && [ -f "$SCHEMA" ] || { echo "prompt or schema missing" >&2; exit 2; }
LEDGER_DIR="$(dirname "$RLAW_LEDGER")"
[ -e "$LEDGER_DIR/VOID" ] && { echo "VOID exists: the result is void; nothing runs" >&2; exit 3; }
[ -e "$LEDGER_DIR/STOPPED" ] && { echo "STOPPED exists: resolve it first" >&2; exit 4; }

STANDIN=0
SHEET_ARG=""
if [ -n "${RLAW_STANDIN:-}" ]; then
  BIN="$RLAW_STANDIN"; STANDIN=1
  # a fixture's own parts sheet, for a stand-in only; a real session is held to the pinned one
  SHEET_ARG="${RLAW_SHEET_SHA256:-}"
else
  BIN="${RLAW_CLAUDE_BIN:?set RLAW_CLAUDE_BIN to the pinned binary}"
  d="$(sha "$BIN")"
  [ "$d" = "$PIN_MAC" ] || [ "$d" = "$PIN_LINUX" ] || { echo "binary is not the pinned one" >&2; exit 2; }
  "$BIN" --version 2>/dev/null | grep -q "^$PIN_VERSION " || { echo "binary version is not $PIN_VERSION" >&2; exit 2; }
  export DISABLE_AUTOUPDATER=1
  unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL
fi

mkdir -p "$OUT"
if [ -n "$(ls -A "$OUT" 2>/dev/null)" ] && [ "${RLAW_RESUME:-0}" != 1 ]; then
  echo "out dir is not empty; set RLAW_RESUME=1 only when told to resume" >&2; exit 2
fi
if [ -n "$IDS" ]; then mapfile_ids=$(cat "$IDS"); else mapfile_ids=$(cd "$PACKETS" && ls [PQ]*.md | sed 's/\.md$//'); fi

ledger_line() { # pid try exit valid
  python3 -I - "$STEP" "$1" "$2" "$MODEL" "$OUT/$1.try$2.json" "$3" "$4" "$STANDIN" <<'PY' >> "$RLAW_LEDGER"
import json, sys, datetime
step, pid, tr, model, out, code, valid, standin = sys.argv[1:9]
try:
    d = json.load(open(out))
except Exception:
    d = None
msgs = d if isinstance(d, list) else ([d] if isinstance(d, dict) else [])
res = [m for m in msgs if isinstance(m, dict) and m.get("type") == "result"]
r = res[-1] if res else {}
u = r.get("usage") or {}
tok = sum(int(u.get(k) or 0) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
print(json.dumps({"step": step, "packet": pid, "try": int(tr), "model_asked": model,
                  "models_used": sorted((r.get("modelUsage") or {}).keys()), "tokens": tok,
                  "exit": int(code), "valid": valid == "1", "standin": standin == "1",
                  "utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
                 sort_keys=True))
PY
}

limited() { # pid try -> 0 if this try hit a usage limit, or this step has three 429s
  grep -qs 'usage_limit_reached' "$OUT/$1.try$2.json" "$OUT/$1.try$2.err" && return 0
  [ "$(cat "$OUT"/*.json 2>/dev/null | grep -o '"api_error_status": *429' | wc -l)" -ge 3 ]
}

one_try() { # pid try
  local pid="$1" tr="$2" w rc valid=0
  w="$(mktemp -d "${TMPDIR:-/tmp}/rlaw.XXXXXX")"
  ( cd "$w" && "$BIN" -p --model "$MODEL" --effort "$EFFORT" --tools "" --setting-sources "" \
      --strict-mcp-config --no-session-persistence --output-format json \
      --json-schema "$(cat "$SCHEMA")" --system-prompt "$(cat "$SYS")" \
      < "$PACKETS/$pid.md" > "$OUT/$pid.try$tr.json" 2> "$OUT/$pid.try$tr.err" )
  rc=$?
  rmdir "$w" 2>/dev/null || rm -rf "$w"
  [ "$STANDIN" = 1 ] && : > "$OUT/$pid.try$tr.standin"
  "$PY" -I "$HERE/law_verify.py" valid "$KIND" "$PACKETS/$pid.md" "$PACKETS/key.json" "$OUT/$pid.try$tr.json" $SHEET_ARG >/dev/null
  case $? in 0) valid=1 ;; 3) echo "REFUSED $pid: the packet lacks the full parts sheet" >&2; touch "$LEDGER_DIR/STOPPED"; valid=0 ;; esac
  ledger_line "$pid" "$tr" "$rc" "$valid"
  if limited "$pid" "$tr"; then echo "usage limit or rate limit at $pid try$tr" > "$LEDGER_DIR/STOPPED"; fi
  [ "$valid" = 1 ]
}

guard() {
  [ -e "$LEDGER_DIR/STOPPED" ] && return 1
  [ -e "$LEDGER_DIR/VOID" ] && return 1
  local t; t="$(spent "$RLAW_LEDGER")"
  if [ "$t" -ge "$GUARD" ]; then
    echo "token guard: $t >= $GUARD; the result is void" > "$LEDGER_DIR/VOID"; return 1
  fi
}

session() {
  local pid="$1"
  if [ "${RLAW_RESUME:-0}" = 1 ] && [ -e "$OUT/$pid.try1.json" ]; then return 0; fi
  guard || return 0
  one_try "$pid" 1 && return 0
  guard || return 0
  one_try "$pid" 2 || true
}

n=0
for pid in $mapfile_ids; do
  guard || break
  session "$pid" &
  n=$((n+1))
  if [ $((n % LANES)) -eq 0 ]; then wait; fi
done
wait

python3 -I - "$RLAW_LEDGER" "$STEP" <<'PY'
import json, sys
rows = [json.loads(x) for x in open(sys.argv[1]) if x.strip()]
mine = [r for r in rows if r["step"] == sys.argv[2]]
print(json.dumps({"step": sys.argv[2], "sessions": len({r["packet"] for r in mine}),
                  "tries": len(mine), "invalid_tries": sum(1 for r in mine if not r["valid"]),
                  "nonzero_exits": sum(1 for r in mine if r["exit"] != 0),
                  "tokens_step": sum(r["tokens"] for r in mine),
                  "tokens_all_steps": sum(r["tokens"] for r in rows),
                  "standin": any(r["standin"] for r in mine)}, sort_keys=True))
PY
[ -e "$LEDGER_DIR/VOID" ] && exit 3
[ -e "$LEDGER_DIR/STOPPED" ] && exit 4
exit 0
