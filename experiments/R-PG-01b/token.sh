# R-PG-01b: the run account's token, as launch.sh handles it. Sourced; defines functions only.
#
# The token is never an argument of any command (``ps`` shows every process's arguments to every
# user of the machine), never printed, never exported by the launcher, and never written. It
# lives in one shell variable of the launcher, RPB_TOKEN, unexported, from rpb_load_token to
# rpb_drop_token, and reaches a child's environment only through rpb_exec_with_token.
#
#   rpb_load_token <env file>   the env file's shape first (grep -c), then the value (sed), both
#                               with stderr suppressed; a file of any other shape is refused with
#                               a reason that quotes nothing of it
#   rpb_exec_with_token <cmd>   exports the token and execs <cmd>: call it only in a subshell,
#                               ( rpb_exec_with_token ... ) or rpb_exec_with_token ... &, so the
#                               token is in that one child's environment and nowhere else
#   rpb_scan <path>...          counts the files under the paths holding the token, sk-ant- or
#                               oat01; the patterns go to grep in a file (-f), never as arguments;
#                               prints counts only; returns 1 on any hit or a grep error
#   rpb_scan_token <path>...    the same for the token alone: for files that name the prefixes
#                               in their own words (a scan's log, the dry run's own scan record)
#   rpb_drop_token              forgets it

#: The one line the env file holds for the token: the name, '=', the value, nothing else.
RPB_SHAPE_LINE='^CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-[A-Za-z0-9_-]{20,}$'
#: Any line that names the variable, however it is spelt: there must be exactly one.
RPB_SHAPE_NAMED='^[[:space:]]*(export[[:space:]]+)?CLAUDE_CODE_OAUTH_TOKEN[[:space:]]*='

rpb_load_token() {
  local file="$1" named shaped
  RPB_TOKEN=
  if [ ! -f "$file" ]; then
    echo "no env file at the run account's path" >&2
    return 1
  fi
  named="$(grep -c -E "$RPB_SHAPE_NAMED" "$file" 2>/dev/null)" || true
  shaped="$(grep -c -E "$RPB_SHAPE_LINE" "$file" 2>/dev/null)" || true
  if [ "$named" != 1 ] || [ "$shaped" != 1 ]; then
    echo "the env file does not hold exactly one token line of the token's shape" >&2
    return 1
  fi
  RPB_TOKEN="$(sed -n -E 's/^CLAUDE_CODE_OAUTH_TOKEN=(sk-ant-oat01-[A-Za-z0-9_-]{20,})$/\1/p' "$file" 2>/dev/null)" || true
  if [ -z "$RPB_TOKEN" ]; then
    echo "the token line could not be read" >&2
    return 1
  fi
}

rpb_exec_with_token() {
  export CLAUDE_CODE_OAUTH_TOKEN="$RPB_TOKEN"
  exec "$@"
}

rpb_scan() {
  _rpb_scan "token sk-ant- oat01" "$@"
}

rpb_scan_token() {
  _rpb_scan token "$@"
}

_rpb_scan() { # labels path...: each label's count of files; 1 on any hit or a grep error
  local labels="$1" found=0 label n status
  shift
  for label in $labels; do
    status=0
    if [ "$label" = token ]; then
      n="$(grep -rlF -f <(printf '%s\n' "$RPB_TOKEN") -- "$@" 2>/dev/null)" || status=$?
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

rpb_drop_token() {
  RPB_TOKEN=
  unset RPB_TOKEN
}
