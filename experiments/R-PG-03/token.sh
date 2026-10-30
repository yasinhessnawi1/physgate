#!/usr/bin/env bash
# R-PG-03: the run account's token, as R-PG-01b's token.sh handles it. Sourced; defines functions
# only. Its discipline is R-PG-01b's, unchanged:
#
# The token is never an argument of any command (ps shows every process's arguments to every user
# of the machine), never printed, never exported by the script that sources this, and never
# written. It lives in one shell variable, RP3_TOKEN, unexported, from rp3_load_token to
# rp3_drop_token, and reaches a child's environment only through rp3_exec_with_token.
#
#   rp3_load_token <env file>   the env file's shape first (grep -c), then the value (sed), both
#                               with stderr suppressed; a file of any other shape is refused with a
#                               reason that quotes nothing of it
#   rp3_exec_with_token <cmd>   exports the token and execs <cmd>: call it only in a subshell,
#                               ( rp3_exec_with_token ... ) or rp3_exec_with_token ... &, so the
#                               token is in that one child's environment and nowhere else
#   rp3_scan <path>...          counts the files under the paths holding the token, sk-ant- or
#                               oat01; the patterns go to grep in a file (-f), never as arguments;
#                               prints counts only; returns 1 on any hit or a grep error
#   rp3_scan_token <path>...    the same for the token alone: for files that name the prefixes in
#                               their own words (a scan's log, a dry run's own scan record)
#   rp3_drop_token              forgets it

#: The one line the env file holds for the token: the name, '=', the value, nothing else.
RP3_SHAPE_LINE='^CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-[A-Za-z0-9_-]{20,}$'
#: Any line that names the variable, however it is spelt: there must be exactly one.
RP3_SHAPE_NAMED='^[[:space:]]*(export[[:space:]]+)?CLAUDE_CODE_OAUTH_TOKEN[[:space:]]*='

rp3_load_token() {
  local file="$1" named shaped
  RP3_TOKEN=
  if [ ! -f "$file" ]; then
    echo "no env file at the run account's path" >&2
    return 1
  fi
  named="$(grep -c -E "$RP3_SHAPE_NAMED" "$file" 2>/dev/null)" || true
  shaped="$(grep -c -E "$RP3_SHAPE_LINE" "$file" 2>/dev/null)" || true
  if [ "$named" != 1 ] || [ "$shaped" != 1 ]; then
    echo "the env file does not hold exactly one token line of the token's shape" >&2
    return 1
  fi
  RP3_TOKEN="$(sed -n -E 's/^CLAUDE_CODE_OAUTH_TOKEN=(sk-ant-oat01-[A-Za-z0-9_-]{20,})$/\1/p' "$file" 2>/dev/null)" || true
  if [ -z "$RP3_TOKEN" ]; then
    echo "the token line could not be read" >&2
    return 1
  fi
}

rp3_exec_with_token() {
  export CLAUDE_CODE_OAUTH_TOKEN="$RP3_TOKEN"
  exec "$@"
}

rp3_scan() {
  _rp3_scan "token sk-ant- oat01" "$@"
}

rp3_scan_token() {
  _rp3_scan token "$@"
}

_rp3_scan() { # labels path...: each label's count of files; 1 on any hit or a grep error
  local labels="$1" found=0 label n status
  shift
  for label in $labels; do
    status=0
    if [ "$label" = token ]; then
      n="$(grep -rlF -f <(printf '%s\n' "$RP3_TOKEN") -- "$@" 2>/dev/null)" || status=$?
    else
      n="$(grep -rlF -f <(printf '%s\n' "$label") -- "$@" 2>/dev/null)" || status=$?
    fi
    if [ "$status" -gt 1 ]; then
      echo "scan $label: grep failed ($status)"
      found=1
      continue
    fi
    n="$(printf '%s' "$n" | grep -c . 2>/dev/null)" || true
    echo "scan $label: $n files"
    [ "$n" = 0 ] || found=1
  done
  return "$found"
}

rp3_drop_token() {
  RP3_TOKEN=
  unset RP3_TOKEN
}

# Executed rather than sourced: one step of the run account's work, under the watcher.
#
#   token.sh run <log> <kind> <watched dir> -- <command...>
#
# loads the token from the run account's env file, runs <command> as one child (its own process
# group) with the token in its environment alone, watches it with watch_limit.sh (<kind>: block,
# authoring or reality) over <watched dir>, then scans <watched dir> for the token and drops it. It
# exits with the command's exit, or 1 if the token's scan found a hit. How the reality reading's
# sessions run (reality.py run), so they hold the same discipline as a block and an authoring turn.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  set -euo pipefail
  if [ "${1:-}" != run ] || [ "$#" -lt 6 ] || [ "$5" != "--" ]; then
    echo "usage: token.sh run <log> <kind> <watched dir> -- <command...>" >&2
    exit 2
  fi
  RP3_LOG="$2"; RP3_KIND="$3"; RP3_DIR="$4"; shift 5
  mkdir -p "$RP3_DIR"
  rp3_load_token "${RP3_ENV_FILE:-$HOME/.config/physgate-run.env}" 2>> "$RP3_LOG" || exit 1
  ( rp3_exec_with_token setsid "$@" ) &
  RP3_PID=$!
  "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/watch_limit.sh" "$RP3_LOG" "$RP3_KIND" "$RP3_PID" "$RP3_DIR" &
  RP3_WATCHER=$!
  set +e
  wait "$RP3_PID"; RP3_CODE=$?
  wait "$RP3_WATCHER"
  set -e
  if ! rp3_scan "$RP3_DIR" >> "$RP3_LOG"; then
    echo "the token's scan found a hit in what the step wrote" >> "$RP3_LOG"
    RP3_CODE=1
  fi
  rp3_drop_token
  exit "$RP3_CODE"
fi
