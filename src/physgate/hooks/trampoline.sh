#!/bin/sh
# Fail-closed wrapper around every hook command.
#
# Usage: trampoline.sh <watchdog-seconds> <command> [args...]
#
# Claude Code lets a tool call run on any hook outcome except exit status 2 or
# an explicit JSON refusal. Measured on the pinned version: exit 1, exit 3, an
# uncaught exception, a killed process, a missing interpreter and a hook that
# outlives its timeout all let the tool run. So this wrapper passes a clean 0
# and a 2 through, and turns everything else into a 2. It also kills the hook
# itself after <watchdog-seconds>, which must be shorter than Claude Code's own
# hook timeout: when that one fires first, the tool runs.
#
# It is shell, not Python, because the case it exists for is the Python side
# failing to start at all.
umask 077
W="$1"
shift
tmp_in=$(mktemp) || exit 2
tmp_out=$(mktemp) || { rm -f "$tmp_in"; exit 2; }
cat > "$tmp_in"
"$@" < "$tmp_in" > "$tmp_out" &
child=$!
# The watchdog's descriptors are detached so that a still-sleeping watchdog
# never holds Claude Code's pipe open, and it takes its sleep down with it when
# it is told to stop.
(
  sleep "$W" &
  s=$!
  trap 'kill "$s" 2>/dev/null; exit 0' TERM
  wait "$s" && kill -9 "$child" 2>/dev/null
) </dev/null >/dev/null 2>&1 &
dog=$!
wait "$child"
rc=$?
kill "$dog" 2>/dev/null
wait "$dog" 2>/dev/null
cat "$tmp_out"
rm -f "$tmp_in" "$tmp_out"
[ "$rc" -eq 0 ] && exit 0
[ "$rc" -eq 2 ] && exit 2
echo "The hook that checks this call could not reach a decision (exit status $rc), so the call is refused." >&2
exit 2
