# R-PG-01 — pre-registration

> **Draft, not frozen.** This text awaits approval. It is frozen by the commit that removes this
> note and fills `⟨RUN_COMMIT⟩` and `⟨FREEZE_DATE⟩`; until then nothing here is binding.

**Status:** frozen before any artefact of the corpus was reviewed by a real reviewer. Gate
exposure before the freeze (every injected artefact was gated in the mechanical dry run, and
the unit class while the corpus was assembled) is disclosed in R7.
**Written:** 29.09.2026
**Facts filled:** 16.10.2026 (the component commits and the runtime in §2; dated disclosures
under §4 R4 and R7); 17.10.2026 (the re-pins in §2 at `3750496`, R4 at that commit, R8);
⟨FREEZE_DATE⟩ (the run's commit). No threshold, definition or rule was changed by any fill.
**Added 17.10.2026, before any review of this corpus:** secondary result 10 (§6), reported and
never scored.
**Rule:** nothing in this file may change after the first metric is produced.
- A measurement that turns out to be impossible as specified is recorded in `RESULT.md` as a
  deviation, with its reason, and the criterion is scored as failed rather than rewritten.
- An amendment is a new experiment (`R-PG-02`) that cites this one.

---

## 1. Question

Does the physics gate (ARCH-080, ARCH-082, ARCH-083) catch physical errors that paired
reviewers on a different model (ARCH-060) approved?

This feeds the pre-registered risk table's row "Physics gate catches nothing the reviewers missed":

> *Inject 40 known errors, ten each of unit, magnitude, equilibrium and propagation, into
> otherwise valid artefacts. Run paired reviewers alone, then the gate.* Kill criterion:
> *Reframe the contribution if fewer than 10 of the errors the reviewers approved are caught by
> the gate, or if the reviewers approve fewer than 4 of the 40.*

The thresholds (10 caught; 4 approved) are the risk table's. They are not set here, and nothing
in this experiment changes them.

## 2. What is under test

All component commits below are on `master`; the run's commit is **`⟨RUN_COMMIT⟩`**. Every hash
below was read at `3750496`; the launch script (§9) holds the run's commit to each of them.

- **The gate:** `src/physgate/gate/` with git tree hash
  **`29e7c8061e4f5e54b815afd41bf98f9e6455a7c3`**, last changed at `f2048da`.
  - Its magnitude check reads its bounds table from outside that tree:
    `knowledge/electrical/bounds.toml`, git blob **`cdeb9736d93362120f8f08f0244ab449b7bd5f90`**
    (sha256 `b75d14d541243108d02f0afc1414a8cd61493f694325c9c2e4f09e30cfa27071`), pinned here
    with the tree.
  - Checks 1 and 2 hold every unit to a bounded spelling before the unit registry reads it
    (named units with small integer powers, at most 64 characters), from a module outside the
    tree: `src/physgate/unit_spelling.py`, git blob
    **`eaa4ce697092d27545a19c87c6d92fc6f1e966fc`**, pinned with the tree.
  - The quantity catalogue's digest is
    `171b054b61f703fee2aaf750b4ff107754bbf0726882e18531cb92db0028d69f`.
  - **Provenance.** The corpus was assembled and this file drafted against tree
    `03f71cd606226514c792831d05181f65c5e61dfd`, unchanged since `7291058`, after check 7
    (`check_propagation.py`, ARCH-082) landed. Commit `363eace` then moved the bounds table out
    of the gate's directory, with its ranges unchanged (tree `0bb76313…`). The unit-spelling
    guard was then added to the gate's parser (commit `3ed87e8`, tree `29e7c806…`, on `master`
    at `f2048da`). Both changes and their effect on the clean twins are disclosed under §4, R4
    and R7.
  - The run's launch script (§9) checks, before the instrument starts, that the `gate/` tree,
    the bounds file and the spelling module at the run's commit have these hashes, so a merge
    that changes the gate refuses to run, and one that doesn't passes.
- **The reviewers:** the paired reviewers of ARCH-060 at commit **`⟨RUN_COMMIT⟩`**
  (`src/physgate/reviewers/` tree **`7df979eecb5b9acba572c5687747ea33586a87e1`**, last changed at
  `1c5e988`), every role's on `claude-sonnet-5`.
  - **One review per artefact, by the paired reviewer of the artefact's role.** ARCH-060 pairs a
    reviewer with the producing role; it does not put two reviewers on one artefact. The pair's
    verdict on an artefact (§3) is that one review's verdict.
  - The reviewers' rubrics are committed before anyone who writes them has read the corpus
    (§4, R2).
  - The rubrics are those promoted under `knowledge/reviewers/` (tree
    **`dd203340de8cee2f42878bb09ee72e64dfe1465b`**, last changed at `bd14da5`):
    - control sha256 `18be8569a3743d6f9f5ff554ac6fd7e7c86b082ffaad4c08d0a40a00bac111f5`;
    - electrical sha256 `a1b78302cf116ce471bf24a484de24a1e98e8679256e41d5f36b3dd4f48219b3`;
    - firmware sha256 `e265ef4733443d1af8a8152a8831fa97f999c3fcae0acc8f12f48fe1faed5f8a`;
    - mechanical sha256 `3ca83fe1099481ff4c32681b7e63a594e907dd01bcd6a56a8160ed0a8e0783fa`.

    Each digest is the sha256 of the file's bytes, which the rubric loader holds to the file's
    last promotion. Each review line records the digest it judged with.
  - The control and firmware reviewers were validated on real design runs. The electrical and
    mechanical reviewers are **newly promoted and not validated by real design runs**; the
    instrument pilot (§4, R8) is their first real use through this instrument.
  - A reviewer session has two tools: Read, and the structured verdict.
- **The corpus:** `corpora/injected-errors/v1/` at sha256
  **`41553301d5b036f84df289ee6d8c87ecce4504d5a09969e05291e23c9ebc026a`**, commit **`dd7e042`**. It
  has been on `master` since `647875c`, and its tree (`77782679f15eae4301e86516541b4a3c5c6613b0`)
  is unchanged through `⟨RUN_COMMIT⟩`.
  - It holds 40 artefacts, ten per class, and each has a clean twin.
  - Two fresh sessions on `claude-opus-5-5` (the implementers' model, per the evaluation pins)
    wrote it, working blind to the gate's code and output: session A wrote the base design and
    the clean patches, and session B wrote the injections.
  - The base design is **a labelled stand-in** built from a sourced parts sheet (Pololu Balboa
    32U4), not the reference design.
- **The instrument:** `physgate inject` as at commit **`⟨RUN_COMMIT⟩`**
  (`src/physgate/evaluation/inject/` tree **`af7ead4ac5579c86b6e19ffe7a02991ac9872eca`**, last
  changed at `f2048da`).
  - It records a review that came to no verdict as `review_unavailable`, with its cause, and a
    review that stopped on a blocking defect of the issued specification as `blocked`. Neither
    is a pass.
  - **It retries a review once when, and only when, the review ended for an infrastructure
    failure.** A review that ends without a verdict for any other cause is not retried. A
    reviewer session takes no seed.
  - Every review, of an artefact or of a clean twin, is given the corpus's parts sheet
    (`sources.json`, sha256 `bc1e5ec15c6f1df823f5a39207b0656b6a2b388eca4d3414db007b4d7999ca91`,
    the digest the manifest holds) byte for byte as a file of its worktree, in the given
    design's commit, so a source that cites one of its rows can be checked. The account of the
    revision names it in the same words for every artefact. The gate's copies hold no sheet.
  - The gate judges fresh copies made in the run directory, outside the review root, after
    every review has ended; a reviewer session's processes are stopped after every end.
- **The runtime:** Claude Code **`2.1.301`**, macOS build, sha256
  **`1f04c69e1c24e4d0a716a863af0aad8fc64d49a499334c29701f073700276b99`** (the file the pilot, R8,
  ran); auth mode `subscription`.
  - The binary's sha256 is checked by the launch script (§9) and a mismatch is refused. The
    instrument itself records the binary's version in `instrument.json`.
  - **The reviewer requests' defaults on this version are measured at launch.** Before the first
    review, the launch script runs the instrument pilot's dry run (scripted endpoint, a dummy
    token, no model call) on this binary at the run's commit, and records every request's fields
    and beta header in the run's directory. `RESULT.md` reports them.
- **The machine:** a macOS laptop, on the binary above. A reviewer session has no shell (Read and
  the verdict only), so the operating-system sandbox that wraps a role session's shell takes no
  part in this run.
- **Expected cost and time:** about **$71 and about 11 hours**, run serially: the pilot's (R8)
  mean of $0.89 and 8.0 minutes per review, times 80 reviews (40 artefacts, 40 twins). The real
  artefacts' larger design graphs may raise both. The run has no dollar cap. It is bounded by
  its count (80 sessions, at most one retry each, for an infrastructure failure only) and by each
  session's bounds below.
- **Pinned run parameters, recorded in the manifest:**
  - reviewer model `claude-sonnet-5` for every role; corpus author model `claude-opus-5-5`;
  - effort `high`; max output tokens `64000`; token ceiling `400000`;
  - session bounds: 80 turns, 4500 s wall clock, 0 binary retries;
  - clean twins reviewed in the same blind phase (`--review-clean-twins`);
  - seed **`7`**, fixed on 29.09.2026, before the reviewers were built, so it could not be
    picked after seeing anything about them.

## 3. Definitions (the unit of counting)

**The unit is the injected artefact, never a gate event.** One artefact can produce records at
several scopes; it counts once.

- **Approved (A):** the pair's verdict on the injected artefact is approved.
  - A review that ends for an infrastructure failure is retried once (§2).
  - If it produces no verdict (an infrastructure failure again, or any other cause), the
    artefact is counted as **not approved** and listed. It is never re-drawn.
- **Caught (C):** the injected artefact produces at least one failing record from the gate, at
  any scope. The clean-twin precondition (§4, R4) guarantees the twin produces none.
  - An `unchecked` record is **not** a catch.
  - A catch on a check other than the class's expected one still counts as a catch, and is
    reported separately.
- **Headline:** C among A. That is, the injected artefacts that the reviewers approved and the
  gate caught. This is ARCH-083's quantity: gate events with `reviewer_had_passed: true` and a
  failing record, counted by distinct artefact.

## 4. Rules of fair play

- **R1 First honest version.** Neither the gate, the instrument nor the corpus changes after
  this file is committed.
  - A defect in the instrument (not the gate) found after a number is seen is recorded as a
    deviation.
  - The whole run is then repeated at the corrected commit, and both runs are reported.
- **R2 Blindness.**
  - The corpus authors never saw the gate's code or output. Session B never saw any gate result.
  - Whoever writes the reviewers' rubric has not read the corpus. The rubric is committed before
    its authors could. `RESULT.md` states who approved the rubrics and whether they had seen the
    corpus or a gate outcome on it.
  - Reviewers see a neutral trajectory, the same template for every artefact. This is a stated
    deviation from ARCH-060's full trajectory: injected artefacts have no real trajectory.
    **Its direction is stated in advance:** a reviewer given less than the full trajectory has
    less to object to, which plausibly means more approvals, so A and C are biased **upward**,
    the direction favourable to the headline. `RESULT.md` names this beside the headline; the
    gate-observe ablation, which reviews full trajectories, is its counterpart.
  - What a reviewer is shown (its paths, every file name it is listed, every file and the
    account) is held to the blindness check before its review: no telltale word (a file name
    read with its words split at case, digits and separators as well), no gate-result or
    corpus field name, and not the artefact's own id or description. Every file name must be
    one the instrument writes (the design's journal, a node file named for a valid node id, the
    parts sheet); any other is refused. Measured 17.10.2026 at `988679f`, counts only: all 80
    review worktrees (each artefact's two patches, with the parts sheet) pass, and the parts
    sheet passes against every artefact's answers (0 of 40 refused).
  - The error-item table of secondary result 10 (§6) was drawn from the four rubrics' text
    alone, by a drafter who had read no artefact, answer or error class of the corpus.
- **R3 Nothing reachable.** Before the run, a scan proves that no copy of the corpus, its
  manifest, the dry-run results or any answer key is readable from where a reviewer runs. A hit
  stops the run.
- **R4 Clean-twin precondition.** Before this file is committed, every one of the 40 clean twins
  has passed the gate with no failing record (`unchecked` records allowed). The measured count
  is written here as **40/40**. A corpus that fails this is not frozen.
  - **Re-measured 16.10.2026 at `4a28f4f` (gate tree `0bb76313…`): 40/40,** records byte-identical
    to those at `7291058` (gate tree `03f71cd…`), records sha256
    `ea3d581a027abd3538c3aa5271f169ca8ddc2d868e5f7fe104739ef1ccb8e75c`.
  - **Re-measured 17.10.2026 with the unit-spelling guard** (commit `3ed87e8`, gate tree
    `29e7c8061e4f5e54b815afd41bf98f9e6455a7c3`): **40/40**, the full gate records byte-identical
    to the same twins' records at `5b49709` (gate tree `0bb76313…`) and identical across two
    passes, records sha256 `ea3d581a…` again. Only the 40 clean twins were gated.
  - **Re-measured 17.10.2026 at `3750496`** (gate tree `29e7c806…`, bounds blob `cdeb9736…`,
    spelling blob `eaa4ce69…`, the hashes pinned in §2), on a clean clone: **40/40**, records
    sha256 `ea3d581a027abd3538c3aa5271f169ca8ddc2d868e5f7fe104739ef1ccb8e75c`, byte-identical
    across two passes and equal to every measure above. Only the 40 clean twins were gated.
  - **At the run's commit,** the launch script (§9) gates the 40 clean twins alone once more
    before the first review; any count other than 40/40, or any other records sha256, stops the
    run.
- **R5 A miss is not re-drawn.** No artefact is replaced, re-injected or dropped after this file
  is committed. The denominator is 40.
- **R6 One registered run.** Reviewers are not deterministic, so no claim about reviewer variance
  is made from this run. The gate is deterministic: a second gate pass over the same corpus must
  give byte-identical records, and a difference is a deviation.
- **R7 Disclosed pre-freeze observation.** While the corpus was assembled, a citation refusal in
  the loader required checking whether a fix to three injected artefacts had accidentally
  removed their intended errors. That check ran all ten `unit`-class injected artefacts through
  the real gate and read the per-artefact pass/fail outcome, before this file was committed.
  **This is disclosed, not hidden:** the orchestrator and implementer therefore knew, before
  freeze, which of the 10 unit-class artefacts the current gate catches and which it does not.
  This information produced §7's stated coverage limit (a stated, never-scored secondary result
  per §6) and touched nothing else: the kill criterion (§5), the denominator (40, all classes),
  and every other class's catch data were not observed and are not shaped by this. No threshold
  in this file was chosen, adjusted, or could have been adjusted by what was seen, since §5's
  criterion existed unchanged before the corpus was assembled. Stated here so the eventual
  `RESULT.md` carries this alongside the primary result, rather than a reader discovering it
  independently.
  - **Extended (29.09.2026):** the mechanical dry run (fake reviewer, no live call, twice, for
    R1/R6's determinism check) necessarily produced a full `gate_verdict` per artefact across all
    four classes, and confirmed the production log-reading tools (`gate_events()`, `catches()`)
    run over it without error. No catch/miss count from this was recorded or reported as a
    result, per this file's own rule that the dry run reports no count — but the orchestrator
    and implementer were exposed to the complete picture in the course of checking it, not just
    the unit class. Same conclusion as above: §5's threshold predates this and is not shaped by
    it.
  - **Extended 16.10.2026: the gate changed after the corpus froze.** Commit `363eace`
    (01.10.2026) moved the magnitude bounds table from `src/physgate/gate/bounds/electrical.toml`
    to `knowledge/electrical/bounds.toml` and changed the loader to read it there.
    - The two ranges, their bounds, units, classes and sources are unchanged. Only a comment and
      the table's `curated_by` note differ. Besides the loader (`bounds_table.py`) and the
      directory's README, no file under `gate/` changed, and the catalogue digest is the same at
      both trees.
    - The one gate run since the dry run is the R4 re-measure above. It gated the clean twins
      alone, so no catch or miss on any injected artefact was observed at the new tree.
  - **Extended 17.10.2026: the gate's unit parser gained a cost bound.** Checks 1 and 2 now refuse
    a unit that is not spelt as named units with small integer powers before the unit registry
    reads it (a twelve-character exponent tower had stalled a process until a CPU limit killed
    it).
    - On the 40 clean twins the records are byte-identical (R4). **No injected artefact was gated
      at the new tree.** An injected artefact whose unit the registry read but the spelling
      refuses would now fail check 1 with the spelling's reason rather than pint's, or fail it
      where it passed before; whether any does was not observed and is not known.
    - The guard was a stated prerequisite of this freeze, specified on 16.10.2026 before the
      change was made and before any of its effects could be seen.
    - Also changed on 17.10.2026, in the instrument, before any real review: every review is given
      the parts sheet (§2), and the blindness check reads file names split at case and digits and
      admits only the names the instrument writes (R2). Neither touches the gate's input.
  - **Extended 17.10.2026, at `3750496`:** the R4 re-measure there gated the clean twins alone.
    No injected artefact has been gated at any tree since the dry run of 29.09.2026, and no
    artefact of this corpus has been reviewed by a real reviewer. Secondary result 10 (§6) was
    added after the instrument pilot (R8), on the pilot's practice corpus alone, showed that a
    rejection did not tell an injected artefact from its clean twin. It is reported and never
    scored, and no threshold, definition or the denominator moved with it.
- **R8 Instrument pilot, before the freeze.** Real reviewers ran through `physgate inject`, on
  the pinned binary (2.1.301, macOS build, the sha256 of §2), with these run parameters and seed
  7, over the instrument's **four-role test corpus** (one artefact per role with its clean twin;
  never this corpus), on **17.10.2026** at **`1c5e988`**, whose gate tree, bounds blob, spelling
  blob, reviewers tree, rubrics tree (all four digests) and instrument tree equal those of §2. It
  is instrument validation, reported as such and never as a result.
  - **Verdict forms observed:** `fail` only. All 8 reviews (4 artefacts, 4 twins) rejected; no
    `pass`.
  - **`blocked` and `review_unavailable`:** 0 and 0 for every role, for the artefacts and for the
    twins.
  - **The parts sheet:** read in 8 of 8 reviews (counted by the Read calls on it, so a lower
    bound).
  - **Tokens and cost:** $7.09 for the 8 reviews, the binary's own figure, equal to the tokens
    priced at the dated sheet; a mean of $0.89 per review ($0.45 to $1.25); 16 to 20 turns and a
    peak context of 85k to 140k tokens per session; 65 minutes of wall clock, the reviews run one
    after another (a mean of 8.0 minutes each).
  - **What the reviews turned on:** each injected review also carried every class of rejecting
    item its clean twin's review carried, so on this corpus a rejection did not separate an
    injected artefact from its twin. The twins were rejected for completeness duties the rubrics
    owe for a written value (control, firmware) and for numbers the practice corpus wrote that
    differ from their own parts-sheet rows (electrical, mechanical). Secondary result 10's rule,
    applied to the pilot after its table was drawn up, gives 3 of 4 named.

## 5. Primary result and the kill criterion

- **A** = injected artefacts approved by the reviewers (of 40).
- **C** = of those A, the ones caught by the gate.
- **The kill criterion fires if C < 10 or A < 4**, as stated in the risk table. Read literally,
  if A < 10, then C < 10 and the criterion fires. That reading is recorded here and is not
  adjusted after the result.
- A fired criterion is a result: the thesis reframes the contribution, as the risk table says.

## 6. Secondary results (reported, never scored)

1. A and C per class (unit, magnitude, equilibrium, propagation).
2. For caught artefacts, whether the failing check is the class's expected check.
3. `unchecked` records per class, and the artefacts whose error the gate could not judge. Their
   coverage limits are listed in §7.
4. The propagation class's edges, listed by domain pair, so that a concentration (for example,
   most edges ending in the control loop) stays visible.
5. The gate's catches among artefacts the reviewers **rejected**, so the gate's total detection
   is visible beside the headline.
6. Gate events and records, beside the artefact counts.
7. The reviewers' verdicts on the 40 clean twins, reviewed in the same blind phase and
   interleaved under their own seeded ids, reported as the rate of correct work refused.
8. **A and C per role** (control, electrical, firmware, mechanical), beside the per-class table.
   The electrical and mechanical reviewers are labelled newly promoted (§2).
9. **`blocked` and `review_unavailable`, counted per role, for the injected artefacts and for
   the clean twins**, each listed with its cause.
   - **Its reading, stated before the run:** a `blocked` or `review_unavailable` review is not an
     approval, so it lowers A (§3), and the kill reading of §5 is not changed by this count.
     Where a role's clean twins are blocked (or come to no verdict) at about the same rate as
     its injected artefacts, the reviewer could not judge the revision at all: that is a
     property of the stand-in design and the instrument's input, and it is **not** evidence
     that the reviewer caught the error. Only where the twins are judged (pass or fail) and
     the injected artefacts are not, or the reverse, does the difference say anything about
     the injected errors. `RESULT.md` sets this count beside A and beside secondary result 7.
10. **Named against caught.** For each injected artefact: whether its review **named the
    planted error**, against whether the gate **caught** it (§3's caught, whatever the review's
    verdict). Tabulated per class and per role as counts of: named and caught; named, not
    caught; caught, not named; neither; and, in a fifth column, artefacts with no error item.
    Listed per artefact with the items that decided it. It is decided mechanically, from item
    ids the run's log records, and no language model reads a review to decide it.
    - **Cited items.** A review cites an item when its `review_ran` line in the run's log records
      that item with the result `unmet` or `confirmed`, or names it as the failing item. Where a
      review was retried, its last `review_ran` line is read. A review with no `review_ran` line
      (`review_unavailable`) cites nothing.
    - **Error items.** An artefact's error items are the cell of the table below for its
      assigned role (as the run's log records it) and its expected check (as its result row
      records it). They are the items of that role's promoted rubric (the digests of §2) whose
      own text states the rule that check enforces. Section 1 lines, which restate other items,
      and Section 4 indicators are never error items.
    - **Named.** An artefact is named when its review cites at least one of its error items
      **that its clean twin's review does not cite**. An item cited in both reviews was triggered
      by something the two revisions share, not by the error alone. A twin's review with no
      `review_ran` line cites nothing.
    - **Beside it,** the same count without the twin condition (an error item cited at all), so
      the effect of the condition is visible.
    - **No error item.** An artefact whose cell is empty is reported in its own column, never
      as named and never as missed.
    - **Its limit, stated before the run:** a reviewer that describes the error in words under
      an item outside its cell is not counted as naming it, so the count is a lower bound on
      naming. The per-artefact list shows every item each review and its twin's review cited.
    - **Its reading, stated before the run:** "caught, not named" counts the artefacts whose
      error the gate caught and the reviewer did not name. That is §1's question asked without
      depending on approval. It does not enter A, C or the kill reading (§5), and it has no
      threshold.

    | Expected check | control | electrical | firmware | mechanical |
    |---|---|---|---|---|
    | `units` | D25, D26 | ES-31, ES-32 | DS-27 | MS-2 |
    | `magnitude` | D25, D27 | ES-32 | DS-27 | MS-3 |
    | `equilibrium` | — | — | — | MS-4 |
    | `power` | — | ES-7, ES-33 | — | — |
    | `conservation` | — | ES-7, ES-9, ES-33 | — | MS-3, MS-26 |
    | `thermal` | — | ES-19, ES-20, ES-35 | — | — |
    | `propagation` | D28 | ES-34 | DS-30 | MS-5 |

    Every id in the table is a Section 2 item of its role's rubric at the digests of §2.

## 7. Known coverage limits (stated before the run)

- **The magnitude check's bounds table holds two sourced ranges.** A magnitude error on any
  other kind is `unchecked`.
- **Current headroom is not judged.**
- **A statically indeterminate mount's load split is not verified.** Only the resultant balance
  is checked; the load split is recorded as unchecked, needing FEA.
- **The base design is a stand-in.** The quantities its parts sheet could not source are absent
  from it, and no error can involve them.
- **The unit check cannot judge a same-dimension scale error.** It validates a quantity's
  dimension and sign, never the scale a number is written at. An error that keeps the right
  dimension but the wrong prefix or multiplier (a value in millinewton-metres labelled as
  newton-metres, in millimetres labelled as metres, in milliamps labelled as amps, and so on) is
  dimensionally valid either way and produces no failing record. Measured on this corpus: **6 of
  the 10 unit-class artefacts are this shape** and are `unchecked`, never caught, regardless of
  the gate's behaviour; the other 4 are genuine dimension mismatches (a period where a frequency
  belongs, a gain given the wrong unit, an energy written as a power, a current unit on a power
  quantity) and are caught. This bound was not set here; it follows from what the check tests
  for, stated so the unit class's ceiling is known before the run.
- **A propagation edge into a node that does not exist is `unchecked`, not caught.** Nothing
  checks that a `constrains` target exists when the edge is written, and check 7 records an edge
  whose target is missing from the design as `unchecked`. If an injected propagation error takes
  this shape, it is not caught. No count is given: stating one would mean reading the corpus.

## 8. What is published

`RESULT.md` cites the commit of every component in §2 and gives the secondary results beside the
primary ones. It also contains the results file (one row per artefact) and the
`physgate catches --run-dir` output over the run directory, which must equal the rows' totals.
It names the direction of the neutral-trajectory bias (R2) beside the headline, the R8
pilot's findings as instrument validation, the reviewer requests' defaults measured at launch
(§2), and secondary result 10's per-artefact list: the artefact, its class, role and expected
check, its error items, the items its review and its twin's review cited, named or not, and
caught or not.

## 9. The scripts committed with this file

Committed in the freeze commit, under `experiments/R-PG-01/`, so the launch checks and the
analysis are pre-registered with the criteria. Each is the version tested on the instrument's
test corpus at the run's commit; none has been run on this corpus's injected artefacts.

| Script | What it does |
|---|---|
| `launch.sh` | The pre-flight refusals, then the run. Checks the run's commit, a clean tree, the gate tree, the bounds blob and the spelling blob, the instrument and reviewer trees, the rubric tree and the four rubric digests, the corpus manifest's sha256 and the binary's sha256 against §2, and records them. It then measures the reviewer requests' defaults by the dry run (§2) and gates the 40 clean twins alone (R4), and only then starts `physgate inject` with §2's parameters. Any mismatch stops it before any review runs. |
| `params.json` | The reviewers' parameters file of §2, validated against the instrument's schema. |
| `r3_scan.py` | R3: the review root holds no giveaway word, is new and outside every checkout; the corpus, run, install and checkout are kept apart from it; no library file a reviewer is shown equals a corpus file or names the corpus's label or manifest digest. Exits non-zero on any hit. |
| `tally_rows.py` | The rows to A, C and the kill reading (§3, §5), and every §6 figure: per class, per role, the expected-check share, catches among rejected artefacts, the controls' gate verdicts (expected 0 failures by R4), the twins' review outcomes, `blocked` and `review_unavailable` per role for artefacts and twins, each listed with its cause, and secondary result 10 by its rule, reading both logs' `review_ran` lines and holding the error-item table of §6 verbatim. |
| `read_catches.py` | `physgate catches --run-dir` over the run directory and its controls, held to the rows: `caught_after_reviewer_passed` must equal C. |
| `regate_r6.py` | R6: a second gate pass over the same corpus into a fresh directory; the records must be byte-identical. |
| `r4_twins.py` | R4, called by `launch.sh`: gates the 40 clean twins alone, never an injected patch, and prints counts and the records' sha256 only. Exits non-zero unless 40/40 with the records sha256 of R4. |
| `test_tally_rows.py` | The tests of `tally_rows.py`: its error-item table equals §6's, every id in it is a Section 2 item of the rubric at §2's digest, the rule on small built logs, and the rule on the pilot's (R8) run directory. |

The R3 checks of the reviewer's read allowance run the hook layer's integration tests on the
binary their harness pins, 2.1.301, as the macOS build of §2 (sha256 `1f04c69e…`), not on
another.
