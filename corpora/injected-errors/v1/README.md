# Corpus provenance

Injected-error corpus, version 1: forty artefacts, ten each with a unit,
magnitude, equilibrium or propagation error injected into an otherwise valid
revision of a stand-in design. Built by two sandboxed corpus-author sessions,
each with Read, Write and Edit tools only (no shell, no web), on the
subscription, model `claude-opus-5-5`, pinned Claude Code binary version
2.1.283. Neither session read the physics gate's implementation, its
relations, its bounds table, or any prior test or review of it. Neither
session ever saw a gate result, except that the first session — after its
base design failed the gate on two checks, then twice more failed a check on
how one of its numbers was sourced — was resumed three times, each time with
only that one refusal's own text; nothing else the gate or the loader found
reached it. The second session never saw any gate or loader output at all,
including the base's.

## Session A — base design and forty clean revisions

| | |
|---|---|
| Session id | `19a2f50c-65f1-4aba-b9c2-a3df3b00ed25` |
| Model | `claude-opus-5-5` |
| Initial run | 2026-09-28, local afternoon/evening; 50 turns; exit 0, success |
| Resume 1 (base's two failing checks, message only) | 2026-09-28, later the same evening; 40 turns; exit 0, success |
| Resume 2 (a sourcing refusal on one derived number, message only) | 2026-09-29, early morning; 32 turns; exit 0, success |
| Resume 3 (a second sourcing refusal on another derived number, message only) | 2026-09-29, later the same morning; 11 turns; exit 0, success |
| Inputs digest (sha256 of the session's own manifest of every input file's sha256) | `41b182f954b684dc16b049ac645bfc9aa17306e69929976d4d243f63bd5bfe15` |
| Stream digest, initial run | `420c1b598b3d0c8de45238c9531f48dce6ab96afb1926f512008c67daf857211` |
| Stream digest, resume 1 | `91d63abc2980a4035099dfbddd7423239d6f57031e49f571ecb07d5f2a152bdc` |
| Stream digest, resume 2 | `bdfa2145f1b1c299a05e3a039e9e6d3f9f4c439b5c6ae18e492e4706c835e8b8` |
| Stream digest, resume 3 | `e78c7cc7bcc52426882827bd08ddcb1298ad22ea9f4f970f69e423fcca425267` |
| Secret scan (token value / `sk-ant-` / `oat01`), all four segments | 0 / 0 / 0 |

## Session B — forty injections

| | |
|---|---|
| Session id | `59be2f5a-ae35-40fc-86dd-629d7ccda14c` |
| Model | `claude-opus-5-5` |
| Initial run | 2026-09-29, local early morning; 89 turns; exit 0, success |
| Resume (three artefacts' sourcing refusals, message only) | 2026-09-29, later the same morning; 8 turns; exit 0, success |
| Inputs digest (sha256 of the session's own manifest of every input file's sha256) | `43c46a3f57ac8bfcc40503e573c30e5a45e4b79754f6ade0fdb01f795b6ca060` |
| Stream digest, initial run | `ec646d47191565b7b4048b8b8396ec8a81b8b9fc25d64a8df83e7f13c2548871` |
| Stream digest, resume | `15ce4fe2bed48391d27b28483abd67e7be6bc084ef854dc44bd66092bd305b4f` |
| Secret scan (token value / `sk-ant-` / `oat01`), both segments | 0 / 0 / 0 |

## Design

A stand-in design, not the reference design: a self-balancing two-wheeled
robot built from a sourced parts sheet (`parts_sheet.md`, `sources.json`),
every number cited to a datasheet, a retailer page or a manufacturer's
documentation by row.
