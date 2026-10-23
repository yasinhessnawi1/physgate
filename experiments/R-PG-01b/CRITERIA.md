# R-PG-01b — pre-registration: R-PG-01's reviewer side, re-run with the complete parts sheet

> Git-tracked and public. `ARCH-nnn` and experiment IDs only.

**Status:** frozen and committed before any code of this experiment exists (the backport, arm F's
corpus, the scripts). The facts below cannot be known at the freeze. Each stays a marked
placeholder until a later dated commit on `master` fills it, before the first review:
- arm F's corpus manifest, its label and its digest (§2.5): `[FILL at "sheet filled"]`. They are
  filled by the **"sheet filled"** commit, which follows the "sheet" commit that adds the corpus.
- the run commit and its instrument tree (§2.4): `[FILL at "run commit filled"]`. They are filled
  by the **"run commit filled"** commit, which follows the tagging and push of the run branch.

Those two commits change nothing else in this file: no rule, definition, threshold, seed or other
value. The run branch carries this file as frozen, placeholders included (L2); the filled copy is
`master`'s.

Two facts are recorded at launch, in the run's records and not in this file: the slot draw (§2.6),
and the account label with the token's digest prefix (§11). Every `[FILL]` is a fact, never a
choice.
**Written:** 23.10.2026 (draft), revised the same day after an adversarial review. The drafter has
read R-PG-01's `CRITERIA.md` and none of its results (§8).
**The numbers the owner sets:** approved by the owner on 23.10.2026, every value as proposed, except
that the weekly allowance gate was removed: the owner set no weekly cap on the run account (§11,
§15).
**Cites:** R-PG-01 (`experiments/R-PG-01/`), its pre-registration and its frozen scripts. Nothing of
R-PG-01 is changed or re-scored. Its numbers stay as published, with the dated preface of PR #68.
**Excluded until the last step (§8):** R-PG-01's `RESULT.md` and run directory, and every file that
quotes them.
**Rule:** nothing in this file may change after the first metric is produced.
- A measurement that turns out to be impossible as specified is recorded in `RESULT.md` as a
  deviation (§12). The reading it feeds is **not taken**, and the criterion is never rewritten.
- An amendment is a new experiment (`R-PG-01c`) that cites this one.

---

## 1. Question

**How much of the physics gate's advantage over the paired reviewers in R-PG-01 came from the
reviewers' incomplete parts sheet?**

- **What the reviewers saw.** In R-PG-01 every review was given the corpus's `sources.json` as its
  parts sheet.
  - In it, 62 of 163 rows have no value: every row whose value in the authors' table is a range, a
    list, a min/typ/max triple or a text.
  - No row carries the authors' notes, although 130 rows have one.
  - The authors wrote the corpus against the full table, `parts_sheet.md`.
  - The gate never reads the sheet, so the sheet touched the reviewer side only.
- **Its direction on the headline is not known in advance.** The test is two-sided.
  - A planted error whose check needs a missing row could not be verified. That plausibly raises
    approvals of injected artefacts, and with them the gate's added catches (C).
  - A reviewer may reject a revision because the sheet gives no value. That lowers approvals, and C
    with them.
  - On the clean twins, a missing value can mainly add refusals of correct work. A note's limit can
    also add a new ground for refusal.
- **What it is not:**
  - a new test of the gate, whose inputs and pins are R-PG-01's and whose verdicts are
    deterministic;
  - a change to R-PG-01's numbers or kill reading.

## 2. Design

### 2.1 Arms, rounds and pairing

**Two reviewer arms, identical in everything but the parts sheet.**
- **Arm I (incomplete), the replication.** R-PG-01's corpus as frozen. Its reviewers see what
  R-PG-01's saw, byte for byte (L5).
- **Arm F (full sheet).** The same base and the same 40 artefacts and 40 clean twins, byte for byte,
  with the complete sheet of §2.5.

**Two rounds (R = 2).**
- In each round the two arms run at the same time, as two `physgate inject` processes started
  together. They share the machine, the account, the binary and the pins.
- Each arm runs serially, one review at a time, as R-PG-01 did.
- Round 2 starts after round 1 has ended, into new directories.

**Pairing.**
- Review ids derive from the seed and the artefact id alone. So seed 7 gives every artefact the same
  id and the same place in the order in every run, and the two arms of a round review the same
  artefact at about the same time.
- The unit of every contrast is the **(artefact, round) pair**: one review in arm F against one in
  arm I.

**Why this separates the sheet from noise.**
- Reviewers are not deterministic. If the sheet has no effect, arm F and arm I are exchangeable on
  each artefact within a round, so a disagreement is as likely in one direction as the other.
- A sheet effect shows as an imbalance of disagreements (§5.4).
- The two rounds also give a direct noise floor: how often an arm disagrees with itself between
  rounds (§5.3 item 9).
- One round would be too weak to show a plausible effect (§5.6).

**As in R-PG-01:** no generalist arm, no lanes and no OS layer (§2.3).

### 2.2 What is held to R-PG-01

The launch script checks every row below (L3 and L4).

| Component | Pin (R-PG-01 §2) |
|---|---|
| Gate | `src/physgate/gate/` tree `29e7c8061e4f5e54b815afd41bf98f9e6455a7c3`; bounds blob `cdeb9736d93362120f8f08f0244ab449b7bd5f90`; spelling blob `eaa4ce697092d27545a19c87c6d92fc6f1e966fc`; catalogue digest `171b054b61f703fee2aaf750b4ff107754bbf0726882e18531cb92db0028d69f` |
| Reviewers | `src/physgate/reviewers/` tree `7df979eecb5b9acba572c5687747ea33586a87e1`. One review per artefact, by the paired reviewer of its role (ARCH-060). A session has Read and the verdict only. |
| Rubrics | `knowledge/reviewers/` tree `dd203340de8cee2f42878bb09ee72e64dfe1465b`: control `18be8569a3743d6f9f5ff554ac6fd7e7c86b082ffaad4c08d0a40a00bac111f5`, electrical `a1b78302cf116ce471bf24a484de24a1e98e8679256e41d5f36b3dd4f48219b3`, firmware `e265ef4733443d1af8a8152a8831fa97f999c3fcae0acc8f12f48fe1faed5f8a`, mechanical `3ca83fe1099481ff4c32681b7e63a594e907dd01bcd6a56a8160ed0a8e0783fa` |
| Runtime | Claude Code `2.1.301`, the version R-PG-01 pinned; auth `subscription`. The build is Oracle's Linux aarch64 build at `~/pinned/claude-2.1.301`, sha256 `1e119036a802d359ba5f9886428e031586e8796f7a858d5a8ee179ac7b8604f0` (verified read-only on 23.10.2026). It is not R-PG-01's macOS build, `1f04c69e1c24e4d0a716a863af0aad8fc64d49a499334c29701f073700276b99` (§2.3). The reviewer requests' defaults are measured at launch by R-PG-01's dry run (L9). |
| Run parameters | R-PG-01's `experiments/R-PG-01/params.json`, blob `f32da7e47303ee168cc9671edb2a8b40e72b024e`, unchanged: `claude-sonnet-5` for every role, effort `high`, max output tokens `64000`, token ceiling `400000`, 80 turns, 4500 s, 0 binary retries. |
| The invocation | R-PG-01's, as its `launch.sh` runs it, with only the macOS keep-awake wrapper dropped (§2.6) |
| Arm I's corpus | `corpora/injected-errors/v1/`, manifest `41553301d5b036f84df289ee6d8c87ecce4504d5a09969e05291e23c9ebc026a`, `sources.json` `bc1e5ec15c6f1df823f5a39207b0656b6a2b388eca4d3414db007b4d7999ca91` |
| The rest of the repository | R-PG-01's run commit `8bc03fc`, with its dependencies from its `uv.lock`, except the paths of §2.4 |
| Scoring | R-PG-01 §3, §5 and §6, by its frozen scripts, run unchanged on each run directory: `tally_rows.py` `0f138e7fa353e545cfab749ce73c7ca2e063f0f4`, `read_catches.py` `d311b76e7492f81a54cba5e51dccdbc103505fad`, `regate_r6.py` `39c33c98e0f6da328383020d14cbcbe1d08b44b3`, `r4_twins.py` `a30afd3d4fecb742085c6d5d569710a528a1f58a`, `r3_scan.py` `dfcddf2c34da27337cd956b9548c0d0c3aa706e8` |

### 2.3 What differs from R-PG-01, and why

| # | Difference | Why | How its effect is bounded |
|---|---|---|---|
| 1 | Arm F's parts sheet, and the account sentence that names it | The treatment | — |
| 2 | The instrument tree: R-PG-01's `af7ead4ac5579c86b6e19ffe7a02991ac9872eca` plus the sheet-format backport (§2.4) | R-PG-01's format allows one number or nothing per row and no other field, so it cannot load the complete sheet | It acts only on a sheet that gives values. Arm I's packets are checked byte-identical to R-PG-01's (L5). |
| 3 | Arm F's corpus has its own manifest digest | The sheet is part of the corpus and is held to its manifest | Base and artefacts are byte-identical (L4) |
| 4 | One word of row R6.05's note ("answered" becomes "responded") | The word holds a telltale ("answer"), and the blindness check of R-PG-01 R2, unchanged, refuses every packet that carries it | Disclosed with before-and-after digests (§2.5) |
| 5 | The account: Oracle's run account, whose token is in `~/.config/physgate-run.env` there | R-PG-01's account and machine are not used for this run | Both arms share it. Each launch records its label and the token's digest prefix (§11); R-PG-01's is compared at the last step. |
| 6 | The date, and the model served behind `claude-sonnet-5` | Time | Arm I measures it against R-PG-01, at the last step (§8) |
| 7 | Two review sessions at once on the account, one per arm | Same-time pairing | Each arm still runs serially; the usage-limit watcher and the void rules of §11 and §12 cover it |
| 8 | Two rounds instead of one | A noise floor, and power (§5.6) | Each round is a complete R-PG-01 run, scored as one |
| 9 | The run commit is on a branch, not on `master` | `master` has moved on: at `31b90aa` its gate tree, bounds blob, reviewers tree, rubrics tree and instrument tree all differ from R-PG-01's pins | The branch is R-PG-01's commit plus §2.4's paths alone (L2) |
| 10 | Run ids and review roots of the form `rpb-<k>`, where R-PG-01's were `rp1-<N>` | Fresh directories are a rule of the instrument | The same form for both arms (§2.6); an R3 scan per run |
| 11 | One real non-evaluation smoke review before each round, on the instrument's pilot design (L10) | It guards the whole read of arm F's sheet (§2.5) | It is never a review of this corpus |
| 12 | The machine and the binary's build: Oracle's ARM Linux VM and the Linux build of 2.1.301 (`1e119036…`), where R-PG-01 ran the macOS build (`1f04c69e…`) on the laptop. The launch wrapper is `setsid nohup` instead of `caffeinate`. | The laptop cannot hold a 24 to 28 h run unattended, and the server needs no keep-awake | Both arms run on the same machine and build, so the I-against-F contrast is untouched. The difference bears only on the comparison with R-PG-01 (§8), where it is named. The machine, its operating system and git are recorded at launch. |
| 13 | Every rejection is read for its reason (§6), and the reads of the sheet are counted (§5.5) | Added analyses | They change no metric of R-PG-01 |
| 14 | The void rules for infrastructure cascades, crashes and cut reads (§12) | Two concurrent sessions, and the whole-read guard | Stricter than R-PG-01's; decided from causes and counts alone, before any verdict is read |

**Not a difference: the OS layer.**
- R-PG-01's reviewer sessions had no shell, and the operating-system sandbox took no part.
- Since PR #65, `physgate run` refuses role sessions where the OS layer is absent. That rule is not
  reached by `physgate inject`: checked on `31b90aa`, the inject command builds no run configuration
  and calls no OS-layer refusal. It is not in the run commit in any case.
- R-PG-01b runs without the OS layer, as R-PG-01 did.

### 2.4 The run commit

**The branch.** `exp/r-pg-01b-run` starts from R-PG-01's run commit `8bc03fc`. It is tagged
`r-pg-01b-run`, pushed, and never merged.

**`git diff --name-only 8bc03fc <run commit>` may list only these paths (L2):**
- `src/physgate/evaluation/inject/corpus.py`, with these definitions taken verbatim from
  `31b90aa`:
  - a sheet row may carry `given` (its value as the authors wrote it) and `note`;
  - a sheet may carry `remarks`;
  - a sheet that gives values gives one on every row that has no number;
  - `read_sheet` and `gives_values`.
- `src/physgate/evaluation/inject/materialise.py`:
  - the account sentences `ACCOUNT_SHEET_GIVEN` (sha256
    `09f545b2df9d39fe8c27784768d58d5dfa71a243c2fa5808996ed8a0718fe439`) and `ACCOUNT_SHEET_REMARKS`,
    verbatim from `31b90aa` and chosen from the sheet;
  - `import hashlib`, for their digests;
  - a sheet of numbers alone keeps R-PG-01's sentence (sha256
    `4adba41d2ba10410d8fa734013dcfa305c0918190e0757cb54ab6f3fc625c9c9`, the same at `8bc03fc` and
    at `31b90aa`);
  - the account's form, absences and precision paragraphs, added on `master` after R-PG-01, are
    **not** backported.
- `tests/unit/evaluation/test_a_sheet_row_gives_its_value_as_written_and_its_note.py`, adapted from
  `31b90aa` to the backport.
- `tests/unit/evaluation/test_every_review_is_given_the_parts_sheet_its_numbers_cite.py`: R-PG-01's
  file plus PR #69's added cases, adapted. PR #69's account-form test is not taken, since its
  paragraphs are not backported.
- `corpora/injected-errors/v1-fullsheet/**`: arm F's corpus (§2.5), every blob equal to `master`'s
  at the "sheet" commit.
- `experiments/R-PG-01b/**`, except `sheet/`: this file and the scripts of §14, every blob equal to
  `master`'s at the "scripts" commit.

**`experiments/R-PG-01b/sheet/`**, the edited table copy, lives on `master` only. The "sheet"
commit adds it, and the run branch does not carry it. Its digests are in §2.5.

**Facts for the run commit:**
- **Instrument tree at the run commit:** `dcb84fdbcc036de47e3f8aa96afc5b789ae1dd42`. **Run commit:**
  `dfa1b53b6eb8f27bdaeae6ce0610c34bd09b2029`. Both are filled by the dated "run commit filled" commit on `master`, after
  the run branch is tagged and pushed; that commit changes nothing else in this file.
- **Measured on 23.10.2026 with the same backport in a scratch copy of `8bc03fc`** (nothing
  committed; counts and digests only):
  - the three sentence digests equal `31b90aa`'s;
  - arm I's 80 packets are byte-identical under R-PG-01's code and under the backport (digest over
    files, account and commits `3822f66a…`);
  - arm F's 80 packets pass the blindness check, 0 refused;
  - at the materialised level, arm F's packets differ from arm I's only in `parts_sheet.json`, the
    account, and the two commit ids.

### 2.5 The complete sheet (arm F)

**The source.** The corpus's own `parts_sheet.md`, sha256
`29f9568ce8465112ef0b0b164f05f3ba76f9702e3ccbc7a1dea96fbc3d057b3f` (30,998 bytes). It is the table
the authors wrote against, and the same file R-LAW-01 shows its coders.

**The one edit (R6.05).**
- The only cell of the table that holds a telltale word is row R6.05's note. It is a source caveat
  ending "…monolithicpower.com **answered** with a client challenge from two networks on
  27.09.2026".
- The converter is given a copy of the table in which that word reads "**responded**". Nothing else
  changes.

| What | Before | After |
|---|---|---|
| The table | `29f9568ce8465112ef0b0b164f05f3ba76f9702e3ccbc7a1dea96fbc3d057b3f` | `0573ef044ebdcee9ff184eec2789e1a10b31fef6f32947735f9005ea8b0daedc` (one line differs; 30,999 bytes) |
| Row R6.05's table line | `e2a58b268972a03fbd710be37df6ce3992209f336c03238efd3c405089bb0368` | `9976c090b279fa6d74c3a49dac455bed9d25cea40d3a3d59adc49a26b39e13de` |
| Row R6.05's note | `7aa9c88bbf959fb64e136e8abe9e6007e6d4faf365d7eb1f1671d85820612af2` | `46a0698bb1dc51349623245a2f01a4af34995b21e5b1147d6f6e7e119d16c56d` |

**No prose is carried.**
- The table has 9 lines of prose beside its rows, and a check of them found two problems:
  - line 1 states that the design is a stand-in, and names a reference solution;
  - line 5 frames the sheet as a kit chosen for an exercise.
- The other seven are conventions and source keys.
- The conversion therefore drops all nine (`--prose drop`). Arm F's sheet carries the table's cells
  and notes only, as R-PG-01's sheet carried cells only.

**The conversion.** `scripts/parts_sheet_sources.py` at `31b90aa`, with `--keep-values-from
corpora/injected-errors/v1/sources.json --prose drop`.
- Keep mode holds every field of R-PG-01's sheet byte for byte: every number, unit, address and the
  label.
- It adds only `given` and `note`, and refuses rather than change anything else.

**Arm F's sheet, as measured:**

| Measure | Result |
|---|---|
| sha256 | `2efbb6a8ab889ceac54d8ebdba15c8530274d8524c9eaf6181d22abf5ccbef90` |
| Size | 40,095 bytes, 1,224 lines (R-PG-01's sheet: 27,438 bytes, 983 lines) |
| Rows | 163 |
| Rows with a number | 101, every one R-PG-01's, unchanged |
| Rows with `given` | 111: the 62 rows R-PG-01's sheet left without a value, and 49 where the table writes the number in another spelling or with its unit |
| Rows with neither | 0 |
| Notes | 130 |
| Remarks | none |
| Account sentence | `ACCOUNT_SHEET_GIVEN` |

**Arm F's corpus** is `corpora/injected-errors/v1-fullsheet/`, on `master` and on the run branch.
- `base.json`, `artefacts/*.json`, `README.md` and `parts_sheet.md` (the unedited table) are copied
  byte for byte from `v1`.
- `sources.json` is the converted sheet.
- `MANIFEST.json` is new: format 1, author model `claude-opus-5-5`, label `injected-errors
  v1-fullsheet: v1's base design and 40 artefacts, byte for byte, with the complete parts sheet
  converted from the authors' table`.
- Its manifest digest is
  `8c9ceb11ffe91afd28b79dd1d206507b463bb1bf8bb8bb8f33a0a27b84e3ba57`.
- Both are filled by the dated "sheet filled" commit on `master`, after the "sheet" commit; that
  commit changes nothing else in this file.
- The "sheet" commit on `master` adds this corpus, and the edited table copy in
  `experiments/R-PG-01b/sheet/`, outside the corpus (§2.4).

**The sheet is read whole, at a measured margin.**
- **How the binary reads a large file.** Measured on 23.10.2026 against a scripted endpoint, with no
  model call, on R-PG-01's hook rig and the macOS build of 2.1.301. The Linux build is the same
  version.
  - The binary counts a Read's numbered text through the service.
  - Up to 25,000 tokens it returns the file whole.
  - Above 25,000 it returns a shortened text and **adds no notice**: the file was whole at a count
    of 25,000 and cut at 25,001.
- **What a real session got.** One real reviewer session on macOS (the smoke of §10) read arm F's
  sheet with no offset or limit. It got all 1,225 numbered lines, last row included.
  - Its size, from the context growth across that Read turn: 81,709 to 104,655 tokens, less the
    turn's 168 output tokens, is about **22,778 tokens, about 91 % of the limit**.
  - The count is fixed for fixed bytes. Only a change in how the service counts could move it.
  - **The figure is indicative only.** The run is on Oracle, through the Linux build.
- **The guards decide.** L10 checks the whole read on Oracle, through the Linux build and the run
  account's credential, before each round. §5.5 checks every review's reads after each round. A cut
  in either voids the round (§12).
- **R-PG-01's sheet**, at the same rate, is about 15,800 tokens (31,266 numbered bytes), about 63 %
  of the limit. This is an estimate, not a measurement.

**The account sentence is part of the treatment.**
- Arm F's reviewers read `ACCOUNT_SHEET_GIVEN`; arm I's read R-PG-01's sentence.
- A sheet that gives ranges and notes has to be described as one, so the sentence cannot be
  separated from the sheet.

### 2.6 The invocation, run ids and slots

**The invocation** is R-PG-01's, as its `launch.sh` runs it, once per arm. Only the machine's
wrapper changes.
- **Where it runs:** on Oracle, as the run account, in the run-branch checkout
  `~/physgate-r-pg-01b-run`, at the run commit with a clean tree.
- **How a round is started**, as the earlier unattended runs on Oracle were:
  `setsid nohup experiments/R-PG-01b/launch.sh --round <r> > ~/runs/rpg01b/launch-<r>-<attempt>.log 2>&1 < /dev/null &`.
- **Each arm runs with:**
  - `CLAUDE_CODE_OAUTH_TOKEN` exported from the shape-checked line of
    `~/.config/physgate-run.env`, never printed;
  - `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN` and `ANTHROPIC_BASE_URL` unset;
  - `DISABLE_AUTOUPDATER=1`, and `PHYSGATE_CLAUDE_BIN=$HOME/pinned/claude-2.1.301`.
- **`caffeinate -i` is dropped.** R-PG-01 wrapped the command in it to keep the laptop awake; the
  server needs none (§2.3).

```
uv run --frozen physgate inject \
  --corpus "$HOME/physgate-r-pg-01b-run/corpora/injected-errors/<v1 | v1-fullsheet>" \
  --run-dir "$HOME/runs/rpg01b/run-<k>" \
  --scratch "$HOME/review-scratch/rpb-<k>" \
  --run-id "rpb-<k>" \
  --seed 7 \
  --params "$HOME/physgate-r-pg-01b-run/experiments/R-PG-01/params.json" \
  --install "$HOME/runs/rpg01b/install-<k>" \
  --review-clean-twins
```

**Slots.** `<k>` is a slot number.
- Slots 1 to 4 hold the first attempts of (arm I, round 1), (arm F, round 1), (arm I, round 2) and
  (arm F, round 2). Their assignment is drawn with `random.Random(29)` and recorded before round 1.
- A re-attempt (§12) takes the next unused slot from 5 upwards. The two arms of a round take their
  slots in the order of their first slots.
- Every slot has the same form of run id, review root, run directory and installation, so no id or
  path tells an arm.
- Each process builds its own installation, so two builds never share a directory.

## 3. Definitions

**Per run**, exactly as R-PG-01 §3 defines them:
- The unit is the injected artefact.
- **Approved (A)**, **caught (C)**, and the **headline: C among A**.
- A review left without a verdict after its retry counts as not approved. It is listed and never
  re-drawn.

**Per (artefact i, round r, arm X):**
- `a(i,r,X)`: 1 if the injected artefact's review is approved.
- `t(i,r,X)`: 1 if the clean twin's review is approved.
- `m(i,r,X)`: 1 if the review names the planted error, by R-PG-01 §6 item 10's rule. Its twin is
  the twin's review in the same run.
- `g(i)`: 1 if the gate caught the artefact. It is the same in every run (R6).

## 4. Rules of fair play

- **R1 First honest version.**
  - Nothing of §2 changes after this file is committed, except the facts it marks `[FILL]`, each in
    the dated commit its placeholder names ("sheet filled" or "run commit filled"), before the
    first review. Nothing else in this file changes at those commits.
  - A defect in the instrument found after a number is seen is a deviation. The experiment is
    repeated at the corrected commit as a new experiment, and both are reported.
- **R2 Blindness.**
  - R-PG-01 R2 holds for every run, unchanged: the neutral account, the blindness check and the
    file-name rule. Arm F's sheet is held to the same check (L6).
  - Slots and their paths are neutral (§2.6).
- **R3 Nothing reachable.**
  - For arm I's runs: R-PG-01's `r3_scan.py`, unchanged.
  - For arm F's runs: `experiments/R-PG-01b/r3_scan_f.py`. It is R-PG-01's script with arm F's
    corpus path and manifest in place of `v1`'s and nothing else, and its diff against
    `r3_scan.py` is published.
  - Each is run for its run's review root, run directory and installation. No corpus, no run and no
    other slot's root is under a root.
- **R4 Clean twins.**
  - The 40 clean twins pass the gate at the run commit: 40/40, records sha256
    `ea3d581a027abd3538c3aa5271f169ca8ddc2d868e5f7fe104739ef1ccb8e75c`, by R-PG-01's
    `r4_twins.py`, before each round.
  - The gate's copies hold no sheet, so one measure covers both arms.
- **R5 Nothing is re-drawn.** No artefact is replaced or dropped. The denominator is 40 per run.
- **R6 Gate determinism.**
  - Every run's gate records must be byte-identical to every other run's.
  - `regate_r6.py`'s second pass must report 0 records that differ.
  - `contrast.py` makes the cross-run comparison and reads that count. A difference is a deviation
    (§12).
- **R7 The operators are blind.**
  - Progress lines give counts only.
  - No one reads a verdict, a finding or a per-artefact row before §5's tally runs on every valid
    run.
  - A void attempt (§12) is read for its causes and counts alone.
- **R8 Exposure before the freeze** is disclosed in §9, threat 10.

## 5. Metrics

### 5.1 Per run: R-PG-01's metrics, unchanged

**For each run:** A, C and the kill reading (R-PG-01 §3 and §5), and secondary results 1 to 10
(R-PG-01 §6), by `tally_rows.py` and `read_catches.py`, unchanged.
- Results 2, 3, 4 and 6 belong to the gate and the corpus alone. They must be identical in every
  run (R6), and are printed once.
- After each round, every review line's `rubric_sha256` is checked against the pinned digest of its
  role (§2.2).

**The gate's added catches against each arm** are R-PG-01's C, per run. That is ARCH-083's
quantity: artefacts approved by the reviewer and caught by the gate. Beside it go:
- result 5, the gate's catches among the artefacts the reviewers rejected;
- result 10's "caught, not named".

**Each arm's reading** is the mean over its rounds: Ā is the mean of A, and C̄ the mean of C.
- R-PG-01 §5's rule is read on those means: the kill reading fires if C̄ < 10 or Ā < 4.
- Each round's own reading is printed beside it.

### 5.2 The primary contrast

**ΔC = C̄(F) − C̄(I):** the change in the gate's added catches when the reviewers have the complete
sheet.
- As a sum over artefacts, ΔC = Σᵢ g(i) · d(i), where d(i) = (1/R) Σᵣ [a(i,r,F) − a(i,r,I)].
- Negative ΔC: the incomplete sheet inflated the gate's added catches. Positive ΔC: it deflated
  them.
- **The share** of arm I's gate advantage the sheet accounts for is −ΔC / C̄(I). It is printed when
  C̄(I) ≥ 1, with the bootstrap interval of §5.4, unless the floor of §7 holds.

### 5.3 Secondary contrasts (reported; they decide only where §7 says)

Each is paired per (artefact, round).

1. **ΔA:** approvals of injected artefacts.
2. **ΔT:** approvals of clean twins (R-PG-01 result 7).
3. **Δnamed:** injected artefacts whose review names the planted error, by result 10's rule with its
   twin condition. Beside it, the same count without the twin condition.
4. **ΔCNN, "caught, not named"** (result 10): the gate's advantage in a form that does not depend on
   approval.
5. **ΔC among rejected** (result 5).
6. **Per class and per role** (results 1 and 8): ΔA and ΔC, as counts, with no interval.
7. **`blocked` and `review_unavailable`** per arm and role, each with its cause (result 9).
   - Beside them, per arm: each review's turns and wall clock (median and maximum), and how many
     reviews ended at the 80-turn or 4500 s bound.
8. **Sensitivity:** ΔC and ΔA again, with every (artefact, round) pair excluded in which either
   review is `blocked` or `review_unavailable`.
9. **The noise floor.** For each arm, its disagreements between its two rounds on each artefact,
   against the disagreements between the arms within a round.
   - It is measured twice: on the injected artefact's approval and on the twin's.
   - It is given as counts and Cohen's κ, and reported only.

### 5.4 Intervals and tests

- **Interval:** a 95 % percentile bootstrap over the 40 artefacts, 10,000 draws,
  `random.Random(13)`. A resampled artefact carries its injected reviews and its twin's reviews in
  every run.
- **Beside it, for each round alone:** Newcombe's (1998) method 10 interval for a difference of
  paired proportions, scaled to counts.
- **Test:** the exact two-sided McNemar test (binomial, p = ½) on the discordant (artefact, round)
  pairs, pooled over rounds.
  - **For ΔC and ΔCNN**, only the pairs of gate-caught artefacts are counted (g(i) = 1). The others
    cannot contribute.
  - **For every other contrast**, all 40 artefacts count.
  - With no sheet effect, the arms are exchangeable within each pair, so the test is exact.
- **"Shown":** a contrast is shown when its interval excludes 0 **and** its exact p is below 0.05.
  - Otherwise it is **not shown at this size**, and the interval's bounds are printed as the largest
    effects not excluded.
- **With one valid round only (§12),** Newcombe's interval replaces the bootstrap.
- **Each arm's own levels** (Ā and C̄) get the same bootstrap interval, or a Wilson interval with one
  round.

### 5.5 Did the treatment reach the reviewers?

After each round, `streams.py` reads every review's captured stream. It is kept under the review
root as `<root>/<session id>/session/stdout.jsonl`, since R-PG-01's runner removes only the
review's working copy.

**What is read.** For each Read call on `parts_sheet.json`, the check reads the text the model
received: the tool-result content returned to the model for that call. It never uses the copy of
the file, or a line count the stream reports beside the result.

**What each read is expected to return.** The sheets' numbered lines are pinned:
- arm F: **1,225 numbered lines**;
- arm I: **984 numbered lines**;
- both end with the same last row id.

A read asks for the lines from its offset (line 1 if none is given) up to its limit (the rest of the
file if none is given).

**How each read is classed:**
- **cut:** it returned fewer numbered lines than it asked for, whatever its offset or limit, or it
  asked for the file's end and the last row id is absent;
- **whole:** it asked for the whole file and returned every line, last row included;
- **part:** it asked for a range smaller than the file (a reviewer's own paging) and returned all of
  it.

**What is reported**, per arm, round and side, beside ΔC in `RESULT.md`:
- the reviews that read `parts_sheet.json` at least once, and those that never did;
- the Read calls on it;
- the whole, part and cut reads;
- the reviews whose reads together covered every line.

**What a cut does.**
- **A cut read in any review, in either arm, voids the round** (§12). It can only come from the
  service's counting, which the bytes do not control.
- A review whose stream is missing is listed, and counted as unknown.

**How the check is tested.** `streams.py` is tested on real streams of the pinned binary against a
scripted endpoint, with no model call:
- a read the endpoint counts at 25,000 tokens must be classed whole;
- one counted at 25,001 must be classed cut.

These tests are built later, with the tooling of §14.

### 5.6 What the experiment can show

The smallest ΔC with 80 % power was estimated by simulation:
- per-artefact approval probabilities drawn from a Beta distribution;
- the exact test of §5.4 alone, 1,500 runs per setting.

The double rule of "shown" is slightly stricter than the test alone.

| Gate-caught artefacts | Mean approval of gate-caught artefacts | Two rounds | One round |
|---|---|---|---|
| 20 or 30 | 35 % to 50 % | about 7 to 9 items | 12 or more |
| 20 or 30 | 20 % | none up to 10 items | none up to 12 |

**The direction simulated** is a fall: the complete sheet lowers the approval of gate-caught
artefacts, so ΔC is negative.
- At 20 % approval, arm I's C̄ is only about 4 to 6, and a fall cannot be larger than C̄(I). That
  is why no fall up to 10 items reaches 80 % there.
- A rise is not bounded this way, but it was not simulated.

Hence **two rounds**. A smaller sheet effect can only be reported as not shown, with the interval
saying what it excludes.

## 6. Every rejection read for its reason

Every review whose outcome is `fail` or `blocked` is given one reason class. That covers every valid
run, injected artefacts and twins alike.

**Finding lines.** Lines are defined as R-LAW-01 §2.2 defines them:
- each entry of the review's `result.items` whose result is `unmet` (sections 1 to 3) or `confirmed`
  (section 4);
- plus `result.failing_item`, if it names an item not already among them;
- each with its evidence text, every rubric item id replaced by `[rule]`;
- read from the last review line of each subtask. R-PG-01's log records the same fields.

**Line ids** run `L0001…` in this order, across the four runs:
1. round (1, 2);
2. arm (I, F);
3. side (injected, twin);
4. artefact id;
5. the entry's position in `result.items`.

Every seeded draw below starts from a list sorted by these ids.

**The locus of a line** is the set of (node id, quantity name) pairs of the design pair that it
names. A pair is named by the quantity name as a whole word, and the node id or the part of it after
its first dot as a whole word, case-folded. This is R-LAW-01 §2.2's rule, implemented from that
description.

**A changed pair** of a design pair is either of:
- a (node, quantity) whose value or unit differs between its clean and injected patches, or that one
  patch has and the other lacks;
- for a propagation item, every (node, quantity) of the injected edge's two end nodes.

This is R-LAW-01 §2.3's definition.

**Reality.** Every finding line is judged `true_flaw`, `not_a_flaw` or `undecidable`, with its
origin, by R-LAW-01's reality adjudication.
- **Its system prompt and output schema are used verbatim** (R-LAW-01 Appendix E): prompt sha256
  `41438ab78097d57a6e986b24f4f8071516fa36c1f0393f408874cd81adb23913`, schema sha256
  `57c3852f8aa0adf9450de3504509b0bf95f85e78c55ff77b199a9c0998172324`.
- **The session settings:** `claude-opus-5-5`, effort high, no tools, no settings, no MCP, no session
  persistence, an empty working directory.
- **One packet per design version**, that is, per artefact and side.
  - It pools the lines of all four runs on that version, shuffled with `random.Random(37)`, at most
    12 per packet, labelled F1 to Fn.
  - It holds the base design's nodes, the nodes the revision wrote, the findings, and the table
    `parts_sheet.md` verbatim (`29f9568c…`).
  - It never states the arm, the round, the side, the error class, the expected check, a verdict or
    a gate record. Pooling both arms in one packet keeps the adjudicator blind to the arm, though a
    finding itself may say that a sheet lacked a value.
- **It runs on the run account,** after both rounds, within §11's quota rules and under its own
  token guard (§12).

**Two controls, each reported with its bar.**
- **Calibration.**
  - A P review (below) is calibrated if at least one of its error-item lines is judged `true_flaw`
    with origin `introduced` or `both`.
  - The bar: at least 70 % of P reviews are calibrated; put the other way, their planted-error lines
    are rarely judged `not_a_flaw`.
- **Rejection control, R-LAW-01 §2.3's rule exactly.**
  - The eligible lines are injected-side lines judged `true_flaw` with origin `introduced`, whose
    every locus pair is a changed pair. The locus must be non-empty, since an empty locus names no
    pair.
  - For each injected design version holding one, one line is drawn (`random.Random(43)`). It is
    placed in a packet of its own, built for that pair's clean twin (its base, its clean patch, the
    table), with that single finding.
  - The correct verdict there is `not_a_flaw`. The bar: at least 70 % come back `not_a_flaw`.
  - Control verdicts are never reality verdicts.
- **Each control needs at least 10 cases.** With fewer, it is reported as **not checked**.
- **The O/N split below is labelled:**
  - **reliable** if both bars are met;
  - **unreliable** if either is missed;
  - **unchecked** if either control is not checked.

**The counting rule: one class per rejection, the first that holds.**
1. **B, blocked.** A `blocked` review. It is listed with its cause and not adjudicated.
2. **P, names the planted error.** The review of an injected artefact names its error by R-PG-01 §6
   item 10's rule. This is decided mechanically, from item ids, with the twin condition.
3. **O, other real flaw.** At least one finding line is `true_flaw`. On both sides, O is split into:
   - **O-introduced:** a `true_flaw` line with origin `introduced` or `both`. On the injected side
     this may hold a planted error described under an item outside its cell; result 10 counts naming
     as a lower bound for this reason.
   - **O-base:** every `true_flaw` line is `already_in_base`.
4. **N, no real flaw.** Every finding line is `not_a_flaw`.
5. **U, undecided.** The rest: a line `undecidable` and none `true_flaw`, or a review with no
   finding line.

A `review_unavailable` review is not a rejection; it is listed under result 9.

**Reported per arm and round, for injected artefacts and for twins:**
- the counts of B, P, O (split), N and U;
- the paired change in N between the arms: the rejections the complete sheet removes or adds;
- **the twins' corrected refusal rate:** twins rejected in class N over 40, with N + U as its upper
  bound. A twin rejected in class O was refused for a real flaw, which is not correct work refused.

**Descriptive only:**
- **A tag:** a finding line that cites by row id one of the 62 rows R-PG-01's sheet left without a
  value. The tagged share per arm is printed. It is a lower bound, since a line may name a missing
  value without its id.
- **A count:** for P reviews, how many of their error-item lines are judged `not_a_flaw`.

## 7. Decision use, fixed now

**D1 The corrected headline.**
- Arm F's reading (Ā, C̄ and the kill reading, §5.1) is reported as R-PG-01's headline corrected for
  the sheet.
- It stands beside R-PG-01's published reading, which stays as it is, with its preface.
- **The risk row's status follows arm F's kill reading.**
- If arm F's two rounds disagree on the kill reading, it is labelled **not stable at this size**,
  and the mean still decides.
- **Its "why" sentence is taken from this table** at the last step (§8), since it compares
  readings.
  - Each reading is the kill reading of §5.1. Arm I's and arm F's are read on the means of their
    rounds.
  - The rows are read **from the top**, and the first row that holds gives the sentence.
  - **"Through the A leg / the C leg / both":**
    - the A leg is crossed when Ā(I) and Ā(F) lie on different sides of 4 (one below 4, the other
      at 4 or above);
    - the C leg is crossed when C̄(I) and C̄(F) lie on different sides of 10.

| # | When | The sentence |
|---|---|---|
| 1 | Arm I's two rounds disagree with each other on the kill reading | "The kill reading is not stable at this size; the sheet's part in it is not separable." |
| 2 | R-PG-01's reading, arm I's and arm F's are all the same | "The complete sheet did not change the kill reading." |
| 3 | R-PG-01's reading and arm F's are the same, and arm I's differs from both | "Under today's protocol the complete sheet changed the kill reading, through the A leg / the C leg / both: ΔA = … (interval), ΔC = … (interval). Today's reading with the incomplete sheet differs from R-PG-01's (drift or protocol differences), so R-PG-01's published reading matches the corrected one." |
| 4 | R-PG-01's reading and arm F's differ, and arm I's is R-PG-01's | "The complete sheet changed the kill reading, through the A leg / the C leg / both: ΔA = … (interval), ΔC = … (interval)." |
| 5 | R-PG-01's reading and arm F's differ, and arm I's is arm F's | "The kill reading changed between R-PG-01 and today's same protocol (drift or protocol differences), not through the sheet." |

  A kill reading either fires or not. So when R-PG-01's and arm F's differ, arm I's equals one of
  them, and rows 2 to 5 cover every case that row 1 leaves.

**The floor.** If C̄(I) < 3 **and** C̄(F) < 3:
- the gate's added catches are **not measurable at this approval rate**;
- ΔC and its interval are printed under that label, and the share is not printed;
- D2's sentence is the floor's.

D1 still applies, since arm F's own reading fires on C̄ < 10.

**D2 The sheet's share.** ΔC with its interval answers §1 (§5.2). It is reported in one of three
fixed sentences:
- if shown: "the incomplete sheet changed the gate's added catches by ΔC (interval)";
- if not shown: "no change was shown at this size; the interval excludes changes beyond its
  bounds";
- under the floor: "not measurable at this approval rate".

**D3 R-PG-02.**
- **R-PG-02's reviewer arms are re-run with the complete sheet as a new experiment, whatever
  R-PG-01b shows.** R-PG-01b's result is never used to excuse R-PG-02's numbers.
- **Why unconditional:**
  - At 40 artefacts the interval on any contrast is several items wide, so a rule like "re-run
    unless the interval excludes effects beyond a margin" would trigger almost every time.
  - A sheet effect on this corpus's stand-in does not transfer to R-PG-02's corpus, which has a
    different base design.

**D4 The reviewers' refusals of correct work.**
- The thesis's figure is arm F's corrected refusal rate (§6), with arm I's beside it.
- It is labelled when the O/N split is unreliable or unchecked.

**Under a deviation (§12)** that voids the primary contrast, D1, D2 and D4 are **not taken**, and
R-PG-01 stands with its preface alone. D3 stands in any case.

## 8. Analysis blinding, and the comparison with R-PG-01 (the last step)

**The order:**
1. All of R-PG-01b's numbers (§5, §6) are computed by the scripts of §14. Those scripts are
   committed before the first review, and run only after every valid run has ended.
2. **"Numbers final."** `RESULT.md`'s sections on R-PG-01b alone are committed **and pushed** on the
   branch `exp/r-pg-01b-numbers` (Appendix A), with the tally's full output and its sha256. This happens before any person who has read R-PG-01's
   results sees any output of the tally.
3. Only then does `compare_r_pg_01.py` run. Its output becomes `RESULT.md`'s last section, in a
   commit of its own.

**The analyst's allowlist.**
- **The analyst** runs the tally and the reason reading and writes step 2. It is a fresh agent that
  has not read R-PG-01's results.
- **How it is started:** as a session of its own, inside its clone, never as a subagent of another
  session. The owner starts it with the prompt of Appendix A.
- **Where it works:** a sparse clone at `~/rpg01b-analysis` on the machine where its session runs,
  plus the run outputs under `~/runs/rpg01b/`.
  - The clone is made with `git clone --single-branch --no-tags --branch r-pg-01b-run`, so it holds
    the run tag's commit alone.
  - By default the session runs on Oracle, where the outputs are.
  - Elsewhere, `~/runs/rpg01b/` alone is first copied to the same path there, with its digest
    recorded.
- **What it reads:** this file, the scripts, and those outputs. Nothing else.
- **What the clone excludes:** `experiments/R-PG-01/RESULT.md`, `experiments/R-PG-02/`, and every
  results summary and private working file kept outside the repository.
- **`check_analyst.py` runs before the tally** and confirms that:
  - the excluded paths are absent;
  - the clone has no branch or tag other than the run tag's;
  - its working directory is the clone.
- **Until "numbers final" is pushed,** every message and handback from the analyst carries counts of
  sessions, failures and tokens only, and no metric.
- **A bug found in an analysis script** after numbers are seen is fixed in a dated commit.
  - Both outputs, before and after the fix, are published.
  - **The corrected output is the one that decides.**
  - A fix never changes a rule of this file.

**Nothing before step 3 reads R-PG-01's results.**
- No script of R-PG-01b opens R-PG-01's `RESULT.md` or run directory, R-PG-02's files, or any file
  that quotes them.
- `compare_r_pg_01.py` refuses to run unless the pushed "numbers final" commit exists and the
  committed tally output matches its digest.

**Who is blind:**
- This file was drafted, and then frozen, by agents that have read R-PG-01's `CRITERIA.md` and none
  of its results.
- The owner and the orchestrator have read them. They approve this file and the scripts before the
  run, and read R-PG-01b's numbers no earlier than step 2.

**What the last step computes, by fixed rules:**
1. **Replication, against the same-day noise floor.**
   - D_cross: for each arm I round, the artefacts on which its injected-artefact approval differs
     from R-PG-01's, averaged over the two rounds.
   - D_same: the artefacts on which arm I's two rounds differ from each other.
   - **Replicated** if both hold:
     - the bootstrap 95 % interval of D_cross − D_same (over artefacts, `random.Random(13)`)
       includes 0 or lies below it;
     - the exact McNemar test between R-PG-01 and arm I, pooled over rounds, gives p ≥ 0.05, so
       there is no systematic shift.
   - **Not replicated**, otherwise: the difference is named **drift or protocol differences**.
     - The protocol differences include the binary's Linux build, the machine and the account
       (§2.3, rows 5 and 12).
     - It is reported beside the sheet effect, never in place of it.
   - **With one valid round only,** there is no same-day noise floor.
     - D_cross is arm I's one round against R-PG-01, printed with its bootstrap interval.
     - **Replicated** then means that the exact McNemar test between R-PG-01 and that round gives
       p ≥ 0.05. The result is labelled "without a noise floor".
   - The same is reported for the twins.
2. **The sheet's share of R-PG-01's advantage:** −ΔC divided by R-PG-01's C, when that is at least
   1 and the floor does not hold.
3. **The gate across time.** R-PG-01's gate records are compared with R-PG-01b's. They are expected
   to be byte-identical; a difference is reported as a deviation of the gate's determinism.
4. **D1's sentence**, from its table.

The comparison changes no number of steps 1 and 2, and no decision of §7 beyond D1's sentence.

## 9. Threats to validity (stated before the run)

1. **Reviewer variance.** A single review is noisy.
   - Mitigation: paired arms run at the same time, two rounds, an exact test and an interval, and
     the noise floor (§5.3 item 9).
   - **Resolution:** §5.6. Only an effect of about 7 or more items can be shown.
2. **The direction is two-sided** (§1). A complete sheet can add grounds for rejection, such as a
   note's limit, as well as remove them. The contrast measures the net effect.
3. **The treatment is the sheet and its sentence together.** Arm F's reviewers are told that the
   sheet gives values as written and notes. The sentence cannot be separated from the sheet.
4. **R6.05.** One word of one note is edited (§2.5). The table's 9 prose lines are not carried,
   since two of them would tell a reviewer that the design is a stand-in.
5. **The backport** changes code on the reviewers' path.
   - Arm I's packets are checked byte-identical to R-PG-01's (L5).
   - Arm F's differ only where L7 allows.
6. **Drift and protocol differences between R-PG-01 and this run.** The arms share all of them, so
   the I-against-F contrast is untouched. They bear only on the comparison with R-PG-01, which the
   last step measures:
   - the model served behind a pinned string may have changed;
   - the account is another (§2.3, row 5);
   - the binary is the Linux build of the same version, on another machine (§2.3, row 12);
   - the binary's request defaults are measured anew at launch;
   - the service's token counting decides whether a large Read is cut, which L10 and §5.5 guard.

   Two more limits follow from it:
   - **Arm F falls behind arm I within a round.** Its reviews read a longer sheet and may take
     longer, so the two arms review the same artefact further apart in time as a round goes on. The
     pairing is by artefact, not by clock. The lag is reported from each review's start time.
   - **Today's sheet effect may not be the one 18.10.2026 would have shown.** The contrast is
     measured with today's service and account. Applying it to R-PG-01's run assumes the effect held
     then. The last step's replication check (§8) is the only evidence on that.
7. **The whole-read margin.**
   - Arm F's sheet was read whole in a real session on macOS (the smoke of §10), at about 22,778
     tokens, about 91 % of the binary's 25,000-token limit.
   - That figure is indicative only. The run is on Oracle, through the Linux build, and L10 there
     decides before each round.
   - The method: the context growth across the Read turn, less that turn's output.
   - Above the limit the binary cuts the text without a notice (§2.5).
   - R-PG-01's sheet is estimated at about 63 % of the limit.
   - Mitigation: L10 before each round and §5.5 after it. A cut voids the round.
8. **Longer reviews.**
   - Arm F's sheet is 12,657 bytes longer than R-PG-01's.
   - A review that runs closer to its turn or wall-clock bound may end `review_unavailable`. That
     counts as not approved, and it would mimic a sheet effect. Mitigation: §5.3 items 7 and 8.
   - The 400,000-token ceiling applies to the always-loaded set (ARCH-023), not to a sheet the
     reviewer reads.
9. **The rejection reading.**
   - One model judges reality. It is the corpus authors' model, not the reviewers'.
   - Mitigation: two controls with bars and minimum counts. No decision rests on the O/N split
     except D4, which is labelled when the split is not reliable.
10. **Exposure before the freeze.**
    - The drafter read R-PG-01's `CRITERIA.md`, its frozen `launch.sh` and `params.json`, the code,
      and a code-level account of the sheet defect.
    - The drafter also read, by script, counts and digests of the corpus, plus row R6.05 and the
      table's 9 prose lines.
    - The drafter ran the non-evaluation smoke (§10), which reviewed the pilot design, not this
      corpus.
    - The owner and the orchestrator have read R-PG-01's results. No choice in this file was drafted
      with them, and the owner's choices are listed in §15.
11. **The corpus** is one stand-in design with 40 artefacts in the authors' four gate-shaped error
    classes (R-PG-01 §7). It is unchanged from R-PG-01 and limits both arms alike.
12. **The neutral account's bias** (R-PG-01 R2) raises A and C. It is the same in both arms, so it
    cancels in the contrast, but not in each arm's reading.
13. **The run commit's code has not run on Linux before.**
    - R-PG-01 ran it on macOS.
    - On Oracle, the launch checks L3 to L10 are its first run.
    - A check that fails for the platform, and that only a code change could cure, stops the
      experiment (§12). The run branch admits no other change.

## 10. Host, the smoke, and run order

**Host.** Oracle (`ssh oracle`): the ARM Linux VM, 2 OCPU and 12 GB, unattended, as R-PG-02's runs
and a later reviewer calibration run were.
- **The binary:** Oracle's Linux aarch64 build at `~/pinned/claude-2.1.301`, sha256 `1e119036…`,
  verified read-only on 23.10.2026.
- **The checkout:** `~/physgate-r-pg-01b-run`, at the run commit with a clean tree.
- **Outputs:** under `~/runs/rpg01b/`, with review roots at `~/review-scratch/rpb-<k>` (§2.6).
- **Starting a round:** `setsid nohup`, with a launch log (§2.6).
- **The laptop is not used.** It cannot hold a 24 to 28 h run unattended.

**The smoke already run.** This experiment classifies it as a non-evaluation smoke: one check
session on a design that is not this corpus, whose verdict is never a result.
- R-LAW-01 forbids its sessions in the same weekly window as an *evaluation run* on the account, but
  it does not define a "non-evaluation smoke". The classification is this experiment's own, and is
  disclosed as such.

| Item | Value |
|---|---|
| Account and machine | the development account, through the binary's own login, on the macOS laptop with the macOS build |
| When, UTC | 23.10.2026, 07:33:16Z to 07:38:08Z |
| Sessions | one, with no retry |
| Tokens | 336,445 in all: input 8, output 29,788, cache creation 104,653, cache read 201,996 |
| Cost | $0.757, the binary's figure; 17 turns |
| What ran | R-PG-01's reviewer from `8bc03fc` with this file's backport in a scratch copy; R-PG-01's parameters; the instrument's own four-role pilot design (electrical artefact), carrying arm F's sheet |
| Result | the whole read of §2.5 |

- **It differs from the run's sessions in its login, its machine and its build.**
  - It used the binary's default configuration and claude.ai login, with `--strict-mcp-config` and
    claude.ai MCP servers off.
  - The stream showed tools Read and StructuredOutput, and 0 MCP servers.
  - The run's sessions use the instrument's own credential route, on Oracle (§2.6).
- **Its whole-read figure is indicative only.** L10, on Oracle through the Linux build, decides.

**L10, before each round.**
- One smoke review of the same pilot design carrying arm F's sheet, on Oracle, through the run
  commit's reviewer, the run account's credential and the Linux build.
- It passes if the stream shows at least one whole Read of `parts_sheet.json` and no cut.
- Each read is classed by §5.5's rule: the text the model received, against the pinned 1,225
  numbered lines and the last row.
- **If the reviewer never read the sheet,** the smoke is repeated, at most twice more.
- **After three smokes in which the reviewer never read the sheet,** one last check session runs:
  - the same binary, credential, settings, hooks and packet;
  - a one-line prompt that asks it to read `parts_sheet.json` in full, then stop.

  This tests only the service's counting, which does not depend on the prompt.
  - If it reads the sheet whole, L10 passes.
  - If it never reads the sheet, the round does not start, and the experiment stops for the owner
    as a deviation (§12).
- Its tokens and times go in the quota ledger as this experiment's non-evaluation smokes, in the
  round's line (§11).

**Run order:**
1. The owner approves this file, and it is committed: the freeze. No code of R-PG-01b exists before
   it.
2. The scripts of §14, with their tests on synthetic fixtures, are committed on `master` (the
   "scripts" commit). No review of this corpus runs in this step.
3. The "sheet" commit on `master`: arm F's corpus, and the edited table copy (§2.5). The dated
   "sheet filled" commit follows: arm F's manifest label and digest, and nothing else. Then the run
   branch (§2.4), tagged and pushed. The dated "run commit filled" commit follows: the run commit
   and its instrument tree, and nothing else.
4. **Round 1:** the launch checks L1 to L11 (§14), then both arms at once. After it: §5.5, the
   rubric digests, and R6.
5. **Round 2:** the same.
6. The tally (§5), the reason reading (§6), then "numbers final" (§8).
7. The comparison with R-PG-01 (§8). `RESULT.md` is then complete.

## 11. Account, cost and quota

**Account.**
- Everything but the recorded trial runs on Oracle's run account: the account R-PG-02's runs and a
  later reviewer calibration run of 22.10.2026 used. Its long-lived token is the shape-checked line in `~/.config/physgate-run.env` on
  Oracle.
- The launch script reads that line into `CLAUDE_CODE_OAUTH_TOKEN` and never prints it.
- L1 records the account's label, as the owner states it, and the first 8 hex digits of the token's
  sha256.
- **No wait for R-LAW-01.** R-LAW-01's weekly-window rule binds the development account only. That
  account carried only the trial of §10, recorded as it ran.
- The smoke of §10, and every L10 smoke, is recorded under this experiment's classification as a
  non-evaluation smoke (§10), with its times and tokens.

**Cost.**

| Step | Sessions | Model | Estimate |
|---|--:|---|---|
| Reviews: 2 rounds × 2 arms × (40 + 40) | 320, plus at most one infrastructure retry each | `claude-sonnet-5` | About 0.34 M tokens a review (the smoke on macOS: 336,445 tokens, $0.757) to 0.40 M (the pilot's mean of $0.89, R-PG-01 R8). A later reviewer calibration run's reviews on the run account, with a later instrument, ran 0.49 to 0.51 M. About 54 to 64 M tokens a round, 110 to 130 M in all; about $240 to $285 as the binary prices it. |
| L10 smokes | 2 to 6 | `claude-sonnet-5` | About $0.76 each |
| Wall clock | — | — | About 5 to 8 min a review, each arm serial and the arms in parallel: about 7 to 11 h a round, plus about 1 h of launch checks. |
| Gate passes | 0 | none | Minutes |
| Reality adjudication (about 1,100 to 1,500 finding lines, at most 12 a packet) and both controls | About 150 to 200 | `claude-opus-5-5` | About 60 k tokens a session (the table alone is about 9 k), about 10 to 12 M tokens; the guard is 30 M |

The run has no dollar cap. It is bounded by its count of sessions and by each session's bounds, as
R-PG-01 was.

**No other session runs on the run account during a round,** from L10's first smoke to the
round's last review. The owner confirms this at launch, and it is recorded.

**The quota ledger.**
- Each round's tokens, every try, are counted as the binary's own totals.
- Here they are summed from every session's `result` line, since R-PG-01's instrument has no repair
  resumes. Void attempts are included.
- Each round adds one line, with the account and the round's start and end times (UTC), before the
  round is scored.

**The 5-hour projection** is L11, before each round. It is a recorded figure, not a gate: it
starts, delays or stops nothing.
- **What the run account is known to carry:** in the reviewer calibration run of 22.10.2026, 80.46 M
  tokens between 06:05 and 09:50 UTC, inside one 5-hour span, with no limit.
- **T, the tokens projected per review,** is the larger of L10's smoke review on Oracle and 0.40 M
  (R-PG-01's pilot rate). For round 2, round 1's measured rate also counts, if it is larger.
- **The figure.** Two sessions at once, at about 5 min a review, finish at most about 120 reviews in
  5 hours. L11 records T and 120 × T, beside 80 M, in the round's ledger line.

**No weekly gate.** The owner set no weekly cap on the run account, so no round waits for, or is
stopped by, a weekly allowance.

**A usage limit during a round** is caught by a watcher.
- A watcher derived from the one that calibration run used stops both arms at the first session
  that ends on a usage limit, so no further session runs into the limit.
- The round is void and counts as an attempt (§12). It is re-attempted after the limit that stopped
  it has reset.
- **The fallback, for a round the 5-hour limit keeps stopping.**
  - It applies when a round has been voided twice by the 5-hour limit.
  - The round's next attempt runs the two arms one after the other, in consecutive windows, in an
    order drawn with `random.Random(31)`.
  - This is disclosed as a deviation from same-time pairing.

## 12. Deviations, fixed now

- **A launch check fails:** no review of that round runs.
  - A wrong fact (a path, a missing file) is fixed and the check is run again.
  - A check that can pass only by changing this file stops the experiment. An amendment is a new
    experiment.
- **L10 finds a cut read:** the round does not start. The bytes are fixed, so a cut means the
  service's counting has changed. The experiment stops, and the owner decides on a new experiment.
- **L10 cannot be applied:** three smokes and the check session never read the sheet (§10). The
  round does not start, and the experiment stops for the owner.
- **§5.5 finds a cut read in any review:** the round is **void**. It counts as an attempt and is run
  again from the start into new slots. A second cut in the same round stops the experiment, as
  above.
- **An infrastructure cascade.**
  - A round is **void** when **3 or more** of its reviews, both arms together, end
    `review_unavailable` for an infrastructure cause after their retry.
  - Nothing of a void round is read but its causes and counts.
  - One or two such reviews are kept and count as R-PG-01's rule counts them, as not approved. §5.3
    item 8 shows their effect.
- **A usage limit** stops both arms through the watcher (§11). The round is void and counts as an
  attempt.
- **A crashed or killed process** voids both arms of that round. It counts as an attempt, and the
  round is run again into new slots.
- **Attempts:** at most **3** per round. Every attempt is listed with its causes.
- **A round lost** after 3 void attempts:
  - with one valid round, the analysis is the R = 1 form (§5.4), and is labelled;
  - with none, there is no result, and D1, D2 and D4 are not taken.
- **The gate's records differ** between runs, or `regate_r6.py` reports a record that differs (R6).
  C is not computed, and the primary contrast and D1, D2 and D4 are not taken.
- **A review line's `rubric_sha256`** is not its role's pinned digest. The tally stops.
- **The tally's totals differ** from `tally_rows.py`'s or `read_catches.py`'s for any run. The tally
  stops.
- **The reason reading reaches its 30 M token guard.** It stops and is void, §6's counts are not
  reported, and D4 is not taken. Nothing else changes.
- **Anything else impossible as specified** is a deviation of the same kind: the reading it feeds is
  not taken.

## 13. What is published

**`RESULT.md` cites:**
- this file's freeze commit, the "scripts" commit, the "sheet" commit, the "sheet filled" and "run
  commit filled" commits, and the run commit with its tag;
- every pin of §2.2, as checked at launch;
- the digests of §2.5, including the R6.05 edit's.

**It publishes:**
- for each run, its results file and its `physgate catches` output, which must equal the rows;
- R-PG-01's secondary results, for each run;
- the contrasts with their intervals and tests, and the noise floor;
- §5.5's counts of reads, beside ΔC;
- for the rejection reading, each review's class, every finding line's verdict, and both controls;
- the smokes' records (§10);
- the slot draw;
- the causes of every void attempt, and every deviation;
- both outputs of any fixed analysis script;
- the last step's comparison, in its own section.

Session transcripts, tokens and account files are not published.

## 14. Scripts and launch checks (written after the freeze)

**Where everything runs.**
- All scripts live under `experiments/R-PG-01b/` on `master` and, with equal blobs, on the run
  branch.
- Every script runs on Oracle, in the run-branch checkout `~/physgate-r-pg-01b-run`, as R-PG-01's
  `launch.sh` runs its own: `uv run --frozen python -I …`.
- The exception is `make_sheet.sh`, which runs the converter on `master` at `31b90aa` or later.
- Each is tested by `test_*.py` on synthetic fixtures, never on this corpus's reviews.

| Script | What it does |
|---|---|
| `make_sheet.sh` | Copies the table, applies the R6.05 edit to that one word, runs the converter in keep mode with `--prose drop`, and writes arm F's corpus and manifest. Prints counts and digests only, including the edit's before-and-after digests. |
| `launch.sh` | Derived from R-PG-01's `launch.sh` (blob `63efe5ac3f182d9b99c5870ae318caf871bc9c8e`); its diff against that file is published. It replaces R-PG-01's macOS check with a check that it runs on Oracle as the run account; its binary path and digest are the Linux build's; `caffeinate` is dropped; it reads the token from `~/.config/physgate-run.env`. For each round it runs L1 to L11, starts the usage-limit watcher, then starts both arms at once with §2.6's invocation. Any failure stops it before any review. |
| `abort_on_limit.sh` | §11's watcher, derived from the watcher of §11's reviewer calibration run; its diff against that script is published. It stops both arms at the first session that ends on a usage limit, and logs counts and causes only. |
| `packets_identity.py` | L5 and L7. Builds every packet of both arms at the run commit, and arm I's at `8bc03fc`, with no session: the materialised worktree and account, and the reviewer's packet (its `read/` directory and `packet.json`, as R-PG-01's reviewer prepares them). Every packet is built at one fixed path per artefact and side, with one fixed session id, whatever the arm. Compares their digests and prints counts only. |
| `streams.py` | §5.5, after each round, and L10's whole-read check. It reads the text the model received, against the pinned line counts. Its tests run on real streams of the pinned binary from a scripted endpoint: a read counted at 25,000 tokens must be classed whole, and one counted at 25,001 cut. |
| `smoke.py` | L10. One reviewer session as §10 states it, and its fallback check session; the whole read is classed by `streams.py`. Prints counts, times and tokens. |
| `r3_scan_f.py` | R3 for arm F (§4). |
| `contrast.py` | §5. Takes A, C, naming and twin approval per artefact from each run through `tally_rows.py`'s own functions, re-implementing no rule, and holds them to `tally_rows.py`'s printed totals. Computes the contrasts, intervals, tests, sensitivity and noise floor; the cross-run comparison of R6, with `regate_r6.py`'s count of differing records; and the check of every review line's `rubric_sha256`. |
| `reasons_extract.py`, `reasons_packets.py`, `reasons_sessions.sh`, `reasons_tally.py` | §6: the finding lines and loci; the packets and both controls, whose key no session is shown; the sessions with the pinned prompt, schema and model, a token log and the 30 M guard; the classes, counts, bars and labels. |
| `check_analyst.py` | §8: the analyst's clone holds none of the excluded paths, no branch or tag other than the run tag's, and is the working directory. |
| `compare_r_pg_01.py` | §8's last step. Refuses to run before the pushed "numbers final" commit. |
| R-PG-01's `r3_scan.py`, `r4_twins.py`, `regate_r6.py`, `tally_rows.py`, `read_catches.py` | Run unchanged, at the blobs of §2.2, in the run worktree. |

**Launch checks, each round:**
- **L1** On Oracle, as the run account: the checkout `~/physgate-r-pg-01b-run` is at the tag's
  commit, with a clean tree. Recorded:
  - the account label, the token's digest prefix and the slot draw;
  - the owner's confirmation that no other session will run on the run account during the round
    (§11).
- **L2** `git diff --name-only 8bc03fc <run commit>` lists only §2.4's paths, and:
  - every blob under `experiments/R-PG-01b/` equals `master`'s at the "scripts" commit;
  - the run branch holds no `experiments/R-PG-01b/sheet/`;
  - every blob under `corpora/injected-errors/v1-fullsheet/` equals `master`'s at the "sheet"
    commit.
- **L3** Every pin of §2.2 holds at the run commit:
  - the gate tree, bounds, spelling and catalogue;
  - the reviewers and rubrics trees, with the four digests;
  - the instrument tree of §2.4 and the `params.json` blob;
  - the binary's sha256 (`1e119036…`, the Linux build) and its version (2.1.301).

  `uv run --frozen python -c "import physgate; print(physgate.__file__)"` resolves under the run
  worktree.
- **L4** Arm I's manifest is `41553301…`. Arm F's manifest and sheet are those of §2.5, and its base
  and artefacts are byte-identical to arm I's.
- **L5** Arm I's 80 packets are byte-identical to those `8bc03fc` builds, which are R-PG-01's.
- **L6** Arm F's 80 packets pass the blindness check: 0 of 80 refused.
- **L7** Both arms' packets are built at the same fixed paths, with the same fixed session id, so
  no path or id differs. Arm F's reviewer packets may then differ from arm I's only in:
  - `parts_sheet.json`'s bytes;
  - the account's sheet sentence;
  - the file listing's line for `parts_sheet.json`;
  - the two commit ids;
  - and every digest, size and part boundary that follows from these.
- **L8** R4: 40/40, records sha256 `ea3d581a…`.
- **L9** R3 for each arm's run: `r3_scan.py` for arm I and `r3_scan_f.py` for arm F, and the
  reviewer's read allowance on the pinned Linux build, as R-PG-01 ran it on its build. R-PG-01's dry run records the
  reviewer requests' defaults.
- **L10** The smoke of §10, on Oracle, through the Linux build and the run account: a whole read of
  arm F's sheet, and no cut.
- **L11** The 5-hour projection of §11: T and 120 × T are recorded in the round's ledger line. It is
  a figure, not a gate, and cannot stop the round.

**After each round:** §5.5's stream check, the `rubric_sha256` check, and R6.

## 15. The numbers and choices the owner set (approved 23.10.2026)

| # | What | Value | Where |
|---|---|---|---|
| 1 | R6.05's note | "answered" becomes "responded", disclosed (decided 23.10.2026) | §2.5 |
| 2 | Prose beside the tables | dropped (decided 23.10.2026) | §2.5 |
| 3 | Whole-read guard | keep the sheet as converted; L10 and §5.5, where a cut voids the round (decided 23.10.2026) | §2.5, §12 |
| 4 | Account | Oracle's run account; no wait for R-LAW-01's window, which binds the development account only (decided 23.10.2026) | §11 |
| 5 | Arms | I (the replication) and F | §2.1 |
| 6 | Rounds R | 2 | §2.1, §5.6 |
| 7 | Primary contrast | ΔC | §5.2 |
| 8 | "Shown" | the 95 % interval excludes 0, and the exact p < 0.05 | §5.4 |
| 9 | The floor | C̄ < 3 in both arms | §7 |
| 10 | D1 to D4 | as written; D3 unconditional (D3 decided 23.10.2026) | §7 |
| 11 | Control bars | 70 % each, at least 10 cases | §6 |
| 12 | Void rules | 3 infrastructure-unavailable reviews in a round; a crash; a cut; 3 attempts per round | §12 |
| 13 | Quota | no other session on the run account during a round; a watcher stops a round at the first usage limit, which voids it as an attempt; one ledger line per round; the 5-hour projection (120 × T, beside 80 M) recorded, not a gate; no weekly gate, since the owner set no weekly cap (decided 23.10.2026) | §11, §12 |
| 14 | Reason-reading token guard | 30 M | §12 |
| 15 | Seeds | instrument 7; slots 29; arm order under §11's fallback 31; bootstrap 13 (10,000 draws); packets 37; rejection control 43 | §2.6, §5.4, §6, §11 |
| 16 | Host | Oracle, the Linux build `1e119036…`, unattended (decided 23.10.2026) | §10 |
| 17 | Analyst | a fresh agent blind to R-PG-01's results, started by the owner as its own session in the clone, with Appendix A's prompt | §8 |

---

## Appendix A. The analyst's prompt

**How it is used.**
- The owner makes the clone of §8 (by default on Oracle) and starts a new session inside it, with
  this prompt verbatim. It is never started as a subagent of another session.
- **Where "numbers final" goes.** The clone holds the run tag alone, a branch off R-PG-01's commit,
  so "numbers final" is committed on its own branch, `exp/r-pg-01b-numbers`, and pushed. Its files
  are later copied byte for byte to `master`.

```
You are the analyst of experiment R-PG-01b. Your working directory is a clone of the run tag
r-pg-01b-run; the run outputs are under ~/runs/rpg01b.

1. Read experiments/R-PG-01b/CRITERIA.md in full before anything else. Follow its §5, §6, §8 and
   §14 as written. You may not change any rule in it.
2. Read only the files of this clone and of ~/runs/rpg01b. Open nothing else on this machine: no
   other checkout or clone, no results file or summary of any experiment, nothing of R-PG-02, no
   private notes, no .env and no credential. If any file you open shows a number next to "R-PG-01"
   that is not in CRITERIA.md, stop at once and say so, without repeating the number.
3. First run experiments/R-PG-01b/check_analyst.py. If it fails, stop and say why.
4. Run the scripts in the order §8 gives: the tally of §5, then the reason reading of §6, whose
   sessions use the credential the owner has set up for them (you never read it). Run each script
   as §14 says: uv run --frozen python -I, in this clone.
5. Until the "numbers final" commit is pushed, every message you send, including your final
   report, carries counts of sessions, failures and tokens only: never a metric, a verdict, a
   class count or a per-artefact row.
6. Write RESULT.md's sections on R-PG-01b alone, with the tally's full output and its sha256.
   Commit them on a new branch exp/r-pg-01b-numbers, as "numbers final", and push that branch.
7. If you find a bug in an analysis script after a number is produced, fix it in a dated commit,
   keep both outputs, and let the corrected one decide. Never change a rule of CRITERIA.md.
8. Never run compare_r_pg_01.py, and never read anything of R-PG-01's published results.
9. End with one report: the pushed commit's id, the tally output's sha256, and the counts of
   sessions, failures and tokens. Nothing else.
```
