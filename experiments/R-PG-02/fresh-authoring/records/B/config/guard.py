"""PreToolUse guard for a corpus-author session: files inside the scratch directory only.

Standard library only, fails closed. The scratch directory is the first argument.
Any tool other than Read, Write or Edit is refused; a path is resolved (symlinks,
``..``, relative to the call's cwd) and refused unless it lies inside the scratch
directory, also resolved. Any error while deciding is a refusal.
"""
import json
import os
import sys

ALLOWED = {"Read", "Write", "Edit"}


def deny(reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
          "permissionDecision": "deny", "permissionDecisionReason": reason}}))
    print(reason, file=sys.stderr)
    sys.exit(2)


def main() -> None:
    scratch = os.path.realpath(sys.argv[1])
    event = json.load(sys.stdin)
    tool = event.get("tool_name")
    if tool not in ALLOWED:
        deny(f"The tool {tool!r} is not available in this session; only Read, Write and Edit are.")
    path = (event.get("tool_input") or {}).get("file_path")
    if not isinstance(path, str) or not path:
        deny("A file tool without a file path cannot be checked, so it is refused.")
    cwd = event.get("cwd") or scratch
    absolute = os.path.realpath(os.path.join(cwd, os.path.expanduser(path)))
    if os.path.commonpath([absolute, scratch]) != scratch:
        deny(f"{path} is outside this session's working directory; only files inside it may be used.")
    sys.exit(0)


try:
    main()
except SystemExit:
    raise
except BaseException as exc:  # noqa: BLE001 - fail closed on anything
    deny(f"The guard could not decide ({type(exc).__name__}), so the call is refused.")
