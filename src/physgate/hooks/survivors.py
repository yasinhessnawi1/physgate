"""A shell command that left something running is refused after it, and the reaper's word logged.

On macOS the survivor reaper (:mod:`physgate.oslayer.reaper`) runs inside each sandboxed
command's own sandbox and stops whatever the command left running when it ends. It says so on
a line of its own on the command's standard error, which Claude Code hands the session and
this hook as part of the command's output (measured on 2.1.301: ``tool_response.stdout``
after a success, ``error`` after a failure). This hook turns its lines into decisions:

- ``stopped N process(es) this command left running``: the command is refused;
- ``not reaping: …`` (its fence was not proven, so it signalled nothing) and ``some process
  of this command was still running after reaping``: refused, with why;
- ``stopped N process(es) when the command was stopped``: a timeout or an interrupt, whose
  command already failed: logged as ``reaped``, which no count of refusals reads;
- ``done`` ends every sandboxed run. In a session whose configuration says the reaper is on,
  a shell command without it is refused: its reaper did not finish (the command killed it,
  or it was killed with the command), so what it left may still run.

Claude Code cuts a long output before it reaches the hook, and the reaper's lines come last
(measured on 2.1.301): after a success the hook gets the first 30 000 characters and the
path of the whole output, which Claude Code wrote into the session's configuration
directory, where no command reads or writes; its end is read from there. After a failure it
gets the first and the last 5 000 characters with ``... [N characters truncated] ...``
between them, and no path. Up to 30 000 characters of output, that last part is the
output's real end, and the reaper's lines are judged there. Beyond it, Claude Code had
already kept only the first 30 000, so kept and cut together come to that cap (measured
21.10.2026 at 20 000 to 60 000 characters): the real end is lost, and a missing ``done`` is
logged as ``reaper_unverified``, which the orchestrator records as an incident.

The lines are the reaper's word, read from output the command shares: a command can print
them. A printed refusal is the command's own; a printed ``done`` before the command kills its
reaper is a forgery this hook cannot tell from the real line, a residual the reaper states.
Nothing here signals or stops anything.
"""

from __future__ import annotations

import os
import re
import time
from typing import TYPE_CHECKING

from physgate.hooks.runtime import ALLOW, Decision, HookSpec, refuse
from physgate.hooks.state import append_log

if TYPE_CHECKING:
    from physgate.hooks.views import ConfigView, InputView

#: The reaper's tag (``physgate.oslayer.reaper.TAG``, which a test holds equal). Not imported:
#: the reaper module loads ``ctypes`` and ``subprocess``, which the hook hot path stays off.
TAG = "physgate-reaper:"

#: The reaper's lines, each whole on a line of its own.
LINE = re.compile(
    "^"
    + re.escape(TAG)
    + r" (?P<what>stopped (?P<count>[1-9][0-9]{0,5}) process\(es\) this command left running"
    r"|(?P<when>stopped [1-9][0-9]{0,5} process\(es\) when the command was "
    r"stopped \(signal [0-9]{1,2}\))"
    r"|(?P<done>done)"
    r"|not reaping: [^\n]{1,300}"
    r"|some process of this command was still running after reaping)$",
    re.MULTILINE,
)

#: The decision a timed-out or interrupted command's reaping is logged under.
REAPED = "reaped"
#: The decision a missing ``done`` line is logged under when the output's end was cut off.
UNVERIFIED = "reaper_unverified"
#: Claude Code's mark where it cut the middle out of a failed command's output.
TRUNCATED = re.compile(r"\n\.\.\. \[([0-9]{1,12}) characters truncated\] \.\.\.\n")
#: The most of a command's output Claude Code keeps before it cuts the middle (2.1.301).
KEPT_CAP = 30_000
#: How much of the end of a persisted output is read for the reaper's lines.
TAIL_BYTES = 16384

LEFT_RUNNING = (
    "This command left {count} process(es) running after it ended (started in a session of "
    "its own, or detached some other way), and they were stopped. Nothing a command starts "
    "may outlive it: run what you need in the foreground, within the command."
)
NOT_REAPED = (
    "The OS layer could not make sure this command left nothing running ({what}). Nothing a "
    "command starts may outlive it."
)
NOT_FINISHED = (
    "The OS layer's survivor reaper did not finish for this command (it gave no 'done' "
    "line: it was killed, or ended with the command), so what the command started may still "
    "run. Nothing a command starts may outlive it, and its reaper may not be stopped."
)


def _inside(path: str, root: str) -> bool:
    root = os.path.realpath(root)
    return path == root or path.startswith(root.rstrip("/") + "/")


def _persisted_end(path: object, config: ConfigView) -> str | None:
    """The end of an output Claude Code persisted, if it lies in a protected root."""
    if not isinstance(path, str) or not path:
        return None
    where = os.path.realpath(path)
    if not any(_inside(where, root.path) for root in config.protected_roots):
        return None
    try:
        fd = os.open(where, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        size = os.fstat(fd).st_size
        os.lseek(fd, max(0, size - TAIL_BYTES), os.SEEK_SET)
        return os.read(fd, TAIL_BYTES).decode("utf-8", "replace")
    except OSError:
        return None
    finally:
        os.close(fd)


def _told(hook_input: InputView, config: ConfigView) -> tuple[str, bool]:
    """What the command printed, as far as it reached this hook, and whether its end is cut."""
    response = hook_input.tool_response
    parts: list[str] = []
    cut = False
    if isinstance(response, dict):
        parts += [str(response.get(key) or "") for key in ("stdout", "stderr")]
        persisted = response.get("persistedOutputPath")
        if persisted:
            end = _persisted_end(persisted, config)
            cut = end is None
            parts.append(end or "")
    error = hook_input.error or ""
    marks = list(TRUNCATED.finditer(error))
    if marks:
        # Only what follows the last mark can hold the reaper's last lines. It is the
        # output's real end unless the output had reached Claude Code's cap before the cut.
        last = marks[-1]
        whole = last.start() + int(last.group(1)) + len(error) - last.end()
        cut = cut or whole >= KEPT_CAP
        error = error[last.end() :]
    parts.append(error)
    return "\n".join(parts), cut


def _log(hook_input: InputView, config: ConfigView, decision: str, what: str) -> None:
    append_log(
        config,
        {
            "t": time.time(),
            "session": hook_input.session_id,
            "agent": hook_input.agent_id,
            "profile": config.profile,
            "role": config.role,
            "event": hook_input.hook_event_name,
            "tool": hook_input.tool_name,
            "tool_input": hook_input.tool_input,
            "hook": "survivors",
            "decision": decision,
            "told": what,
        },
    )


def after_shell(hook_input: InputView, config: ConfigView) -> Decision:
    """After a shell command: refuse it if the reaper said it left something running."""
    if hook_input.tool_name != "Bash":
        return ALLOW
    told, cut = _told(hook_input, config)
    said = list(LINE.finditer(told))
    left = sum(int(m.group("count")) for m in said if m.group("count"))
    others = [
        m.group("what")
        for m in said
        if not (m.group("count") or m.group("when") or m.group("done"))
    ]
    if others:
        return refuse(NOT_REAPED.format(what="; ".join(others)))
    if left:
        return refuse(LEFT_RUNNING.format(count=left))
    for m in said:
        if m.group("when"):
            _log(hook_input, config, REAPED, m.group("what"))
    if config.survivor_reaper and not any(m.group("done") for m in said):
        if cut:
            _log(hook_input, config, UNVERIFIED, "the output's end was cut off before the hook")
            return ALLOW
        return refuse(NOT_FINISHED)
    return ALLOW


HOOK = HookSpec("survivors", {"PostToolUse": after_shell, "PostToolUseFailure": after_shell})
