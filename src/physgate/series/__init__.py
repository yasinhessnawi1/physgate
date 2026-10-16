"""Series records: a role's simulation output, sealed beside the run, never design state.

A role's script writes each run's output through the series writer into its worktree's
outbox; the orchestrator collects the outbox when the session ends, before the attempt
is committed, and seals what it collected on the session's end line. A reader serves a
sealed record, held to its seal, to the reviewer packet, the consistency check and the
operator UI. The format is :mod:`physgate.series.record`.

What it owns: the record format and its bounds (``record``, ``seal``), the role's writer
(``writer``), the collection and sealing of a session's outbox (``collect``), the bounded,
seal-held reader (``reader``), the published extractors and how a value is read off a record
(``extract``), the frozen tolerance (``tolerance``), the check of a graph quantity against the
record it names (``consistency``), and the listing a review is given (``summary``).

What it deliberately does not own: re-running a recorded script to show that it produces the
curve it recorded (a record proves which committed code it names, not that the code computed
it); deciding whether a role records a simulation at all; drawing a record, which the operator
UI does with this reader; and the physics gate's own unit parser, which does not yet use the
bounded spelling in :mod:`physgate.unit_spelling`.
"""

from __future__ import annotations
