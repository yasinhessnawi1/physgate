#!/usr/bin/env bash
# R-PG-01b, CRITERIA.md §6 and §12: one reality session per packet, a token log and the 30 M guard.
#
#   reasons_sessions.sh run <packets dir> <out dir> <ids file> [<lanes>]
#   reasons_sessions.sh spent <ledger>
#
# run: every packet the ids file lists (reasons_packets.py writes injected.txt and twin.txt; the
#   controls' ids are its key's), each one session of the pinned binary on claude-opus-5-5, effort
#   high, no tools, no settings, no MCP, no session persistence, an empty working directory and an
#   empty home, R-LAW-01's reality prompt and schema (reasons_packets.py prompts, held to their
#   digests here again), and only an allowlisted environment (env -i) with the run account's token,
#   read from the shape-checked line of ~/.config/physgate-run.env and never printed.
#   - A call that completes (a result, is_error false, exit 0) is a try. A try whose output lacks
#     a valid form for some finding is tried once more (R-LAW-01's one retry); the first valid
#     form of each finding is the one used.
#   - A call that fails (a usage limit, a rate limit, a refused credential, an API error, no result,
#     a non-zero exit) is not a try: its output is kept as <packet>.try<n>.failed-<time>.json,
#     logged with its cause, and STOPPED is written beside the ledger: nothing more starts. A stop is
#     resumed only with RPB_RESUME=1; a failed call is then run again as the same try.
#   - Every call appends one line to the ledger: packet, try, model, tokens (the result's input,
#     output, cache read and cache creation), exit, validity, and the cause of a failed call.
#   - Before each session, and once more at the end, the ledger's total is read: at 30,000,000
#     tokens VOID is written beside it, nothing more starts, and §6's counts are not reported
#     (§12). A ledger that cannot be read stops the run (STOPPED), never VOID.
#   Prints counts of sessions, tries, failed calls and tokens only.
# spent: the ledger's token total over every call.
#
# Environment: RPB_PROMPTS (the prompts directory), RPB_LEDGER (the ledger file, one per reading);
# RPB_CLAUDE_BIN (default ~/pinned/claude-2.1.301), held to the Linux build's sha256 and 2.1.301;
# RPB_STANDIN, a scripted stand-in executable for tests only (never the pinned binary: refused),
# whose outputs and ledger lines are marked; RPB_ENV_FILE, for tests only with a stand-in.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GUARD=30000000
MODEL=claude-opus-5-5
EFFORT=high
PIN_LINUX=1e119036a802d359ba5f9886428e031586e8796f7a858d5a8ee179ac7b8604f0
PIN_MAC=1f04c69e1c24e4d0a716a863af0aad8fc64d49a499334c29701f073700276b99
PROMPT_SHA256=41438ab78097d57a6e986b24f4f8071516fa36c1f0393f408874cd81adb23913
SCHEMA_SHA256=57c3852f8aa0adf9450de3504509b0bf95f85e78c55ff77b199a9c0998172324

sha() { if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }
utc() { date -u +%FT%TZ; }

spent() { # ledger -> its total, or exit 1 if a line cannot be read
  python3 -I - "$1" <<'PY'
import json, sys
total = 0
try:
    for n, line in enumerate(open(sys.argv[1]), 1):
        if line.strip():
            row = json.loads(line)
            t = row["tokens"]
            if not isinstance(t, int) or t < 0:
                raise ValueError(f"line {n}: tokens")
            total += t
except FileNotFoundError:
    pass
except (ValueError, KeyError) as exc:
    print(f"the ledger cannot be read: {exc}", file=sys.stderr)
    sys.exit(1)
print(total)
PY
}

case "${1:-}" in
  spent) spent "$2"; exit $? ;;
  run) shift ;;
  *) sed -n '2,32p' "$0" >&2; exit 2 ;;
esac
[ $# -ge 3 ] || { echo "run needs: packets out ids [lanes]" >&2; exit 2; }
PACKETS="$(cd "$1" && pwd)"; OUT="$2"; IDS="$3"; LANES="${4:-1}"
: "${RPB_PROMPTS:?set RPB_PROMPTS}"; : "${RPB_LEDGER:?set RPB_LEDGER}"
SYS="$RPB_PROMPTS/reality_prompt.txt"; SCHEMA="$RPB_PROMPTS/reality_schema.json"
[ "$(sha "$SYS")" = "$PROMPT_SHA256" ] || { echo "the prompt is not R-LAW-01's" >&2; exit 2; }
[ "$(sha "$SCHEMA")" = "$SCHEMA_SHA256" ] || { echo "the schema is not R-LAW-01's" >&2; exit 2; }
LEDGER_DIR="$(cd "$(dirname "$RPB_LEDGER")" && pwd)"
[ -e "$LEDGER_DIR/VOID" ] && { echo "VOID exists: the reading is void; nothing runs" >&2; exit 3; }
if [ -e "$LEDGER_DIR/STOPPED" ]; then
  if [ "${RPB_RESUME:-0}" = 1 ]; then
    mv "$LEDGER_DIR/STOPPED" "$LEDGER_DIR/STOPPED.$(date -u +%Y%m%dT%H%M%SZ)"
  else
    echo "STOPPED exists: resume only with RPB_RESUME=1" >&2; exit 4
  fi
fi

STANDIN=0
if [ -n "${RPB_STANDIN:-}" ]; then
  d="$(sha "$RPB_STANDIN")"
  if [ "$d" = "$PIN_LINUX" ] || [ "$d" = "$PIN_MAC" ]; then
    echo "the stand-in is the pinned binary: a real session never runs as a stand-in's" >&2; exit 2
  fi
  BIN="$RPB_STANDIN"; STANDIN=1
  ENV_FILE="${RPB_ENV_FILE:?a stand-in names its env file}"
else
  BIN="${RPB_CLAUDE_BIN:-$HOME/pinned/claude-2.1.301}"
  [ "$(sha "$BIN")" = "$PIN_LINUX" ] || { echo "the binary is not the pinned Linux build" >&2; exit 2; }
  "$BIN" --version 2>/dev/null | grep -q '^2\.1\.301 ' || { echo "the binary is not 2.1.301" >&2; exit 2; }
  [ -z "${RPB_ENV_FILE:-}" ] || { echo "RPB_ENV_FILE is for a stand-in only" >&2; exit 2; }
  ENV_FILE="$HOME/.config/physgate-run.env"
fi
# The token is read by the launcher below, inside the process that execs the binary, so it is in
# no argument list and no shell variable; this only holds the env file to the token's shape.
LAUNCHER='
import os, re, sys
binary, model, effort, schema, system, env_file, cwd, home, check = sys.argv[1:10]
found = []
for raw in open(env_file).read().splitlines():
    line = raw.strip().removeprefix("export ").strip()
    if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
        found.append(line.split("=", 1)[1].strip().strip("\x27\x22"))
if len(found) != 1 or not re.fullmatch(r"sk-ant-oat01-[A-Za-z0-9_-]{20,}", found[0]):
    sys.exit(97)
if check == "1":
    sys.exit(0)
env = {"HOME": home, "PATH": "/usr/bin:/bin", "LANG": os.environ.get("LANG", "C.UTF-8"),
       "DISABLE_AUTOUPDATER": "1", "CLAUDE_CODE_OAUTH_TOKEN": found[0]}
os.chdir(cwd)
os.execve(binary, [binary, "-p", "--model", model, "--effort", effort, "--tools", "",
                   "--setting-sources", "", "--strict-mcp-config", "--no-session-persistence",
                   "--output-format", "json", "--json-schema", open(schema).read(),
                   "--system-prompt", open(system).read()], env)
'
python3 -I -c "$LAUNCHER" "$BIN" "$MODEL" "$EFFORT" "$SCHEMA" "$SYS" "$ENV_FILE" / / 1 \
  || { echo "the env file holds no single token line of the token's shape" >&2; exit 2; }
mkdir -p "$OUT"

invoke() { # packet out err: one call, in an empty directory with an empty home
  local w rc
  w="$(mktemp -d "${TMPDIR:-/tmp}/rpbr.XXXXXX")"
  mkdir "$w/cwd" "$w/home"
  python3 -I -c "$LAUNCHER" "$BIN" "$MODEL" "$EFFORT" "$SCHEMA" "$SYS" "$ENV_FILE" \
    "$w/cwd" "$w/home" 0 < "$1" > "$2" 2> "$3"
  rc=$?
  rm -rf "$w"
  return "$rc"
}

classify() { # out err exit -> the cause of a failed call, or nothing for a completed one
  python3 -I - "$1" "$2" "$3" <<'PY'
import json, sys
out, err, rc = sys.argv[1], sys.argv[2], int(sys.argv[3])
def text(p):
    try:
        return open(p, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""
raw = text(out)
if "usage_limit_reached" in raw or "usage_limit_reached" in text(err):
    print("usage_limit"); sys.exit(0)
try:
    d = json.loads(raw)
except ValueError:
    d = None
msgs = d if isinstance(d, list) else ([d] if isinstance(d, dict) else [])
res = [m for m in msgs if isinstance(m, dict) and m.get("type") == "result"]
if not res:
    print("no_result"); sys.exit(0)
r = res[-1]
status, term = r.get("api_error_status"), r.get("terminal_reason")
if r.get("subtype") == "error_max_structured_output_retries" or term == "structured_output_retry_exhausted":
    sys.exit(0)  # a completed try with no form: it gets the one retry
if r.get("is_error") is not False:
    print(f"api_error ({status})" if isinstance(status, int) else "error_result")
elif term is not None and term != "completed":
    print(f"terminal {term}")
elif rc != 0:
    print(f"exit {rc}")
PY
}

ledger_line() { # pid try exit valid file cause
  python3 -I - "$RPB_LEDGER" "$1" "$2" "$3" "$4" "$5" "$6" "$MODEL" "$STANDIN" "$(utc)" <<'PY'
import json, sys
led, pid, tr, rc, valid, path, cause, model, standin, utc = sys.argv[1:11]
try:
    d = json.load(open(path))
except (OSError, ValueError):
    d = None
msgs = d if isinstance(d, list) else ([d] if isinstance(d, dict) else [])
res = [m for m in msgs if isinstance(m, dict) and m.get("type") == "result"]
u = (res[-1].get("usage") or {}) if res else {}
tokens = sum(int(u.get(k) or 0) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
row = {"packet": pid, "try": int(tr), "model": model, "tokens": tokens, "exit": int(rc),
       "valid": valid == "1", "cause": cause or None, "standin": standin == "1", "utc": utc}
with open(led, "a") as f:
    f.write(json.dumps(row, sort_keys=True) + "\n")
PY
}

valid_try() { # pid try -> 0 if every finding of the packet has a valid form in that try
  python3 -I - "$HERE" "$PACKETS" "$1" "$OUT/$1.try$2.json" <<'PY'
import json, sys
sys.path.insert(0, sys.argv[1])
import reasons_packets as P
from pathlib import Path
key = json.loads((Path(sys.argv[2]) / "key.json").read_text())[sys.argv[3]]
fids = list(key["findings"])
sys.exit(0 if len(P.valid_forms(Path(sys.argv[4]), fids)) == len(fids) else 1)
PY
}

guard() { # 0 while the run may start a session
  [ -e "$LEDGER_DIR/STOPPED" ] && return 1
  [ -e "$LEDGER_DIR/VOID" ] && return 1
  local t
  t="$(spent "$RPB_LEDGER")" || { echo "the ledger cannot be read" >> "$LEDGER_DIR/STOPPED"; return 1; }
  if [ "$t" -ge "$GUARD" ]; then echo "token guard: $t >= $GUARD" > "$LEDGER_DIR/VOID"; return 1; fi
}

session() { # pid: its first try, and its one retry if a form is missing
  local pid="$1" tr rc cause stem
  [ -e "$OUT/$pid.try2.json" ] && return 0
  if [ -e "$OUT/$pid.try1.json" ]; then valid_try "$pid" 1 && return 0; tr=2; else tr=1; fi
  while guard; do
    invoke "$PACKETS/$pid.md" "$OUT/$pid.try$tr.part.json" "$OUT/$pid.try$tr.part.err"
    rc=$?
    cause="$(classify "$OUT/$pid.try$tr.part.json" "$OUT/$pid.try$tr.part.err" "$rc")"
    if [ -n "$cause" ]; then
      stem="$OUT/$pid.try$tr.failed-$(date -u +%Y%m%dT%H%M%SZ)"
      mv "$OUT/$pid.try$tr.part.json" "$stem.json"; mv "$OUT/$pid.try$tr.part.err" "$stem.err"
      ledger_line "$pid" "$tr" "$rc" 0 "$stem.json" "$cause"
      echo "a failed call at $pid try$tr: $cause" >> "$LEDGER_DIR/STOPPED"
      return 0
    fi
    mv "$OUT/$pid.try$tr.part.json" "$OUT/$pid.try$tr.json"; mv "$OUT/$pid.try$tr.part.err" "$OUT/$pid.try$tr.err"
    [ "$STANDIN" = 1 ] && : > "$OUT/$pid.try$tr.standin"
    if valid_try "$pid" "$tr"; then
      ledger_line "$pid" "$tr" "$rc" 1 "$OUT/$pid.try$tr.json" ""
      return 0
    fi
    ledger_line "$pid" "$tr" "$rc" 0 "$OUT/$pid.try$tr.json" ""
    [ "$tr" = 2 ] && return 0
    tr=2
  done
}

n=0
for pid in $(cat "$IDS"); do
  guard || break
  session "$pid" &
  n=$((n + 1))
  if [ $((n % LANES)) -eq 0 ]; then wait; fi
done
wait
[ -e "$LEDGER_DIR/VOID" ] || guard >/dev/null || true
python3 -I - "$RPB_LEDGER" "$IDS" <<'PY'
import json, sys
rows = [json.loads(x) for x in open(sys.argv[1]) if x.strip()]
ids = set(open(sys.argv[2]).read().split())
mine = [r for r in rows if r["packet"] in ids]
tries = [r for r in mine if not r.get("cause")]
print(json.dumps({"sessions": len({r["packet"] for r in tries}), "tries": len(tries),
                  "invalid_tries": sum(1 for r in tries if not r["valid"]),
                  "failed_calls": len(mine) - len(tries),
                  "tokens_these": sum(r["tokens"] for r in mine),
                  "tokens_all": sum(r["tokens"] for r in rows),
                  "standin": any(r["standin"] for r in mine)}, sort_keys=True))
PY
[ -e "$LEDGER_DIR/VOID" ] && exit 3
[ -e "$LEDGER_DIR/STOPPED" ] && exit 4
exit 0
