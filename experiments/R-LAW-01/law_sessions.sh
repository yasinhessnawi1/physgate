#!/usr/bin/env bash
# R-LAW-01, CRITERIA.md §4, §7 and §12: one blind session per packet, and the token guard.
#
#   law_sessions.sh run <step> <coder|adjudicator|reality> <packets dir> <out dir> <model> <lanes> [<ids file>]
#   law_sessions.sh spent <ledger>
#   law_sessions.sh projection <ledger> <round-1 step>...
#   law_sessions.sh watch <work dir> <process group> <since file> <phase>
#   law_sessions.sh smoke <out dir>
#   law_sessions.sh envnames
#   law_sessions.sh pinned
#   law_sessions.sh standin
#
# run: every packet of <packets dir> (or those listed in <ids file>), each a session of the pinned
#   binary with the pinned model, effort high, no tools, no settings, no MCP, no session
#   persistence, an empty working directory, the step's system prompt and JSON schema, and only the
#   allowlisted environment (envnames; env -i): nothing else of the caller's reaches the binary.
#   Refused (exit 2) unless the driver's Python ($RLAW_PY, else the project's .venv) is 3.11 or
#   later; there is no other Python to fall back on.
#   - A call that completes (a result with is_error false, no other terminal reason, exit 0) is a
#     try. A try whose output lacks a valid form for some finding is retried once (law_verify.py
#     valid): the §5.5 retry, which is for an invalid form only.
#   - So is the binary's own report that the model's output never fit --json-schema (subtype
#     error_max_structured_output_retries, or terminal reason structured_output_retry_exhausted),
#     an error result: a completed try with no form, which gets the same one retry; a
#     second one leaves the line without that coder's form (classify takes it at any exit).
#   - A call that fails is not a try: any other error result (a usage limit, a rate limit, a
#     refused credential, a server error after the binary's own retries, an API error), no result
#     at all (a network failure, a crash, output that is not the binary's), another terminal
#     reason, or a non-zero exit. Its output is kept as <packet>.try<n>.failed-<time>.json, it is
#     logged in the ledger with its cause and in interruptions.jsonl, and STOPPED is written:
#     every session of the experiment stops starting, and the ones in flight end on their own.
#     A packet's third failed call in a row for one try, with the identical cause each time and
#     another packet's try completed between each (README reading 17, law_verify.py stuck), is a
#     deviation: it is written to deviations.json and logged, and the run stops for good.
#   - Every call appends one line to the ledger, counted and written in one append by
#     law_verify.py ledger: step, packet, try, model asked for, models the output names, tokens
#     (input, output, cache read and cache creation), exit code, validity, and the cause if the
#     call failed (``infrastructure``). A line that cannot be written stops the run, since the
#     guard would never count its call.
#   - Before each session, and once more after the last one settles, the ledger's total is read:
#     at 60,000,000 tokens every session stops and the file VOID is written beside the ledger (the
#     result is void, CRITERIA.md §12). A total that cannot be read (a torn line, a row without a
#     whole token count) fails closed: STOPPED with the cause, logged, and no session starts. It
#     is never VOID, which is the §12 result and is never resumed.
#   Prints counts of sessions, tries, failed calls and tokens only.
# spent: the ledger's token total over every try and failed call (law_verify.py spent), or a
#   refusal and exit 1 if any line of it cannot be read.
# projection: after calibration round 1, spent + (tokens per session measured in the named
#   round-1 steps) x (the table's 590 sessions less the sessions already run) must be at most
#   60,000,000; exit 1 otherwise (a deviation before any measured session). It reads the ledger
#   as spent does. Exit 1 is only a projection over the guard on a ledger read in full; a missing
#   ledger, one it cannot read, no round-1 session, or any failure to compute is exit 2, a stop,
#   never the deviation.
# watch: the launch script's watcher over one phase (its process group). It reads only evidence
#   newer than <since file>, which the launcher touches as the phase starts, so a resumed phase is
#   never stopped by the files of the stop it resumes from. At a usage-limit file or a third
#   rate-limit error of this phase it writes STOPPED and logs the stop: no new session starts and
#   the sessions in flight end on their own (each settled as a try or a failed call). At VOID it
#   also kills the phase. RLAW_WATCH_SECONDS sets the poll (default 30).
# smoke: one session of the pinned binary on a synthetic packet, with exactly the flags of a run,
#   to check before launch that --json-schema works with --tools "", that --setting-sources ""
#   keeps every CLAUDE.md out, and that the result's usage is the sum over its modelUsage. Not
#   part of the experiment: it writes no ledger line. Prints one JSON line; exit 0 if it holds.
# envnames: the names of the environment the binary receives, as env -i hands it over (sorted;
#   never the values).
# standin: RLAW_STANDIN held to be an executable that is not the pinned binary; exit 2 otherwise.
# pinned: RLAW_CLAUDE_BIN held to its sha256 and, run with that environment, its version; prints
#   its path, or exits 2. The launcher's preflight checks the binary through this.
#
# Environment:
#   RLAW_PROMPTS  the directory law_packets.py prompts wrote for the version in force (run)
#   RLAW_LEDGER   the ledger file (run; one per run of the experiment)
#   RLAW_CLAUDE_BIN  the pinned binary, held to its sha256 and version, or
#   RLAW_STANDIN  a scripted stand-in executable, for dry runs and tests only: every output and
#                 ledger line is then marked, and the tally refuses marked outputs
#   RLAW_SHEET_SHA256  with a stand-in only: the fixture sheet's digest
#   RLAW_RESUME=1 resume after a stop (a failed call, the watcher, a killed process). Allowed
#                 because each packet is an independent session on fixed inputs. Only a STOPPED
#                 older than ledger/phase-start (the launcher touches it as a phase starts) is the
#                 stop resumed from; one written since, or with no phase start, is a stop of the
#                 phase now running, and nothing starts. The resume is
#                 logged with its time in interruptions.jsonl beside the ledger, as every stop and
#                 failed call is; each is an interruption RESULT reports, not a deviation. A
#                 finished packet (a valid first try, or a second try) is never run again; a call
#                 cut off mid-session (its process killed) counts as a try and gets the frozen
#                 retry; a failed call is run again as the same try. No output file is ever
#                 overwritten.
#   RLAW_SHARED_OUT=1 a later step writing new packets into an out dir that holds an earlier
#                 step's outputs (the twin versions after the injected ones); not a resume
#
# Without either, a non-empty out dir is refused. VOID is never resumed.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
PY="${RLAW_PY:-$REPO/.venv/bin/python}"  # no fallback: run refuses to start without it (py_ok)
GUARD=60000000
TABLE_SESSIONS=590
PIN_MAC=1f04c69e1c24e4d0a716a863af0aad8fc64d49a499334c29701f073700276b99
PIN_LINUX=1e119036a802d359ba5f9886428e031586e8796f7a858d5a8ee179ac7b8604f0
PIN_VERSION="2.1.301"
EFFORT=high

#: The binary's whole environment (env -i): HOME, USER, LOGNAME, TMPDIR and LANG from the caller
#: where it has them, PATH fixed and the auto-updater off. Nothing else of the caller's reaches it.
binenv() { # command...: run it with exactly the allowlisted environment
  local a=() n
  for n in HOME USER LOGNAME TMPDIR LANG; do
    [ -n "${!n+set}" ] && a+=("$n=${!n}")
  done
  env -i ${a[@]+"${a[@]}"} PATH=/usr/bin:/bin:/usr/sbin:/sbin DISABLE_AUTOUPDATER=1 "$@"
}

standin_ok() { # RLAW_STANDIN: an executable, and never the pinned binary, so that no real session
  # runs with the pin's checks skipped (RLAW_REFUSE_STANDIN_SHA256 adds digests to refuse, for tests)
  local d p
  [ -x "$RLAW_STANDIN" ] || { echo "the stand-in $RLAW_STANDIN is not an executable" >&2; return 2; }
  d="$(sha "$RLAW_STANDIN")"
  for p in "$PIN_MAC" "$PIN_LINUX" ${RLAW_REFUSE_STANDIN_SHA256:-}; do
    if [ "$d" = "$p" ]; then
      echo "the stand-in is the pinned binary (sha256 $d): a real session never runs as a stand-in's" >&2
      return 2
    fi
  done
}

py_ok() { # the driver's Python exists and is 3.11 or later
  [ -x "$PY" ] && "$PY" -I -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 11) else 1)' 2>/dev/null
}

sha() { if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }
utc() { date -u +%FT%TZ; }

spent() { # ledger -> its token total, or a refusal and exit 1 if any line cannot be read
  "$PY" -I "$HERE/law_verify.py" spent "$1"
}

projection() { # exit 0 holds; 1 over the guard (the frozen deviation); 2 cannot be computed
  local ledger="$1"; shift
  "$PY" -I - "$HERE" "$ledger" "$GUARD" "$TABLE_SESSIONS" "$@" <<'PY'
import json, os, sys
def refuse(why):
    print(json.dumps({"refused": why}))
    sys.exit(2)
try:
    sys.path.insert(0, sys.argv[1])
    import law_verify as V
    ledger, guard, table = sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
    steps = set(sys.argv[5:])
    if not os.path.exists(ledger):
        refuse("no ledger: there is nothing to project from")
    rows = V.ledger_rows(ledger)  # the reader spent uses
    spent = sum(r["tokens"] for r in rows)
    r1 = [r for r in rows if r["step"] in steps]
    sessions_r1 = len({(r["step"], r["packet"]) for r in r1})
    sessions_all = len({(r["step"], r["packet"]) for r in rows})
    if not sessions_r1:
        refuse("no session of the round-1 steps is in the ledger")
    per = sum(r["tokens"] for r in r1) / sessions_r1
    remaining = max(table - sessions_all, 0)
    projected = spent + per * remaining
except SystemExit:
    raise
except Exception as exc:  # whatever stops the computation is no projection, never the deviation
    refuse(f"the projection cannot be computed: {type(exc).__name__}: {exc}")
ok = projected <= guard  # exit 1 only here: over the guard, on a ledger read in full
print(json.dumps({"spent": spent, "round_1_sessions": sessions_r1, "tokens_per_session": round(per),
                  "sessions_remaining": remaining, "projected": round(projected), "guard": guard,
                  "holds": ok}))
sys.exit(0 if ok else 1)
PY
}

classify() { # out err exit -> the cause of a failed call, or nothing for a completed one
  # (an exit of -1 is not known: a call found after a stop)
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
if (r.get("subtype") == "error_max_structured_output_retries"
        or term == "structured_output_retry_exhausted"):
    # the binary could not make the model's output fit --json-schema: a completed try with no
    # form, so §5.5's one retry applies (whatever the exit; the binary exits 1 on it)
    sys.exit(0)
if r.get("is_error") is not False:
    if status in (401, 403):
        print(f"credential_refused ({status})")
    elif status == 429:
        print("rate_limit (429)")
    elif isinstance(status, int):
        print(f"api_error ({status})")
    elif term == "api_error":
        print("api_error")
    else:
        print("error_result")
elif term is not None and term != "completed":
    print(f"terminal {term}")
elif rc not in (0, -1):
    print(f"exit {rc}")
PY
}

grep_newer() { # dir since grep-args...: grep over the session files newer than since
  # (every file, if since is missing: the watcher never goes blind)
  local d="$1" s="$2"; shift 2
  if [ -e "$s" ]; then
    find "$d" -type f \( -name '*.json' -o -name '*.err' \) -newer "$s" -exec grep "$@" {} + 2>/dev/null
  else
    find "$d" -type f \( -name '*.json' -o -name '*.err' \) -exec grep "$@" {} + 2>/dev/null
  fi
}

evidence() { # sessions dir, since file -> "<usage-limit files> <429s>" in files newer than it
  local d="$1" s="$2" lim r429
  [ -d "$d" ] || { echo "0 0"; return 0; }
  lim=$(grep_newer "$d" "$s" -l 'usage_limit_reached' | wc -l | tr -d ' ')
  r429=$(grep_newer "$d" "$s" -ho '"api_error_status": *429' | wc -l | tr -d ' ')
  echo "$lim $r429"
}

watch_phase() { # work group since phase
  local work="$1" group="$2" since="$3" phase="$4" lim r429 void
  local every="${RLAW_WATCH_SECONDS:-30}"
  while kill -0 -- "-$group" 2>/dev/null; do
    read -r lim r429 <<< "$(evidence "$work/sessions" "$since")"
    void=no; [ -e "$work/ledger/VOID" ] && void=yes
    if [ "$lim" -gt 0 ] || [ "$r429" -ge 3 ] || [ "$void" = yes ]; then
      echo "$(utc) WATCHER: usage-limit files $lim, 429s $r429 since phase $phase began, void $void"
      if [ "$void" = yes ]; then kill -TERM -- "-$group" 2>/dev/null; fi
      [ -e "$work/ledger/STOPPED" ] && return 0  # a driver stopped the run, and logged it
      echo "stopped by the watcher" >> "$work/ledger/STOPPED"
      python3 -I - "$phase" "$lim" "$r429" "$void" "$(utc)" <<'PY' >> "$work/ledger/interruptions.jsonl"
import json, sys
phase, lim, r429, void, utc = sys.argv[1:6]
print(json.dumps({"event": "stop", "step": "launch", "utc": utc,
                  "reason": f"the watcher stopped phase {phase}: usage-limit files {lim}, "
                            f"429s {r429} since it began, void {void}"}, sort_keys=True))
PY
      return 0
    fi
    sleep "$every"
  done
}

pinned_bin() { # -> the binary, held to its pin; exit 2 if it is not the pinned one
  local b="${RLAW_CLAUDE_BIN:?set RLAW_CLAUDE_BIN to the pinned binary}" d
  d="$(sha "$b")"
  [ "$d" = "$PIN_MAC" ] || [ "$d" = "$PIN_LINUX" ] || { echo "binary is not the pinned one" >&2; exit 2; }
  binenv "$b" --version 2>/dev/null | grep -q "^$PIN_VERSION " || { echo "binary version is not $PIN_VERSION" >&2; exit 2; }
  echo "$b"
}

invoke() { # bin model schema system packet out err: one call, exactly as every session runs
  # (the stand-in's too): an empty working directory and only the allowlisted environment
  local w rc
  w="$(mktemp -d "${TMPDIR:-/tmp}/rlaw.XXXXXX")"
  ( cd "$w" && binenv "$1" -p --model "$2" --effort "$EFFORT" --tools "" --setting-sources "" \
      --strict-mcp-config --no-session-persistence --output-format json \
      --json-schema "$(cat "$3")" --system-prompt "$(cat "$4")" \
      < "$5" > "$6" 2> "$7" )
  rc=$?
  rmdir "$w" 2>/dev/null || rm -rf "$w"
  return "$rc"
}

smoke() { # out dir
  local out="$1" bin standin=0 version rc
  [ ! -e "$out" ] || { echo "smoke: $out exists; give a new dir" >&2; exit 2; }
  mkdir -p "$out"
  if [ -n "${RLAW_STANDIN:-}" ]; then
    standin_ok || exit 2
    bin="$RLAW_STANDIN"; standin=1; version=standin
  else
    bin="$(pinned_bin)" || exit 2
    version="$(binenv "$bin" --version 2>/dev/null | head -1)"
  fi
  printf '%s' 'You answer the questions of the packet you are given, exactly and briefly.' > "$out/system.txt"
  printf '%s' '{"type": "object", "properties": {"sum": {"type": "number"}, "tools": {"type": "array", "items": {"type": "string"}}, "earlier_files": {"type": "array", "items": {"type": "string"}}}, "required": ["sum", "tools", "earlier_files"]}' > "$out/schema.json"
  cat > "$out/packet.md" <<'MD'
# Packet S0001

A synthetic packet for a smoke test of the session settings. It is not part of any experiment.

Answer in the JSON schema given:
- "sum": the value of 2 + 3.
- "tools": the name of every tool you can call in this session, or an empty list if you can call none.
- "earlier_files": the first line, quoted exactly, of every file whose contents were shown to you before this packet (for example inside a system reminder), or an empty list if none was.
MD
  invoke "$bin" claude-opus-5-5 "$out/schema.json" "$out/system.txt" "$out/packet.md" "$out/out.json" "$out/out.err"
  rc=$?
  python3 -I - "$out/out.json" "$rc" "$standin" "$version" "$(classify "$out/out.json" "$out/out.err" "$rc")" <<'PY'
import json, sys
path, rc, standin, version, cause = sys.argv[1], int(sys.argv[2]), sys.argv[3] == "1", sys.argv[4], sys.argv[5]
try:
    d = json.load(open(path))
except (OSError, ValueError):
    d = None
msgs = d if isinstance(d, list) else ([d] if isinstance(d, dict) else [])
res = [m for m in msgs if isinstance(m, dict) and m.get("type") == "result"]
r = res[-1] if res else {}
so = r.get("structured_output")
form = (isinstance(so, dict) and isinstance(so.get("sum"), (int, float))
        and isinstance(so.get("tools"), list) and isinstance(so.get("earlier_files"), list))
kinds = {"input_tokens": "inputTokens", "output_tokens": "outputTokens",
         "cache_read_input_tokens": "cacheReadInputTokens",
         "cache_creation_input_tokens": "cacheCreationInputTokens"}
usage = {k: int((r.get("usage") or {}).get(k) or 0) for k in kinds}
mu = r.get("modelUsage") or {}
summed = {k: sum(int((m or {}).get(v) or 0) for m in mu.values()) for k, v in kinds.items()}
checks = {
    "json_schema_with_no_tools": bool(not cause and form and so.get("sum") == 5),
    "no_claude_md": bool(form and so.get("earlier_files") == []),
    "usage_is_the_model_usage_sum": bool(mu) and usage == summed,
}
print(json.dumps({
    "smoke": True, "standin": standin, "binary_version": version, "model": "claude-opus-5-5",
    "exit": rc, "failed_call": cause or None, "is_error": r.get("is_error"),
    "subtype": r.get("subtype"), "terminal_reason": r.get("terminal_reason"),
    "structured_output": so, "tools_reported": so.get("tools") if form else None,
    "earlier_files_reported": so.get("earlier_files") if form else None,
    "usage": usage, "model_usage_sum": summed, "models_used": sorted(mu),
    "checks": checks, "holds": all(checks.values())}, sort_keys=True))
sys.exit(0 if all(checks.values()) else 1)
PY
}

case "${1:-}" in
  spent) spent "$2"; exit $? ;;
  projection) shift; projection "$@"; exit $? ;;
  watch) shift; watch_phase "$@"; exit 0 ;;
  smoke) shift; smoke "$@"; exit $? ;;
  envnames) binenv /usr/bin/env | sed -n 's/^\([A-Za-z_][A-Za-z0-9_]*\)=.*/\1/p' | sort | tr '\n' ' ' | sed 's/ $//'
    echo; exit 0 ;;
  standin) standin_ok; exit $? ;;
  pinned) pinned_bin; exit 0 ;;
  run) shift ;;
  *) sed -n '2,91p' "$0" >&2; exit 2 ;;
esac

[ $# -ge 6 ] || { echo "run needs: step kind packets out model lanes [ids]" >&2; exit 2; }
py_ok || { echo "the driver's python $PY is missing or older than 3.11 (RLAW_PY names another)" >&2; exit 2; }
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
WORK_DIR="$(dirname "$LEDGER_DIR")"  # deviations.json lives beside the ledger's directory
[ -e "$LEDGER_DIR/VOID" ] && { echo "VOID exists: the result is void; nothing runs" >&2; exit 3; }
event() { # kind reason [packet try cause]: one timed line in interruptions.jsonl
  python3 -I - "$1" "$STEP" "$2" "${3:-}" "${4:-}" "${5:-}" <<'PY' >> "$LEDGER_DIR/interruptions.jsonl"
import json, sys, datetime
kind, step, reason, packet, tr, cause = sys.argv[1:7]
row = {"event": kind, "step": step, "reason": reason,
       "utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
if packet:
    row.update({"packet": packet, "try": int(tr), "cause": cause})
print(json.dumps(row, sort_keys=True))
PY
}
stop() { # reason: write STOPPED and log the stop
  echo "$1" >> "$LEDGER_DIR/STOPPED"; event stop "$1"
}
older_than_phase() { # file -> 0 if it was last written before ledger/phase-start was touched
  python3 -I - "$1" "$LEDGER_DIR/phase-start" <<'PY'
import os, sys
try:
    sys.exit(0 if os.stat(sys.argv[1]).st_mtime_ns < os.stat(sys.argv[2]).st_mtime_ns else 1)
except OSError:
    sys.exit(1)  # no phase start: no stop can be shown to be from before it
PY
}
# A STOPPED older than the phase's start is the stop this run resumes from. One written since
# (or with no phase start to compare) is a stop of this phase, another driver's: nothing starts.
if [ "${RLAW_RESUME:-0}" = 1 ] && [ -e "$LEDGER_DIR/STOPPED" ] && older_than_phase "$LEDGER_DIR/STOPPED"; then
  event resume "after: $(tr '\n' ' ' < "$LEDGER_DIR/STOPPED")"
  mv "$LEDGER_DIR/STOPPED" "$LEDGER_DIR/STOPPED.$(date -u +%Y%m%dT%H%M%SZ)"
fi
if [ -e "$LEDGER_DIR/STOPPED" ]; then
  if [ "${RLAW_RESUME:-0}" = 1 ]; then
    echo "STOPPED was written since ledger/phase-start: this phase is stopped; nothing starts" >&2
  else
    echo "STOPPED exists: resume only with RLAW_RESUME=1" >&2
  fi
  exit 4
fi

STANDIN=0
SHEET_ARG=""
if [ -n "${RLAW_STANDIN:-}" ]; then
  standin_ok || exit 2
  BIN="$RLAW_STANDIN"; STANDIN=1
  # a fixture's own parts sheet, for a stand-in only; a real session is held to the pinned one
  SHEET_ARG="${RLAW_SHEET_SHA256:-}"
else
  BIN="$(pinned_bin)" || exit 2
fi

mkdir -p "$OUT"
if [ -n "$IDS" ]; then mapfile_ids=$(cat "$IDS"); else mapfile_ids=$(cd "$PACKETS" && ls [PQ]*.md | sed 's/\.md$//'); fi
if [ -n "$(ls -A "$OUT" 2>/dev/null)" ] && [ "${RLAW_RESUME:-0}" != 1 ]; then
  if [ "${RLAW_SHARED_OUT:-0}" = 1 ]; then
    for pid in $mapfile_ids; do
      [ -n "$(ls "$OUT/$pid".try* 2>/dev/null)" ] && { echo "shared out dir already holds $pid" >&2; exit 2; }
    done
  else
    echo "out dir is not empty; set RLAW_RESUME=1 only when told to resume" >&2; exit 2
  fi
fi

ledger_line() { # pid try exit valid file cause: one line, counted by law_verify, in one append
  # A line that cannot be written leaves its call uncounted by the guard: the run stops.
  "$PY" -I "$HERE/law_verify.py" ledger "$RLAW_LEDGER" "$STEP" "$1" "$2" "$MODEL" "$5" "$3" "$4" \
    "$STANDIN" "$6" || { stop "the ledger line of $1 try$2 could not be written"; return 1; }
}

valid_try() { # pid try -> 0 if that try's output has every form
  "$PY" -I "$HERE/law_verify.py" valid "$KIND" "$PACKETS/$1.md" "$PACKETS/key.json" "$OUT/$1.try$2.json" $SHEET_ARG >/dev/null
}

logged() { # pid try -> 0 if the ledger holds that try of this step (a failed call is no try)
  python3 -I - "$RLAW_LEDGER" "$STEP" "$1" "$2" <<'PY'
import json, sys, os
led, step, pid, tr = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
rows = [json.loads(x) for x in open(led) if x.strip()] if os.path.exists(led) else []
sys.exit(0 if any(r["step"] == step and r["packet"] == pid and r["try"] == tr
                  and not r.get("infrastructure") for r in rows) else 1)
PY
}

settle() { # pid try exit how: a call that ended becomes a try or a failed call
  # how: "live" (it just ended) or "found" (it was in flight when a stop came). Returns 0 for a
  # valid try, 1 for an invalid one, 2 for a failed call (not a try).
  local pid="$1" tr="$2" rc="$3" how="$4" part="$OUT/$1.try$2.part" cause stem dest n=0 valid=0
  [ -e "$part.err" ] || : > "$part.err"
  cause="$(classify "$part.json" "$part.err" "$rc")"
  if [ "$how" = found ] && [ "$cause" = no_result ]; then cause=""; fi  # cut off mid-call: a try
  if [ -n "$cause" ]; then
    stem="$OUT/$pid.try$tr.failed-$(date -u +%Y%m%dT%H%M%SZ)"
    dest="$stem"
    while [ -e "$dest.json" ]; do n=$((n+1)); dest="$stem-$n"; done
    mv -n "$part.json" "$dest.json"; mv -n "$part.err" "$dest.err"
    [ "$STANDIN" = 1 ] && : > "$dest.standin"
    ledger_line "$pid" "$tr" "$rc" 0 "$dest.json" "$cause"
    if [ "$how" = live ]; then
      event failed_call "$pid try$tr: $cause" "$pid" "$tr" "$cause"
    else
      event failed_call "$pid try$tr: $cause, found on resume" "$pid" "$tr" "$cause"
    fi
    # README reading 17: the third identical, packet-specific failure in a row is a deviation
    if "$PY" -I "$HERE/law_verify.py" stuck "$RLAW_LEDGER" "$STEP" "$pid" "$tr" "$OUT" \
        "$WORK_DIR/deviations.json" >/dev/null; then
      event deviation "$pid try$tr failed three times in a row with the same cause, $cause: a deviation (README reading 17)" "$pid" "$tr" "$cause"
      stop "a deviation: $pid try$tr is stuck on one cause, $cause"
    elif [ "$how" = live ]; then
      stop "a failed call at $pid try$tr: $cause"
    fi
    return 2
  fi
  if [ -e "$OUT/$pid.try$tr.json" ]; then echo "refused: $pid try$tr exists and is never overwritten" >&2; return 1; fi
  mv -n "$part.json" "$OUT/$pid.try$tr.json"; mv -n "$part.err" "$OUT/$pid.try$tr.err"
  [ "$STANDIN" = 1 ] && : > "$OUT/$pid.try$tr.standin"
  valid_try "$pid" "$tr"
  case $? in
    0) valid=1 ;;
    3) echo "REFUSED $pid: the packet lacks the full parts sheet" >&2; stop "packet $pid lacks the full parts sheet" ;;
  esac
  ledger_line "$pid" "$tr" "$rc" "$valid" "$OUT/$pid.try$tr.json" ""
  [ "$valid" = 1 ]
}

call() { # pid try: one call of the session, then settled
  local pid="$1" tr="$2" rc
  if [ -e "$OUT/$pid.try$tr.json" ]; then echo "refused: $pid try$tr exists and is never overwritten" >&2; return 1; fi
  invoke "$BIN" "$MODEL" "$SCHEMA" "$SYS" "$PACKETS/$pid.md" "$OUT/$pid.try$tr.part.json" "$OUT/$pid.try$tr.part.err"
  rc=$?
  settle "$pid" "$tr" "$rc" live
}

total_holds() { # -> 0 while the ledger's total is read and below the guard
  # At the guard: VOID (§12). A total that cannot be read as a non-negative integer fails closed:
  # a stop with its cause, never VOID, which is the §12 result and is never resumed.
  local t
  t="$(spent "$RLAW_LEDGER" 2>&1)"
  if [ $? -ne 0 ] || ! [[ "$t" =~ ^[0-9]+$ ]]; then
    local why
    why="the token guard cannot read the ledger's total: $(printf '%s' "${t:-no output}" | tr '\n' ' ')"
    # logged once: every guard that reads the same ledger finds the same cause
    { [ -e "$LEDGER_DIR/STOPPED" ] && grep -qxF -- "$why" "$LEDGER_DIR/STOPPED"; } || stop "$why"
    return 1
  fi
  if [ "$t" -ge "$GUARD" ]; then
    echo "token guard: $t >= $GUARD; the result is void" > "$LEDGER_DIR/VOID"; return 1
  fi
}

guard() {
  [ -e "$LEDGER_DIR/STOPPED" ] && return 1
  [ -e "$LEDGER_DIR/VOID" ] && return 1
  total_holds
}

session() {
  local pid="$1" tr v
  # a call in flight when a stop came: settled first, as a try or a failed call
  for tr in 1 2; do
    if [ -e "$OUT/$pid.try$tr.part.json" ]; then settle "$pid" "$tr" -1 found; fi
  done
  [ -e "$OUT/$pid.try2.json" ] && return 0   # finished: never run again
  tr=1
  if [ -e "$OUT/$pid.try1.json" ]; then
    # a first try from before a stop, cut off before its ledger line: logged now (marked)
    if ! logged "$pid" 1; then
      valid_try "$pid" 1 && v=1 || v=0
      ledger_line "$pid" 1 -1 "$v" "$OUT/$pid.try1.json" ""
    fi
    valid_try "$pid" 1 && return 0
    tr=2
  fi
  while guard; do
    call "$pid" "$tr"
    case $? in
      0|2) return 0 ;;                      # a valid try; or a failed call, run again on resume
      *) [ "$tr" = 2 ] && return 0; tr=2 ;;  # an invalid form: the one retry
    esac
  done
}

n=0
for pid in $mapfile_ids; do
  guard || break
  session "$pid" &
  n=$((n+1))
  if [ $((n % LANES)) -eq 0 ]; then wait; fi
done
wait
# the sessions in flight when the guard last read the ledger may have taken it past 60 M
[ -e "$LEDGER_DIR/VOID" ] || total_holds

"$PY" -I - "$HERE" "$RLAW_LEDGER" "$STEP" <<'PY'
import json, sys
sys.path.insert(0, sys.argv[1])
import law_verify as V
try:
    rows = V.ledger_rows(sys.argv[2])
except V.LedgerUnreadable as exc:
    print(json.dumps({"step": sys.argv[3], "refused": str(exc)}))
    sys.exit(0)
mine = [r for r in rows if r["step"] == sys.argv[3]]
tries = [r for r in mine if not r.get("infrastructure")]
print(json.dumps({"step": sys.argv[3], "sessions": len({r["packet"] for r in tries}),
                  "tries": len(tries), "invalid_tries": sum(1 for r in tries if not r["valid"]),
                  "failed_calls": len(mine) - len(tries),
                  "nonzero_exits": sum(1 for r in tries if r["exit"] not in (0, -1)),
                  "tokens_step": sum(r["tokens"] for r in mine),
                  "tokens_all_steps": sum(r["tokens"] for r in rows),
                  "standin": any(r["standin"] for r in mine)}, sort_keys=True))
PY
[ -e "$LEDGER_DIR/VOID" ] && exit 3
[ -e "$LEDGER_DIR/STOPPED" ] && exit 4
exit 0
