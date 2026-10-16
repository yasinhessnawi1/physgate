"""Series records: a role's simulation output, sealed beside the run, never design state.

A role's script writes each run's output through the series writer into its worktree's
outbox; the orchestrator collects the outbox when the session ends, before the attempt
is committed, and seals what it collected on the session's end line. A reader serves a
sealed record, held to its seal, to the reviewer packet, the consistency check and the
operator UI. The format is :mod:`physgate.series.record`.
"""

from __future__ import annotations
