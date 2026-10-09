# `physgate.evaluation.observe`: every number with its provenance

This package reads run directories and says what a run was made from, what it
did, what it cost, whether a rerun reproduced it, and how much repeated runs
vary (ARCH-145, ARCH-150). It writes into no run. The one file it writes is a
cost trend, which belongs to no single run.

**Every number the commands print carries the manifest id of the run it came
from.** The id is the sha256 of the run's `run.json` as written. Each reader
holds it to the digest on the run's first event line, so a number never names a
configuration the run did not start under.

## What it owns

| | |
|---|---|
| `manifest.py` | `read_manifest(run_dir)` → `RunManifest`: the resolved configuration, the request fields the pinned binary sends that no setting pins (thinking, context management, beta list, measured per version), the served catalog and flags the decomposition call observed, the policy-limits digest, the machine each driving process recorded, and every artefact by content hash. The artefacts are the brief, the specification commit and tree, each merged attempt's commit and merge with their trees, the run branch's head and tree, the journal's digest and head revision, the store's last commit and tree, each trajectory's seal, and the installation manifests. A commit git cannot find is an error, never a blank |
| `trace.py` | `read_traces(run_dir)` → `RunTrace`: per stage of each attempt, when it began and how long it took; per session, how it ended, its tokens, whether any were partial, and its wall clock from the spawn line to its end line. That wall clock **includes the orchestrator's setup for the session**. It also gives decomposition, reviewer and routing tokens, and every gate check through the gate's own reader. Derived from the log, never written beside it |
| `cost.py` | `load_price_sheet(date)`, `price_run(run_dir, sheet)` → `CostLine`, `append_cost_line(trend, line)`, `append_ratio_line(trend, line)`, `read_trend_lines(trend)`, `read_trend(trend)`. See *Cost* below |
| `ratio.py` | `Ratio`, `ReviewCost`, `RatioLine`: the ratio and its trend line |
| `sequence.py` | What a rerun compares: the normalisation, the exact records, the decision sequence, `first_divergence`, and `level_of`. See *Reproduction* below |
| `rerun.py` | `rerun(recorded, …)` makes the run again through `physgate decompose` and `physgate run`, and `compare_runs(a, b)` → `Comparison` |
| `variance.py` | Ordering and merge-decision variance (definitions in the module docstring): `measure_variance(run_dirs)` over recorded runs, and `repeat_run(recorded, n=…)` to make the repeats as reruns |
| `compare.py` | `compare(baseline, candidate)` → `SideBySide`, refused across drifted pins: a model string, the effort level, the output-token limit, the binary version, the endpoint |
| `cli.py` | The commands below |
| `prices/` | The dated price sheets, one JSON file per date, never edited |
| `exceptions.py` | The domain exceptions, each with a context mapping |

## Commands

```
physgate manifest --run-dir R
physgate trace    --run-dir R
physgate cost     --run-dir R --prices 2026-09-27 [--append TREND]
physgate rerun    R --brief B --run-id NEW --run-dir NEWDIR --target T --install I
physgate variance --runs R1 R2 …
physgate variance --repeat R -n N --brief B --target T --install I --runs-dir D
physgate compare  BASELINE CANDIDATE
```

Output is JSON on standard output. A refusal, or a record that does not hold,
prints `{"error": …, <context>}` on standard error and exits 2. `rerun` prints
the comparison with `reproduced`, the `rule` that judged it and the `first`
divergence that decided, and exits 1 when the rerun did not reproduce the run.

## Reproduction

The binary exposes no seed and no temperature. So what "reproduces" means is
set by what is controllable, at two levels, chosen from the recorded endpoint.

- **Exact**, when a scripted endpoint on this machine (a loopback address)
  answered the run, or nothing did.
  - These must match: the configuration, every event line field by field, the
    ledger, the queue and its decisions, the graph journal raw, and every tree
    on the run's branches and in its store.
  - Normalisation comes first, and it is exactly the list measured between two
    runs of one brief and seed:
    - *mapped:* the run id, the run directory, session ids (by order of first
      appearance), and commit ids (to their trees);
    - *dropped:* `ts`, the `seconds` of a worktree removal and of the
      installation check, a token line's `message_id` and a review's usage
      `message_id`s, a proposal check's
      scratch `graph_root`, trajectory seals, and the first line's
      configuration digest.
- **Decisions**, for a real model. Only the decision sequence is scored: each
  planned subtask; per attempt the gate verdict and failing check (or why it was
  skipped), the review verdict, and how the attempt ended; the integration gate;
  and a halt.
  - The exact records are still compared and reported, as measured differences.
  - The prompt itself differs between reruns: the binary's own context carries
    the branch, a short commit id and the date.

- **Exact up to a resume**, at the exact level, when either run's log holds a
  `resumed` line: a second process took that run over. The two logs cannot match
  line for line, since only one holds what the resume wrote.
  - These must match exactly: the ledger, the queue and its decisions, the
    graph journal, every git tree, and the decision sequence.
  - The event log must match exactly up to the first `resumed` line, and its
    first divergence, if any, must be that line. Anything that parts earlier fails.

A divergence names its record, its position, the event line it stands for, the
first differing field, and the subtask, attempt and stage. A comparison says
which rule judged it (`exact`, `exact_to_resume` or `decisions`).

A rerun is refused, before anything runs, when any of these differs from what the
run recorded: the brief, the harness checkout, the target's head, the endpoint,
or the binary's version. It is also refused when it would reuse the recorded
run id.

## Cost

- **Price sheets.** A sheet names the page its prices were read from, when, and
  that page's digest; the same for its USD to NOK rate. Prices are in USD per
  million tokens, per token class. Cache writes are priced at the five-minute
  rate, since the binary marks its cache breakpoints ephemeral with no time to
  live.
- **A price change is a new dated sheet**, with its digest added to
  `KNOWN_SHEETS`. It is never an edit: an edited sheet does not load.
- **Pricing a token.** It is priced at the model that spent it. A model the
  sheet does not price is refused, never priced at zero.
- **The auth mode.** A line's `basis` is `list_price` on an API key. On the
  subscription it is `list_price_estimate`: the subscription is not billed per
  token, and the line's own schema ties the basis to the auth mode.
- **The trend file** is JSON Lines. A line is a run's `CostLine`, or the
  paired-versus-generalist `RatioLine` (`ratio.py`, `kind: "review_ratio"`). Each
  has one writer: `physgate cost --append` for a run's cost, and
  `physgate ratio --baseline <baseline.json> --append` for a ratio, read from an
  existing generalist review and held to the records beside it (its
  `generalist.json` and its own review line), with no model call. There is one
  reader, `read_trend_lines`; `read_trend` is its cost lines. The reader refuses:
  - a line cut short, or one that is neither line;
  - a ratio line whose ratios are not its two reviews' figures;
  - a sheet date cited with a second digest;
  - a run, or a ratio, repeated at one sheet's prices.

  The trend file lives outside every run directory, so the hooks' run-directory
  protection does not cover it. Each line can be recomputed from its run's own
  event log.

## Formats and their one reader each

For any consumer, a user interface included: read through these, never
the files.

| Format | Model | Reader |
|---|---|---|
| a run's manifest | `RunManifest` | `manifest.read_manifest` |
| a run's traces | `RunTrace` | `trace.read_traces` |
| a price sheet | `PriceSheet` in `DatedSheet` | `cost.load_price_sheet` |
| a cost line and the trend | `CostLine`, `RatioLine` | `cost.price_run`, `cost.read_trend_lines` |
| the paired-versus-generalist ratio | `Ratio` in `RatioLine` | `generalist.ratio_line_from` |
| a rerun's comparison | `Comparison` | `rerun.compare_runs` |
| variance over runs | `VarianceReport` | `variance.measure_variance` |
| two runs side by side | `SideBySide` | `compare.compare` |

## What it deliberately does not own

- **How a run is made.** `rerun` and `repeat_run` go through the orchestrator's
  own commands. The observability layer never drives a loop itself.
- **What the gate checks mean.** Per-check records are read through
  `gate_events`, the gate records' one reader.
- **A model changing behind an unchanged string.** `compare` refuses a changed
  string, a changed effort level or output-token limit, a changed binary version
  and a changed endpoint, and reports a changed gate mode, auth mode or harness. It cannot see a
  provider serving a different model under the same string.
