# `physgate.evaluation` — instruments

Apparatus for measuring the system. An instrument writes files an experiment
reads; it reports no number of its own. Each experiment's criteria, frozen
before it runs, say what the files are counted as.

## `inject/` — the injected-error instrument (risk row 1, ARCH-083)

Known physical errors, each injected into an otherwise valid revision of a base
design, run past a paired reviewer alone and blind, then past the gate. The
experiment reads how many the gate caught after a reviewer had approved them.

| | |
|---|---|
| `corpus.py` | The format. A corpus directory holds `base.json` (the shared base design, a label and whole node payloads), `sources.json` (the parts sheet, by row: each row that is one number with its unit and URL), `artefacts/<id>.json` (each: a clean patch and an injected patch, both whole node payloads; the class, exactly one of `unit`, `magnitude`, `equilibrium`, `propagation`; the check expected to catch it; a description in physics terms; for a propagation error, its one edge), documentation as `*.md`, and `MANIFEST.json` (every other file's digest, the label, and the model string the corpus was written on). It loads only as its manifest lists it, byte for byte; a changed, added or removed file is another corpus. There is no menu of injection operations: the two patches differ, and the difference is the error. Every quantity's source is a URL; `derived: <arithmetic>` whose every operand is a cited row of the corpus's parts sheet (`sources.json`, `[R1.03]`), with whole-number powers the only other numbers, the rows resolved and the arithmetic checked against the quantity's unit under the gate's pint registry (in the base and the clean patches; in an injected patch only the citations, since the error may sit in that quantity); or `design: <reason>`, only for a quantity on the closed list of design choices (`sample_rate`, `loop_gain`). A property of a bought part is never a choice. Every string in every node is held to a list of telltale words (`inject`, `mistake`, "magnitude error", …). `require_complete` asks for ten of each class and ten distinct propagation edges, each joining two domains |
| `materialise.py` | One patch made real: the base written through the real store (its head is the baseline, the given design, which owes nothing), then the patch as one change set above it, committed in a git worktree with fixed author, date and message, so the same patch gives the same commit. Beside it, a neutral account of the revision, one template for every artefact: where the design is, and the patch's nodes in full. `require_blind` refuses to show a reviewer any of it, paths included, if it holds a telltale word, a gate result's or the corpus's field name, or the artefact's own id or description |
| `runner.py` | `run_instrument`. Refuses to start without a reviewer for every artefact's role, or with one on the corpus author's model string (ARCH-060), or with run, scratch and corpus directories that are used or inside one another. Then **every review first**, each on its own copy, removed once its verdict is written, before the gate runs on anything; then the gate on a fresh copy of each injected artefact, one call at all three scopes in `observe`, with the patch as the one change set; then each clean patch as a control, in a log of its own. Artefacts run under an id derived from the seed and the corpus id, so the log shows neither the corpus id nor the class order. Writes `instrument.json` (whose digest the log's start line carries), `events.jsonl`, `controls/events.jsonl` and `results.jsonl`: one row per artefact, no total. `check_base` gates the base alone, as one change over nothing. With `review_clean_twins` (off unless asked for, recorded either way) each clean twin is reviewed too, in the same blind phase under an id of its own, into the controls log |
| `cli.py` | `physgate inject --corpus --run-dir --scratch --run-id --seed [--review-clean-twins]`: a complete corpus, with the reviewers the command is registered with |

The run's log is an ordinary run-event log, so `physgate gate-events` and
`physgate catches` read it like any run: each gate event is stamped from the
review that came before it on the same artefact. The loop's replay would refuse
it (a review before a gate), and it is never resumed; a killed run is started
again into new directories.

## Ships dark

- **The reviewers.** None is registered with the `physgate` command, so
  `physgate inject` refuses to start, naming the first role without one. The
  instrument's own tests run a labelled fake. A reviewer registered where the
  loop's are lights it up with no change here. A reviewer that runs as a
  session must be installed with the corpus and the run directory as answer
  keys (`--answer-key`), so it can read neither.
- **The trajectory.** An injected artefact comes from no role session, so the
  reviewer reads the neutral account in its place, not a session's stream.
