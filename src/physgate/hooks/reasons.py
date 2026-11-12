"""Reasons an agent is given for protected roots that more than one module names.

Kept apart so the hooks on the hot path can use them without importing the
settings generator, which imports the validation library.
"""

from __future__ import annotations

HELD_OUT_REASON = (
    "it is the held-out evaluation tier, which nothing reads or writes before "
    "measurement (ARCH-141)"
)
ANSWER_KEY_REASON = (
    "it is an evaluation corpus whose files state each artefact's injected error and the "
    "check expected to catch it; no session writes it, and no reviewer reads it, because a "
    "reviewer that read the answer would make the measurement of what reviewers miss "
    "measure nothing"
)
GATE_REASON = "it holds the physics gate, which no agent session writes (ARCH-081)"
KNOWLEDGE_REASON = (
    "it holds curated standards or skill content; a human promotes a candidate into it "
    "with the promotion command, and no agent session writes it directly (ARCH-100)"
)
SERIES_WRITER_REASON = (
    "it holds the series writer every role's scripts record their simulations through, put "
    "there by the orchestrator; no session writes it, since a changed writer could record a "
    "curve other than the one its script computed"
)


def series_outbox_reason(platform: str, *, os_layer: bool) -> str:
    """The reason given for the series outbox, saying only what holds where the session runs.

    What a command can read back depends on the OS layer and on the platform's mechanism
    (:func:`physgate.oslayer.policy.outbox_read_denial`): on macOS nothing in the outbox is
    readable to any command; on Linux a record an earlier command wrote is unreadable in the
    outbox, but the command that wrote it can read it back and keep a copy (a link or the
    bytes) where later commands read it; without the OS layer only the hooks' text rule stands.
    """
    if os_layer and platform == "darwin":
        reads = "no command can read it back"
    elif os_layer and platform.startswith("linux"):
        reads = (
            "no command can read back a record an earlier command wrote, unless the command "
            "that wrote it kept a copy"
        )
    else:
        reads = "nothing but this refusal keeps a command from reading it"
    return (
        "it is the series outbox, which a record reaches when the script that ran the "
        "simulation writes it there through the series writer; no file tool writes or reads "
        f"it, no command may name it, and {reads}; the orchestrator seals a record from it "
        "only when the code it names is the module's, unchanged and committed"
    )


STORE_REASON = (
    "it is the design-state graph's own store: its journal is the only authority, and a "
    "line appended to it is replayed as genuine, so no agent tool writes any file in it"
)
HARNESS_REASON = (
    "it is the checkout the orchestrator runs from: the physics gate's source, the curated "
    "library and its bounds tables, and the frozen experiments a run is judged by, which no "
    "session in another worktree writes"
)

#: Given for a read or a write of a run record no session doing design work reads: the run's
#: recorded configuration, which holds the canaries the stream scan looks for.
WITHHELD_REASON = (
    "it is one of the run's own records that no session doing design work reads: the run's "
    "configuration names what the stream scan looks for to tell that the held-out tier was read"
)

#: Given for any tool's read or write of the session's hook state directory. The hooks keep there
#: what the sentinel needs to put a protected path back, their log and, in the api_key mode, the
#: credential's helper; they read and write it in their own processes, never through a tool.
HOOK_STATE_REASON = "it holds the hook layer's own records of this session"

#: Given for a role or baseline session's read of the run's session directories: every session's
#: login, captured stream, settings and hook records. Only what it is given to read there is open.
#: Given for a write into the run's recorded tool environment.
TOOL_ENVIRONMENT_REASON = (
    "it is the run's recorded tool environment: the interpreter, the libraries and the build "
    "tools every session computes and builds with, held to the bytes the run recorded; it is "
    "read and run, and written by no session"
)

SESSIONS_REASON = (
    "it is the run's session directories, which hold each session's login, stream and records; "
    "a session reads there only what it is given to read"
)

#: Given for a role, baseline or reviewer session's read or write of the temporary directory every
#: Claude Code session of the user on the machine shares, which holds the other sessions' task
#: outputs. The session's own binary is pointed at a directory of its own, so none of it is there.
CLAUDE_TEMP_REASON = (
    "it is the temporary directory every Claude Code session of this user on the machine shares, "
    "which holds the other sessions' output; this session has a temporary directory of its own"
)

#: Given for a role, baseline or reviewer session's read or write of another session's own
#: temporary directory: every one lies directly beneath one parent, and only the session's own
#: child there is open to it.
SESSION_TEMPS_REASON = (
    "it is where each session keeps its own temporary files, which no other session reads or "
    "writes; this session's own temporary directory is the one child there open to it"
)

#: Given to a reviewer for a read outside its allowance. Neutral on purpose: a
#: reviewer is shown nothing that says what is being measured.
OUTSIDE_REVIEW_REASON = "it is outside the files this review is given"
REVIEW_MATERIAL_REASON = (
    "it is material only the paired reviewer reads; an implementing session that read "
    "what its reviewer looks for could steer its work around it"
)
GIT_USER_CONFIG_REASON = (
    "it is git's user configuration for this session, where a key could make a later git "
    "command run a program the session chose; a role session reads git's configuration and "
    "never writes it"
)
