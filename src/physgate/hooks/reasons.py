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
SERIES_OUTBOX_REASON = (
    "it is the series outbox, which a record reaches only when the script that ran the "
    "simulation writes it there through the series writer; no tool and no command writes into "
    "it, and the orchestrator admits a record from it only after checking the code it names"
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
