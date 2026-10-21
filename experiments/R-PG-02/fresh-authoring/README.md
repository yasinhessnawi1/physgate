# The fresh set's authoring record (R-PG-02, CRITERIA §2, R2, R4, §10)

The set itself is `corpora/injected-errors/fresh-v1/` (manifest sha256
`e76a4904e7b42326a85a9a9267973518e6f79b510c8f2b8b3391e8b23d37620c`). This directory holds how it
was written, published after the run with `RESULT.md`.

- `records/provenance.md`: the sessions, their stream digests, turn counts and secret scans, and
  the briefs' and continuation messages' digests.
- `briefs/`: the frozen author briefs and the parts sheet, with `BRIEFS.sha256` (each file checks).
- `records/continue_A.txt`, `records/continue_B.txt`, `records/CONTINUATIONS.sha256`: the two
  fixed continuation messages, for revisions 21 to 40 (each file checks).
- `records/A/`, `records/B/`: each session's inputs digests, the messages it was resumed with and
  their digests, its outcome lines, and its sandbox (`config/settings.json`, `config/guard.py`,
  `config/mcp.json`).
- `records/proof_guarded.json`, `records/proof_control.json`: the sandbox proven on the scripted
  endpoint before any launch.
- `records/A_audit_*.json`, `records/B_audit*.json`: each session's audit (tools used, guard
  refusals, models, mentions of a gate or an answer).
- `records/preB-1/` to `records/preB-3/`: the three checks of the base and the clean revisions
  between the two sessions (the loader, the gate and the source check), each with the bare facts
  returned to session A (`resume_A.txt`) and the sheet's own listed facts. `records/after_a.json`
  is the state after session A.

Not published: the sessions' transcripts (about 10 MB of stream lines, digested in
`provenance.md`), the runtime's own account and settings files from each session's configuration
directory, and the sessions' working copies, which duplicate the set and the briefs. They stay on
the run machine.
