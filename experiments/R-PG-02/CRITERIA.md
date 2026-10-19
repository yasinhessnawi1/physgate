# R-PG-02 — pre-registration

> Git-tracked and public. `ARCH-nnn` and experiment IDs only.

**Status:** to be frozen before the last practice round's result exists, naming both reviewer
configurations that round can lead to (§3), and before any tuned component judges an item of
either test set. The fresh test set is authored after this file is frozen, while that round
runs (§2). Two facts are filled in later, each in its own dated commit and before the first
review: **the pick** between the two configurations, read mechanically from the round's
practice tally by the rule in §3, and the fresh set's manifest digest, as R-PG-01 filled its
facts. Every `[FILL AT FREEZE]` and `[FILL AT PICK]` below is a fact read or measured, never a
choice, and none is adjusted to a result.
**Written:** 18.10.2026 (draft); 19.10.2026 (prepared for the freeze; the order changed so
that the fresh set is authored during the last practice round, §2).
**The numbers the owner sets:** approved by the owner on 18.10.2026, every value as suggested
(§12).
**Cites:** R-PG-01 (`experiments/R-PG-01/`). Nothing in R-PG-01 is changed, re-scored or
re-read by this experiment beyond its published counts.
**Rule:** nothing in this file may change after the first metric is produced.
- A measurement that turns out to be impossible as specified is recorded in `RESULT.md` as a
  deviation, with its reason, and the criterion is scored as failed rather than rewritten.
- An amendment is a new experiment (`R-PG-03`) that cites this one.

---

## 1. Question

After the fixes made in answer to R-PG-01, does each layer **separate injected physical errors
from correct revisions**?

- **The layers:**
  - the paired reviewers (ARCH-060), one reviewer per artefact, paired with its role;
  - a generalist reviewer: one reviewer for every role, not paired, so that pairing's value
    (ARCH-063) is measured on the same items at the same commit;
  - the physics gate (ARCH-080, ARCH-082, ARCH-083).
- **Both directions, every time:** the share of injected errors a layer rejects **for the right
  reason**, and the share of correct revisions it **accepts**. A layer that rejects everything
  scores well in one direction and fails the other.

**Why the question changed from R-PG-01's.** R-PG-01 asked whether the gate catches errors the
reviewers approved. Its published counts:
- the reviewers approved 0 of 40 injected artefacts, and refused 21 of the 23 clean twins they
  judged, so a rejection did not separate an error from correct work;
- the gate caught 17 of 40 injected artefacts and failed 0 of 40 twins;
- the kill criterion fired on both limbs.

A count in one direction cannot tell a careful layer from one that refuses everything. This
experiment measures discrimination directly.

## 2. The three sets

| Set | Role in this experiment | Injected | Clean twins | Per class | Authored |
|---|---|---|---|---|---|
| **Fresh test** | **primary** | **40** | **40** | 10 | after this file's freeze, during the last practice round, by one author pair, never seen by anyone before the run |
| **Old test** (R-PG-01's corpus) | secondary | 40 | 40 | 10 | 29.09.2026; sealed; only its published counts are known to the tuners |
| **Practice** | reported, **never a result** | 20 | 20 | 5 | before tuning; read freely by the tuners |

- **The fresh set: 40 + 40, one author pair.** It is the largest size whose 240 reviews (§3) can
  run between the criteria's approval and the demonstration, and it makes the fresh-to-old
  comparison like for like. The original plan was 80 + 80 from two independent author pairs; at
  40 + 40 one author's style can be part of the result, and §9 says so.
  - **How the pair writes 40 from a brief written for 20.** The author briefs are frozen (by
    their sha256) for twenty revisions, five errors of each class. The pair works in two batches
    of twenty, each to the frozen brief unchanged: session A writes the base and revisions 1–20,
    then, resumed with one fixed continuation message, revisions 21–40 of the same base; session
    B writes the errors of 1–20, then, resumed with one fixed continuation message, the errors of
    21–40. The two continuation messages are fixed before the authoring and published with the
    corpus, with their sha256. Each batch holds five errors of each class, so the set holds ten.
- **The practice set: 20 + 20, at most 2 calibration rounds per track.** At this size a rate
  near one half carries a 95 % interval of about ±20 points, so the practice set detects only
  large effects.
- **The order was changed, and the change is disclosed here.** The order first planned was:
  the tuning freeze, then this file's freeze, then the fresh set's authoring. To fit the 240
  reviews in before the demonstration, the fresh set is instead authored **while the reviewer
  track's last practice round runs**, after this file is frozen and before that round's result
  exists. What keeps the two apart:
  - tuning reads practice outputs only (the practice set, its reviews and its tally). Nobody
    involved in tuning opens a file of the fresh set, and the fresh set stays outside the
    repository, read before the run only by scripts that print counts, digests and bare
    check facts (R4);
  - the fresh set's authors are new sessions given the frozen briefs alone (R2): they see no
    practice output, no review and no tuning record;
  - both reviewer configurations the round can lead to are named in §3 before its result
    exists, and the stop rule picks one mechanically from the round's practice tally, so
    neither the round's result nor the fresh set can steer which one judges the test sets;
  - the gate is the same in both configurations, and the authoring step's checks (the
    loader, the gate and the source check) run at this file's freeze commit, so the fresh set
    is held to the same checks whichever configuration is picked.
- **All three sets share one input.** Each is built from the same sourced parts sheet (Pololu
  Balboa 32U4), a labelled stand-in, never the reference design. The fresh set and the practice
  set come from one author brief, frozen before the practice set was written; its differences
  from R-PG-01's brief are listed in `RESULT.md`.
- **Seeds:** practice **11** and fresh test **13**, fixed on 18.10.2026 before any tuning. The
  old set is reviewed at seed **7** (R-PG-01's), so nothing but the fixes differs from R-PG-01's
  run. A seed fixes the review ids, the interleaving and the lane assignment (§5, R8). Author
  sessions take no seed.

## 3. What is under test, and the arms

Every hash below was read at the commit it names. **The tuning-freeze commit is the picked
configuration's commit (K or F below), filled by the pick commit: K, `48929eb2f1ba0d770b02914e4a2b29a62a27e486`.** The run's
commit is the last commit that changes this directory (the manifest's dated fill); it descends
from the tuning-freeze commit, and the launch script (§11) holds it to every hash below, those
of the picked configuration included, and refuses a mismatch.

**The two reviewer configurations, both named before the last practice round's result:**

| | K, kept | F, fallback |
|---|---|---|
| What | the last practice round's rubric text promoted, with the account's fixed paragraphs | the first practice run's rubrics and template, unchanged |
| Commit | **`48929eb2f1ba0d770b02914e4a2b29a62a27e486`** | **`82cbf3b6b77de5de5d6b4d1a5a3117b7656b1480`** |
| Rubrics tree (`knowledge/reviewers/`) | **`b5d5a31e8073ec99d356f41b4086885607c2a4aa`** | **`dd203340de8cee2f42878bb09ee72e64dfe1465b`** |
| Control rubric sha256 | **`08a5cfbc1b6729843bd5f6d8cad5c3596faaeecc596fb472230905815a2677d6`** | **`18be8569a3743d6f9f5ff554ac6fd7e7c86b082ffaad4c08d0a40a00bac111f5`** |
| Electrical rubric sha256 | **`5ca8c13584ac896abda9825d52a0a3b8177866024e68249ad75375c59086b445`** | **`a1b78302cf116ce471bf24a484de24a1e98e8679256e41d5f36b3dd4f48219b3`** |
| Firmware rubric sha256 | **`614ad78c9ebceba6903fba31267801e970162d80fbf10df0713064c99377c25e`** | **`e265ef4733443d1af8a8152a8831fa97f999c3fcae0acc8f12f48fe1faed5f8a`** |
| Mechanical rubric sha256 | **`ee68896b4adce53b1e66330d1c8072e5afbac66a547d077abd4d0325ef8dadf8`** | **`3ca83fe1099481ff4c32681b7e63a594e907dd01bcd6a56a8160ed0a8e0783fa`** |
| Instrument tree (`src/physgate/evaluation/inject/`) | **`93e5c3275997eea4633e5c141fbf80a6f271a029`** | **`375e9e882bc452b75f7395e71a13c8614fee1ba2`** (the first practice run's, byte for byte) |
| The account's fixed paragraphs | sha256 **`8580efd05af6fd2d304810950f00bb2c3d462302dddfd00b1d12373e340ab838`** | none (`account_sha256` is `null` in `instrument.json`) |
| The practice result for P5 (§6) | the last practice round's run | the first practice run |

- **Identical in both:** the gate and everything it reads, the reviewers' code (with the
  verdict check below), the parameters, the runtime and the sets. The launch script holds both
  configurations to the same gate, bounds, spelling, catalogue and reviewer hashes.
- **The pick, by the stop rule fixed before the round ran:** the round is scored on the practice
  set with the same scripts and item map as the first practice run. **K is picked if the paired
  reviewers' A on the practice twins is at least 6 of 20 and their R on the practice injected
  items is at least 11 of 20; otherwise F.** Nothing else is weighed. The pick is filled in a
  dated commit, "Pick filled: <date> (K or F, with the round's two counts)", with the
  tuning-freeze commit and the launch script's `PICK`; that commit merges the picked
  configuration and changes no other value.
- **The pick: K; the round's A 7/20 and R 13/20 on the practice set.** Pick filled: 19.10.2026
  (K, with the round's two counts); the tuning-freeze commit is K's,
  `48929eb2f1ba0d770b02914e4a2b29a62a27e486`.

- **The gate:** `src/physgate/gate/`, git tree **`1e169aac5679d743d4b0585090a45bcd06ea1a63`**.
  - Its magnitude check reads two bounds tables from outside that tree:
    `knowledge/electrical/bounds.toml`, git blob **`3bbdc33b7e4ab1df2b2a32d48003fbffa876ebc0`**
    (sha256 `a5c3be61b6898b1a2408b8957c71fa3008c374f3de1c8fa56423c559c9019663`), and
    `knowledge/cross/bounds.toml`, git blob **`b68fd58f31a9469124d4accc26a8a9c6f1dde7cf`**
    (sha256 `ddb96fc7582241392eb5db407f336c8d8a37c313272c400522ec11b4218fefed`).
  - The unit-spelling module, `src/physgate/unit_spelling.py`, git blob
    **`eaa4ce697092d27545a19c87c6d92fc6f1e966fc`** (R-PG-01's, unchanged).
  - The quantity catalogue's digest is
    **`9bf73a7dfd74f49fc0b094a45df9564fdff5de129e170d06ce8d54851a841c88`**.
  - The gate now never passes a balance it did not read. A pass needs every plausible reading
    of a load to balance, and a disagreement between readings is `unchecked`, never `pass`.
- **The reviewers:** `src/physgate/reviewers/`, git tree
  **`e072e6a908535b5c42e78a30aa1ff0b95cb9ef3a`**, every role on `claude-sonnet-5`.
  - The rubrics under `knowledge/reviewers/` are the picked configuration's (the table above):
    its tree and the sha256 of each promoted rubric. Each digest is that of the file's bytes,
    which the rubric loader holds to the file's last promotion; each review line records the
    digest it judged with.
  - **The calibration rounds' outcome.** The first calibration round (the "Unwritten records"
    text, R7.9, with the account's fixed paragraphs) was **not kept** under the stop rule fixed
    before it ran. The second and last round adds one more rubric rule to it (R7.9) and is
    measured against the first practice run with the same rule; its outcome is the pick above.
    No item of any rubric was added, removed or reworded by either round; the item ids of
    §4.1's table are those of the rubrics in K and in F.
  - The generalist rubric of each role is its paired rubric with the two domain sections
    (Section 2, domain standard violations; Section 3, skill-file antipatterns) left out by code,
    every other byte the paired rubric's. Its sha256 is recorded on each generalist review line.
  - **The verdict contract is ARCH-060's as built:** a rejecting item names a rubric item, with
    no structured defect (node, quantity, requirement, observed, required), and there is no
    non-rejecting "unverified" item result. §4.1's item rule therefore applies.
- **The instrument:** `physgate inject`, `src/physgate/evaluation/inject/` at the picked
  configuration's tree (the table above). It includes:
  - the delayed retry, the parallel lanes and the lane-wide pause (§5, R8);
  - **the verdict-repair resume, adopted:** once per review, a session whose structured verdict
    was refused is resumed once, with the check's own reason in plain words; it is the same
    review, not a re-draw, and each use is counted;
  - the verdict check that refuses an empty or one-word finding or evidence as no verdict, which
    the repair resume answers;
  - **in K only,** the account every reviewer is given carries the same three fixed paragraphs
    before every item's nodes (the revision's form; the quantities the parts sheet does not
    give; the precision convention), sha256
    **`8580efd05af6fd2d304810950f00bb2c3d462302dddfd00b1d12373e340ab838`**, recorded in each
    run's `instrument.json` as `account_sha256`. In F the account is the first practice run's,
    without them;
  - the generalist mode (`--generalist`);
  - the source-consistency check (`physgate inject-sources`, §5, R4).
- **The runtime:** Claude Code **`2.1.301`**, the Linux arm64 build, sha256
  **`1e119036a802d359ba5f9886428e031586e8796f7a858d5a8ee179ac7b8604f0`**, on one ARM virtual
  machine (2 cores, 12 GB). Auth mode `subscription`. Each run records the binary's version.
  The reviewer requests' defaults on this binary are measured at launch by the instrument
  pilot's dry run (scripted endpoint, a dummy token, no model call), as R-PG-01 measured them.
- **The sets:**
  - the old set, `corpora/injected-errors/v1/`, tree `77782679f15eae4301e86516541b4a3c5c6613b0`,
    manifest sha256 `41553301d5b036f84df289ee6d8c87ecce4504d5a09969e05291e23c9ebc026a`
    (R-PG-01's, unchanged);
  - the fresh set, kept outside the repository until `RESULT.md` commits it, manifest sha256
    **`e76a4904e7b42326a85a9a9267973518e6f79b510c8f2b8b3391e8b23d37620c`** (set `fresh-v1`; facts filled: 19.10.2026, the fresh set's manifest
    digest, once the set was assembled and its precondition held (R4): 40 of 40 fresh twins with
    no failing record and no source-check mismatch, records sha256
    `f78681918bb45fc5326e7735fa1b7d0a16f42433eb37ff42c19d255cd0002621`; before its first review);
  - the practice set, outside the repository until `RESULT.md` commits it, manifest sha256
    `ddc255ab538f134c2983edfb71d29cbeba3c0dc3dd23cc01df9415120d9ddfb0`.
- **Pinned run parameters,** recorded in each run's `instrument.json` and committed as
  `params_fresh.json` and `params_old.json`, which differ in their lane count alone (R8):
  - reviewer model `claude-sonnet-5`, paired and generalist; corpus author model
    `claude-opus-5-5`;
  - effort `high`; max output tokens `64000`; token ceiling `400000`; session bounds 80 turns,
    4500 s wall clock, 0 binary retries (R-PG-01's values, so the bounds are not a difference
    between the two runs);
  - `infra_retry_delays_s` `[60, 900, 2700]`; the lane-wide pause after 3 consecutive
    infrastructure failures, for 900 s; 1 repair resume per review.

**The arms:**

| Arm | What | Fresh set | Old set | Reviews |
|---|---|---|---|---|
| **A. Paired reviewers** | one review per item by the paired reviewer of its assigned role (ARCH-060 as built) | 40 + 40 | 40 + 40 | 160 |
| **B. Generalist reviewer** | one review per item with the generalist rubric, same model, same commit, same items | 40 + 40 | not run | 80 |
| **C. Gate** | deterministic; judges fresh copies after every review of its run has ended | 40 + 40 | 40 + 40 | — |

- **Arm B runs on the fresh set only.** The pairing question is asked on the primary set; asking
  it on the old set would cost 80 reviews and answer it on a set the tuners have seen at class
  level.
- **The gate's figures** are read from arm A's run on each set. Arm B's run gates the same fresh
  items at the same commit; its records must equal arm A's byte for byte, and a difference is a
  deviation (R6).
- **Expected time and cost.** The practice baseline ran at 11.7 minutes per review on this
  machine (4 lanes, 40 reviews in 2.2 h). The three runs share 4 lanes (R8): each fresh arm runs
  80 reviews in one lane, about 15.6 hours, and the old set 80 in two lanes, about 7.8 hours, so
  the experiment's wall clock is about 16 hours plus retries. The practice baseline spent
  0.61 million tokens per review by the binary's totals, mostly cache reads, so about 150 million
  for 240 reviews. The run has no dollar cap; it is bounded by its count and each session's
  bounds. Tokens are recorded from the binary's own totals.
- **Not in this experiment, stated so they cannot be claimed later:**
  - a second-vendor reviewer. It moves to a later experiment that adds other harnesses and model
    providers together, and is never bolted onto this one;
  - a scan of an attempt's diff for reward-hacking indicators. It is outlined elsewhere and is not
    scored here.

## 4. Definitions (the unit of counting)

**The unit is the item** (an injected artefact or a clean twin), **never a gate event.** One item
counts once, whatever number of records it produces.

### 4.1 Rejected for the right reason, over the injected items (R)

- **Gate, R_gate:** the injected artefact produces at least one **failing** record that
  **intersects what the injection changes** relative to its clean patch. The changed nodes are
  computed mechanically from the two patches: every node whose payload differs between them, or
  that is in one and not the other, and, for a propagation item, both ends of the injected edge.
  A failing record intersects them when its node or its module is a changed node, when its
  details name one (a power shortfall's contributing nodes, a balance's terms, an equilibrium's
  supports, a propagation's unwritten edges), or when its message holds a changed node's id as a
  whole word.
  - A failing record elsewhere is reported as "caught, elsewhere", beside R, and is not in R.
  - **Beside it, "caught" in R-PG-01's sense** (any failing record), so the old set's figure
    compares with R-PG-01's 17 of 40.
  - An `unchecked` record is never a catch. Whether the failing check is the item's expected
    check is reported beside.
- **Reviewers, R_rev (paired and generalist): the item rule.** The verdict is a reject, **and** at
  least one rejecting item names the error. "Names" is decided mechanically, with no model
  reading a review. It keeps R-PG-01's secondary result 10 in form:
  - a review's **cited items** are those its last review line records `unmet` or `confirmed`,
    and its failing item; a review with no verdict cites nothing;
  - an item's **error items** are the cell of the table below for its error class and its
    assigned role (the role as the run's log records it), in the column of the arm's rubric;
  - **named:** the injected item's review cites one of its error items **that its twin's review
    does not cite**. An item cited in both was triggered by something the two revisions share,
    not by the error alone;
  - beside it, the same count without the twin condition (an error item cited at all).

  **The error-item table.** Every class × role cell is filled, so no injected item is unscorable
  by an empty cell. Paired column: R-PG-01's table (drawn from the rubrics' text alone, keyed by
  the expected check), regrouped by class by a fixed rule, with no item chosen anew:
  - **unit** ← R-PG-01's `units` cell; **magnitude** ← its `magnitude` cell; **propagation** ←
    its `propagation` cell;
  - **equilibrium** ← the role's `magnitude` cell together with its cells for the checks that
    judge a balance (`equilibrium`, `power`, `conservation`). An equilibrium error is a load, a
    reaction, a position or a mass that makes a balance fail, so it lives in a written number
    that its source or its neighbours contradict, or in the balance itself. The `thermal` cell is
    not a balance and is not taken.

  Generalist column: the generalist rubric holds no Section 2 or 3 item. Its only rejecting
  line for a revision with no issued specification is the role's Section 1 line "whether the
  revision is consistent with the design it changes and with this rubric", so that line is
  every cell of the role. Under the twin condition this reads: the generalist rejected the
  injected item on that line, and the twin's review did not.

  | Class | control | electrical | firmware | mechanical | generalist (every class) |
  |---|---|---|---|---|---|
  | `unit` | D25, D26 | ES-31, ES-32 | DS-27 | MS-2 | control A7; electrical EA-9; firmware AC-9; mechanical MA-10 |
  | `magnitude` | D25, D27 | ES-32 | DS-27 | MS-3 | as above |
  | `equilibrium` | D25, D27 | ES-7, ES-9, ES-32, ES-33 | DS-27 | MS-3, MS-4, MS-26 | as above |
  | `propagation` | D28 | ES-34 | DS-30 | MS-5 | as above |

  Every paired id is a Section 2 item, and every generalist id a Section 1 item, of its role's
  rubric at the digests of §3. **Its limit, stated before the run:** a reviewer that describes the
  error under an item outside its cell is not counted as naming it, so R_rev is a lower bound on
  naming. The generalist's cell cannot locate the error, so its rule is looser than the paired
  rule; this biases J_generalist upward against J_paired, the direction unfavourable to P4.

### 4.2 Accepted, over the clean twins (A)

- **Gate, A_gate:** the twin produces no failing record (`unchecked` allowed).
  - **A headroom refusal against a continuous rating** (a `current_limit` whose cited parts-sheet
    row is a continuous rating; §9) is classified by the author's cited row and scored as that
    stated limit, not as a gate false alarm. Every such twin is listed, and A_gate with it counted
    as a failure is printed beside.
- **Reviewers, A_rev:** the verdict is `pass`.
- **Sheet-flaw rejections.** The parts sheet is shared by every set and is not internally
  consistent. Its inconsistencies, as a set inherits them, are listed mechanically by the
  source-consistency check over the set's base and clean patches (never the injected ones):
  every number that is a difference of parts-sheet rows (`subtracted`) and every number whose
  cited row gives nothing of its kind (`unresolved`), each as a (node, quantity) pair at its place
  (the base, or a revision). The list for each set is computed by the frozen tool from the
  frozen set, so it is fixed now by rule, not by hand.
  - A twin rejection is a **sheet-flaw rejection** when the evidence of its **failing item** names
    a listed pair of the base or of the twin's own revision: the quantity name appears in it as a
    word, and the node id, or the part of the node id after its first dot, appears too. The match
    is mechanical, and no judgement is involved.
  - **Primary, conservative:** a sheet-flaw rejection counts as a reject in A_rev, so it lowers
    the reviewers' accept rate.
  - **Stated beside it, every time:** A_rev and J with sheet-flaw rejections removed from the twin
    denominator, and the count of sheet-flaw rejections per arm and set.
  - This tells apart a reviewer that refuses correct work from one that correctly reports a flaw
    every design built from this sheet inherits. Neither reading is chosen after the run.
  - **Beside it, for the old set:** the number of twins whose own numbers the source check finds
    differ from their cited rows (`mismatch`). The fresh set has none by construction (R4); the
    old set was never held to the check. Reported, never scored.

### 4.3 Discrimination (J)

**J_L = R_L + A_L − 1**, per layer. A layer that rejects everything has J = 0, whatever its R.
The raw reject rate over the injected items is printed beside, so that the right-reason
condition's effect is visible.

### 4.4 Reviews with no verdict, items that cannot be scored, and passes that judged nothing

Read before the run, and not adjusted after it:

- **`review_unavailable`** (no verdict after every retry and after the repair resume, whatever
  its cause, `invalid_verdict` included) and **`blocked`** (a stop on a blocking defect of the
  issued specification):
  - on an injected artefact, it is **not** a rejection for the right reason, so it lowers R;
  - on a clean twin, it is **not** an acceptance, so it lowers A.
  - It therefore counts **against the layer in both directions,** and nothing gains by not
    reaching a verdict. It is never re-drawn, and each is listed with its cause.
  - **Beside the headline,** the same figures among items with a verdict only, and the range of
    every figure if each such review had gone either way.
  - **The reading R-PG-01 stated still holds:** where a role's twins and injected artefacts end
    without a verdict at about the same rate, that says nothing about the errors.
- **"Unscored":** an item whose right reason or acceptance cannot be decided. It counts
  **against the layer in both directions**: an unscored injected artefact counts as not rejected
  for the right reason, and an unscored twin as not accepted, each in its own column, so a layer
  cannot gain by an item being unscorable. The alternative, dropping it from the denominator, is
  printed beside. With every cell of §4.1's table filled, the count is expected to be 0; any
  found is listed.
- **The gate: for every gate verdict, the evaluated count is printed beside the pass count, per
  check.** The runner still writes "found nothing wrong (0 evaluated)" at a scope where a check
  has nothing to judge (no statics quantity in scope, for example). Such a record is printed as
  **"nothing in scope"**, beside the counts, and is never counted as judged. A check that judged
  nothing while it left something `unchecked` writes no pass at all. The evaluated count holds
  judged observations only: a balance, a headroom or a discharge left `unchecked` (by a refused
  unit, or by readings that disagree) is not counted as evaluated.

## 5. Rules of fair play

- **R1 First honest version.**
  - This file's freeze precedes the fresh set's authoring, and both reviewer configurations
    it names (§3) are fixed commits before the last practice round's result exists. The gate
    does not change after this file's freeze; the reviewers, the rubrics, the verdict contract
    and the instrument are the picked configuration's, and none of them changes after the pick.
  - A defect in the instrument (not in a layer) found after a number is seen is a deviation; the
    whole affected set is re-run at the corrected commit, and both runs are reported.
- **R2 Blindness.**
  - The fresh set's authors are **new sessions** that have never seen the practice set, the gate's
    code or output, or any of the fixes: each runs in a sandbox of its own (Read, Write and Edit
    only, inside its own directory; no shell, no web, no settings or servers), proven on the
    scripted endpoint before any launch. Session B sees no gate output at all. Between the
    sessions only the base design and the clean revisions go through the gate and the source
    check, and session A is told only a failing check's name and message, or the source check's
    bare fact.
  - New rubric text is drafted by agents who have not seen R-PG-01's corpus. `RESULT.md` states who
    approved each rubric and what they had seen.
  - Reviewers see a neutral trajectory, the same template for every item, held to the blindness
    check before each review (no telltale word in any path or file name, no field name of a result
    or corpus, not the item's own id or description).
- **R3 Nothing reachable.** Before the run, a scan proves that no copy of **any** of the three
  sets, their manifests, the practice runs, the dry-run results or any answer key is readable from
  where a reviewer runs: each review root is new, outside every checkout, holds no telltale word
  (the substring "physgate" included), and neither contains nor lies inside any of them; no file a
  reviewer is shown from the library equals a file of any set, or names a set's label or manifest
  digest. A hit stops the run.
- **R4 Clean-twin conditions.**
  - **Fresh set, a precondition:** before its manifest digest is filled in, every fresh twin
    passes the gate with no failing record **and** passes the source-consistency check (every
    number copied from the parts sheet equals its row, converted only between units; every
    derived number is the arithmetic of the rows it cites, to three significant figures). A twin
    that fails either goes back to session A with the bare fact only. The launch script checks
    both again at the run's commit.
    - **Its consequence, stated now:** the gate's acceptance of the fresh twins is 40 of 40 **by
      construction**, and is **not a result.** `RESULT.md` reports instead how many twins the gate
      returned to the author, and on which check, and how many the source check returned.
  - **Old set, once:** R-PG-01's 40 twins were gated **once**, at this file's freeze (the gate
    is the same in K and F), count only:
    **40 of 40 twins with no failing record, records sha256
    `4a23d22dd255d41afa9934aba77caeb1ee8a819def1428741a5e41f1f8598d11`** (measured 19.10.2026).
    A twin that failed there was not tuned against; it is reported as found, and it is the gate's A on
    the old set. The launch script gates them again and must reproduce that count and sha256
    exactly.
  - **During tuning,** the zero-failure guard ran on the practice twins and on every clean real
    design graph available, never on a test set.
- **R5 No re-draw.** No item is replaced, re-injected or dropped after the fresh set's digest is
  filled in. Denominators: 40 per direction per set.
- **R6 One registered run per arm.** Reviewers are not deterministic, so no claim about reviewer
  variance is made. The gate is: a second pass over both sets must give byte-identical records,
  arm B's gate records on the fresh set must equal arm A's, and a difference is a deviation.
- **R7 Disclosed exposure before the freeze.** Listed in full so that `RESULT.md` carries them
  beside the primary result:
  1. **The planner of the fixes saw R-PG-01 corpus detail beyond the published counts,** through a
     private planning note: the base design's node identifiers, the injection sites of three
     artefacts (`a23`, `a29`, `a40`), and the shapes of the ten unit-class errors (the scale
     prefixes of the six the gate missed, and the dimension mismatches of the four it caught).
     - What it touched: the planner's discussion of factor-of-ten scale errors; two hand-made node
       names that coincided with base identifiers, which were renamed before any fix
       (`electrical.battery_pack` to `electrical.cell_pack`, `mechanical.chassis` to
       `mechanical.carrier`). No fix names or is shaped to any item.
     - From then on, nobody working on the fixes read the planning note, R-PG-01's result or its
       readiness material.
     - **This is one reason the fresh set is primary.**
  2. **The old set is seen at class level.** The fixes target the error kinds R-PG-01's published
     counts named (an equilibrium check that judged and passed broken balances; same-dimension
     scale errors; a magnitude table with two sourced ranges; reviewers that refused correct
     twins). The old set therefore cannot show that the fixes generalise; it is secondary.
  3. **The old twins' gate outcome, once, count only** (R4).
  4. **The gate's fixes were written against hand-made errors of each kind,** never against an
     item of any set. **Three gate relations were proposed from the practice authors' vocabulary**
     (a quantity name ending in `_mass` read as a mass; `torque_peak` against `reaction_moment` on
     one node; `supported_mass` against the masses carried), each written as a general rule with
     its own false-positive check on every clean design. The practice set is the development set,
     so learning the authors' frozen vocabulary is what it is for; the fresh set's authors use the
     same vocabulary, which may favour the gate on the fresh set.
  5. **The drafter of this file** read R-PG-01's criteria, its published counts (which name
     artefacts by outcome), the planner's own exposure statement (which lists the details in item
     1), the practice set's tuning metrics and its provenance (which names practice nodes that
     carry the parts sheet's inconsistencies). The drafter read no file of the old or fresh set,
     no review, gate record or results row of R-PG-01, and no error class or answer of any item of
     any set. §4.1's table was regrouped from R-PG-01's by the fixed rule stated there.
  6. **The practice set shares the fresh set's parts sheet and brief,** by design, so the tuners
     know the fresh set's input distribution though not its items.
  7. **The runtime differs from R-PG-01's** in its build (Linux arm64, not macOS) and machine (an
     ARM virtual machine, not the laptop).
  8. **The neutral trajectory's bias, stated before the run.** A reviewer given no trajectory has
     less evidence. If it answers "cannot verify" with a rejection, A_rev falls and the raw reject
     rate rises without raising R_rev, so **J_rev is plausibly biased downward**, the direction
     unfavourable to the reviewers. In K, the account's fixed paragraphs (the revision's form,
     the quantities the sheet does not give) are meant to reduce this; F has no such paragraphs.
  9. **The models that built and reviewed the fixes.** From the evening of 18.10.2026,
     development and review agents ran on `claude-fable-5-1` (the weekly limit on
     `claude-opus-5-5`). The first calibration round's rubric change, one policy bullet in each
     of the four rubrics ("Unwritten records": for a proposed revision, a required record the
     revision did not write is `noted`, not `unmet`), was drafted blind by a development agent on
     `claude-fable-5-1` that read only the four rubrics, the author briefs and the rule it was to
     state, and was approved and promoted by the owner. The second round's rubric rule (a
     sub-check whose input the account lists as absent from the parts sheet by construction is
     recorded as not checkable, `noted` and naming the missing input, never `blocked` or `unmet`;
     an input not so listed, and a value the revision itself writes, are judged as before) was
     drafted blind in the same way, from the four rubrics, the account's text, the author briefs
     and the rule, and approved and promoted by the owner. No evaluation session (author, reviewer
     or role) ran on `claude-fable-5-1`.
  10. **The order change** (§2): the fresh set is authored while the last practice round runs,
     and the configuration that judges it is picked afterwards, mechanically, from that round's
     practice tally. Who ran the authoring, and that no person or agent involved in tuning opened
     a file of the fresh set, is stated in `RESULT.md`.
  11. **An instrument fix before the run.** 19.10.2026, before any review: attempt 0's dry run found
      the instrument pilot's stand-in for the completeness check still taking one argument, and its
      parameters lacking fields the command now requires (the lanes, the lane-wide pause and the
      repair resumes); both fixed in the pilot script only (no pinned tree changes). This is an instrument fix before the run, not
      a deviation.
- **R8 Retries, lanes and order.** These rules read only infrastructure outcomes, never a verdict.
  - **Retry only on an infrastructure failure,** after a delay, each delay recorded on the review's
    line: `infra_retry_delays_s` = **[60, 900, 2700]**, three retries, the last about an hour after
    the first failure. In R-PG-01 one outage window ran from 14:01 to 14:51 UTC and failed every
    one of its 47 sessions; a schedule of [60, 600, 1800] waits about 41 minutes in all, which
    that window would have outlasted.
  - **A lane-wide pause:** after **3** consecutive infrastructure failures across a run's lanes,
    no lane of that run starts a new review for **15 minutes**. A review not started is not a
    failure and uses no retry. Each run counts its own failures; an outage reaches all three runs
    at once, so each pauses on its own count.
  - **Lanes: 4 in all, shared by the three runs**: one lane for each fresh-set arm, and two for
    the old set (`lanes.py` holds the rule: the two fresh arms get equal lanes, so the primary
    contrast's two arms run alike, and the old set takes the rest). Within a run, every item's
    lane is drawn by the set's seed before the run and recorded (`lanes.json`). **An injected
    artefact and its twin run on the same lane**, and classes are balanced across lanes, so a
    lane's hour affects both directions alike. Figures per lane are a secondary result.
  - **Order:** the three runs (arm A and arm B on the fresh set, arm A on the old set) run
    **concurrently**, in separate run directories and separate review roots. All three start
    within one minute of each other, and the launch script refuses to start one alone: every
    pre-flight check for all three passes before any starts, and if one stops within its first
    minute the others are stopped and the attempt is void. Every item records its wall-clock start
    and end, so the outage exposure of each arm is compared afterwards (§8). An outage therefore
    falls on all three at once, not on one; once the old set's run has ended, the two fresh arms
    still share every hour.
  - **The verdict-repair resume** (§3): once per review, when the binary's cap on refused
    structured verdicts ends the session or the verdict check refuses a verdict after it.
- **R9 The tuning record is published.** Every practice iteration, with its commit, its arms, both
  directions and its cost, so the number of attempts is visible, the round that was not kept
  included. At most 2 calibration rounds per track.

## 6. Primary results and the criteria

**Primary, on the fresh set, for each layer (paired, generalist, gate):** R (of 40), A (of 40) and
J.

- **Intervals, pre-registered here** (R-PG-01 registered none, and its intervals were post hoc):
  - R and A: Wilson 95 %;
  - J, and every difference in J: a bootstrap over **pairs** (an injected artefact with its twin),
    10,000 draws, seed **13**, the 2.5th and 97.5th percentiles. A difference between two arms on
    the same pairs resamples the pairs jointly; a difference between two sets resamples each set's
    pairs on its own.
- **The primary contrast:** paired against generalist, J_paired − J_generalist on the same 40
  pairs, with its paired bootstrap interval, and the cost ratio (tokens, and USD at the dated price
  sheet, from the binary's own totals, per item, n = 80 reviews per arm).

**The criteria** (approved 18.10.2026). "Clearly" means the interval lies wholly above zero.

| # | Criterion | Form | Reasoning |
|---|---|---|---|
| P1 | The gate accepts every correct revision | A_gate = 40/40 on the old set (the fresh set holds it by construction, R4) | The fix cycle's hard condition: the gate must not be loosened, and must not fail correct designs. |
| P2 | The gate rejects for the right reason | R_gate on the fresh set ≥ **20 of 40** | The risk table's own reasoning for its first row: "a deterministic gate catching fewer than half of those is not doing its job." Half of 40 is 20. R-PG-01's gate caught 17 of 40 in the weaker, any-record sense. |
| P3 | The paired reviewers discriminate | J_paired's 95 % interval lies wholly above 0 | R-PG-01 showed no separation at all. The minimum claim a fix can earn is that a rejection now carries information. No magnitude is set: there is no prior J to draw one from. |
| P4 | Pairing adds value | J_paired − J_generalist's 95 % interval lies wholly above 0 | A decision rule, not a magnitude. At 40 pairs the smallest difference this resolves is about 30 points; a smaller one is reported as unresolved, never as absent. |
| P5 | The fixes were not tailored | For each tuned layer (paired reviewers, gate): **tailoring** is declared if the practice-to-fresh drop in J has a 95 % interval wholly above 0; **possible tailoring** if the point drop exceeds **0.15** and the interval includes 0 | At 20 + 20 practice items a fixed point threshold alone would fire on noise. 0.15 is a judgement, and is labelled as one. |

- **P5's practice figures:** the paired reviewers' from the practice run the pick names in §3
  (the last round's run for K, the first practice run for F); the gate's from the practice set gated at the run's commit by the
  tally, so both figures come from the gate that runs on the test sets.
- **No per-class floor** is added to P2. Per class n is 10, so only large effects show, and they
  are reported (§8).
- **A reviewer change that only raises acceptance is not an improvement.** No criterion above is
  met by A alone.

## 7. The risk table's first row, and how this experiment relates to it

- **The row:** "Physics gate catches nothing the reviewers missed". Inject 40 known errors, run
  paired reviewers, then the gate. Kill criterion: *reframe the contribution if fewer than 10 of
  the errors the reviewers approved are caught by the gate, or if the reviewers approve fewer than
  4 of the 40.*
- **R-PG-01 fired it on both limbs** (A = 0 of 40, C = 0). A fired criterion is a result. It
  stands, and this experiment does not re-score, amend or reverse it. The row's thresholds are not
  changed by anything here.
- **R-PG-02 reports the row's two quantities on the fresh set** as a secondary result, beside
  R-PG-01's: A (injected artefacts the paired reviewers approved, of 40) and C (of those, the ones
  the gate caught, in R-PG-01's any-record sense). The row's thresholds are printed beside them,
  and **no verdict is drawn**: they are reported only.
- **Its reading, stated before the run:**
  - The row and this experiment pull in opposite directions. A better reviewer approves fewer
    injected errors, which lowers A and so C. A calibration that raises acceptance of correct
    twins may also raise A for reasons unrelated to the gate's value. A rising A is therefore not,
    by itself, evidence that the row's risk has passed.
  - Whether the thesis's reframing is revisited in the light of this experiment is the owner's and
    supervisor's decision, recorded outside this file.

## 8. Secondary results (reported, never scored)

1. R, A and J per class (unit, magnitude, equilibrium, propagation) and per role, for every layer.
2. The same on the old set; the old-to-fresh and practice-to-fresh differences per layer.
3. `blocked` and `review_unavailable` (with `invalid_verdict` among its causes), per role and arm,
   for injected items and twins, each with its cause; repair resumes and their outcomes; schema
   refusals per review.
4. The gate: for every verdict, evaluated and passed counts per check; passes that judged nothing
   ("nothing in scope"); **equilibrium passes made on forces alone, counted apart from positioned
   passes,** from the check record's tool line; `unchecked` records per class; "caught,
   elsewhere"; the expected-check share; headroom refusals classified by their cited row (§4.2).
5. The R-PG-01-sense figures on both sets (any failing record; approved; named against caught,
   by R-PG-01's own table keyed by the expected check), so the two experiments line up.
6. The fresh set's pre-run record: twins returned by the gate (with the check) and by the source
   check (R4); the number of `current_limit` values whose cited row is a continuous rating.
7. Per-lane figures, retries and their delays, lane pauses, and each run's wall-clock span.
8. Cost per arm: tokens of all four classes and USD at the dated price sheet (cache writes at the
   one-hour rate the binary writes on the subscription; a list-price equivalent, not a bill); the
   paired-to-generalist ratio per item.
9. The row's A and C on the fresh set (§7).
10. Sheet-flaw rejections per arm and set, and A_rev and J without them (§4.2).

## 9. Known limits (stated before the run)

- **The base design is a stand-in,** and all three sets share its parts sheet. Nothing here
  generalises beyond this design class. The quantities the sheet does not give are absent from
  every set, and no error can involve them.
- **One author pair writes the fresh set,** in two batches of twenty, so one author's style can be
  part of the primary result.
- **The unit check judges dimension and sign, not scale.** A same-dimension scale error is caught
  only where a relation reaches the quantity (a mass sum, a carrier's supported mass, a torque
  against its reaction moment, a current headroom, a discharge rating, a power or heat budget).
- **The magnitude check's bounds tables hold one sourced range** (an inertial sensor's
  `sample_rate`, 0.78 Hz to 32 kHz) **and no class envelope.** The catalogue's relations number
  nine (power budget, supply covered, source rating, current headroom, discharge rate, mass sum,
  energy balance, heat budget, junction limit), beside the equilibrium check's carrier and
  torque-unit readings. A magnitude error on any other kind is caught only where one of these
  reaches it.
- **The magnitude check holds no product-class envelope** (no mass, length, voltage or
  temperature bound across domains). Such envelopes would be a product-class assumption, not
  physics, and they would refuse correct designs.
- **The electrical `sample_rate` range spans six IMU makers' output rates.** It is wider than
  before the fixes, a sourced loosening that turned some former failures into passes, and it is
  applied to every electrical node, including ADCs and codecs, where it is too narrow.
- **A statically indeterminate mount's load split is not verified;** a planar mount model is not
  part of the fixes.
- **The equilibrium check's forces-only path (a structure with reactions and no positions) has no
  moment row.** A dummy pair of reactions (for example +200 N and −200 N, or a heavy massless
  support beside matching ballast) can hide a reaction error there and still pass. Forces-only
  passes are counted apart from positioned passes (§8).
- **Readings that disagree give `unchecked`.** A reaction whose negated reading balances; a
  `reaction_force` with no known axis, which is not read as vertical; a sub-assembly that balances
  as carried and fails as not carried, or the reverse. On a structure with three or more equal
  reactions, the "one reaction left out" reading can explain some ordinary errors (one leg
  doubled, or a fourth leg added without re-splitting the load), which then give `unchecked`, not
  fail. On the positioned path, an inconsistency between a support's weight and its load is
  flagged, never loosened.
- **`current_limit` is read as a driver's peak rating** (the catalogue's definition). The authors'
  frozen vocabulary does not define it, so an author may write a continuous rating, which makes
  the headroom check stricter than intended. Any headroom refusal against a continuous-rating
  `current_limit` is classified by the author's cited row and scored as this stated limit, not as
  a gate false alarm (§4.2). Paralleled drivers (one motor constraining two drivers) are judged
  against each driver alone, which can refuse a correct design. A `current_limit` two hops from
  the motor (on a regulator behind the driver) forms no relation.
- **The discharge relation's bound is the fastest store class:** an electric double-layer
  capacitor's 10,910 per hour, from the smallest confirmed time constant (ESR × C) in a maker's
  catalogue. It refuses only the absurd; a node declares no chemistry, so no tighter class bound
  applies.
- **The carrier and torque-unit readings** (`supported_mass`, `torque_peak` against
  `reaction_moment`) treat a `constrains` edge as possibly "is carried by". Unequal splits, subsets
  and gear ratios give `unchecked`. A cantilevered motor's weight moment, a reaction written as a
  rated capacity, and two motors on one node are not read. For a carrier named by two or more
  parts, a declared mass equal to any subset's sum (± its own mass) is `unchecked`; above 16 parts
  the carrier is `unchecked`; the catch is concentrated on single-part carriers and sums that match
  no subset.
- **A geared torque unit is only ever failed or `unchecked`,** never passed, because its readings
  disagree by the gear ratio. The torque row's pass count is read accordingly.
- **Names with an inferred kind** (a closed list of suffixes with one meaning each: `_voltage`,
  `_mass`, `_force`, `_torque`, `_frequency`, `_diameter`, `_radius`, `_thickness`) give
  `unchecked` when their unit does not convert. They are never failed on the suffix alone.
- **A quantity name the catalogue lacks is `unchecked` by the gate.** Write-time refusal sits in
  the design-state store and refuses only near-spellings of a relation's quantity name, which
  injected artefacts never pass through. A quantity written under a different, meaningful name
  (for example `motor_current` in place of `stall_current`) escapes every relation and is recorded
  `unchecked`; the count of such names is reported per set. A suffix such as `_a`, `_x` or `_1` on
  a relation's name (a dual driver's two channels) is refused at write time as a near-spelling.
- **A propagation edge into a node that does not exist is `unchecked`.**
- **The generalist's right reason cannot locate the error** (§4.1): its only rejecting line is
  the role's consistency line, so its R is read under a looser rule than the paired R.
- **At 40 per direction,** a difference of about 30 points between two layers is the smallest this
  resolves; per class (n = 10) only large effects show.

## 10. What is published

`RESULT.md` cites the commit of every component in §3 and gives the secondary results beside the
primary ones. It also contains: the results rows (one per item and arm); the `physgate catches`
output over each run directory, which must equal the rows' totals; the practice corpus and the
tuning record (R9), committed under `experiments/R-PG-02/practice/`; the fresh corpus, with its
authors' records and the two continuation messages; every exposure of R7 beside the headline; and
the rubric approver's exposure statement.

## 11. The scripts committed with this file

Committed in the freeze commit, under `experiments/R-PG-02/`, each tested at the run's commit on
the instrument's own test corpus, never on a set of this experiment. They run explicitly
(`uv run pytest -q experiments/R-PG-02/`), as R-PG-01's did.

| Script | What it does |
|---|---|
| `launch.sh` | The pre-flight refusals of R-PG-01's script (the run's commit, a clean tree, every tree, blob and digest of §3, the picked configuration's among both that §3 names, and a refusal while the pick is unfilled, the binary's sha256 and version, the parameters files against the instrument's schema), the lane split (`lanes.py`), R3 over all three sets and the practice copies with the reviewer's read allowance on the pinned binary, the reviewer requests' defaults by the dry run, the fresh twins' precondition and the old twins' check (R4), and only then the three runs together. Its scans count with the shared helper `scripts/experiment/scan.sh`, so a scan that finds nothing does not end it under `pipefail`. |
| `params_fresh.json`, `params_old.json` | §3's parameters; they differ in `lanes` alone. |
| `lanes.py` | R8: the lane split of the budget across the three runs, held to the parameters files; each run's seeded lane plan (a pair on one lane; classes balanced), printed as counts and a digest before the run, and held to the run's `lanes.json` and review records after it. |
| `r3_scan.py` | R3 over all three sets, the practice copies and runs, and the three review roots. |
| `twins_old.py` | The old twins' gate check: a count out of 40 and the records' sha256, nothing else. |
| `twins_fresh.py` | The fresh twins' precondition: 40 of 40 with no failing record, and no source-check mismatch. Counts only. |
| `tally.py` | §4's R, A and J per layer and set, the unscored and no-verdict columns and the ranges, the sheet-flaw count and the figures without it, the gate's evaluated counts beside its passes with "nothing in scope" and forces-only passes apart, the intervals and the bootstrap, P1–P5, every §8 figure, and §7's A and C. It holds the error-item table verbatim. |
| `read_catches.py` | `physgate catches` over each run directory, held to the rows. |
| `regate.py` | R6: a second gate pass over a set into a fresh directory; byte-identical or a deviation. |
| `rpg02_fixture.py` | The tests' own set (the instrument's test design, every number sourced to a small parts sheet) and their scripted stand-in reviewers; never a set of this experiment. |
| `test_*.py` | Each script on the instrument's test corpus or an empty directory: the tally's rules on built logs, the table equal to this file's and every id an item of its section, the lane rule and plan, the scan on an empty root and on a hit, the twins checks, the regate and the catches reader on a real run of the test corpus with stand-in reviewers, and the launch script's refusals before any run, under `set -euo pipefail`. |

## 12. The numbers the owner set (approved 18.10.2026)

| # | Number | Value | Where |
|---|---|---|---|
| 1 | Fresh test size | 40 + 40, one author pair | §2 |
| 2 | Practice size, rounds | 20 + 20, ≤ 2 rounds per track | §2, R9 |
| 3 | Old set's seed | 7 | §2 |
| 4 | Session bounds | R-PG-01's (80 turns, 4500 s, 0 binary retries) | §3 |
| 5 | Generalist on the old set | no | §3 |
| 6 | "Unscored" in the headline | counted against the layer, in both directions | §4.4 |
| 7 | `infra_retry_delays_s` | [60, 900, 2700] | R8 |
| 8 | Lane pause | 3 consecutive failures → 15 min | R8 |
| 9 | Lanes | 4 | R8 |
| 10 | Bootstrap seed | 13 | §6 |
| 11 | P1–P5's forms and values | as the table in §6 | §6 |
| 12 | The row's A and C | reported only | §7 |
