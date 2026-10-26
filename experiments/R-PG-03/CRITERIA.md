# R-PG-03 — pre-registration: the review-calibration fix, tested on new material

> Git-tracked and public. `ARCH-nnn` and experiment IDs only.

**Status:** frozen and committed before any file of the new set exists. Facts are filled later,
each in its own dated commit, before the first review, and none is a choice:
- **"Commits filled"**: the run commit `R` and its rubric-only sibling `R_K` (§3.2), with every
  tree, blob and digest of §3, and `code_changes.py`'s list of code changes since the practice
  runs' trees (§3.3);
- **"Sheet filled"**: the reviewers' parts sheet's sha256 and counts (§2.4);
- **"Set filled"**: each corpus's manifest digest, after its acceptance checks: fresh-v2's seven
  and `fresh-v1c`'s two (§2.5).

Every `[FILL]` below is such a fact. A `[FILL AT FREEZE]` is filled in this file before it is
frozen.

**Written:** 23.10.2026 (draft); revised four times on 24.10.2026, after four adversarial reviews
(the last a narrow check).
**The numbers the owner sets:** §14, approved by the owner on 24.10.2026.
**Cites:**
- R-PG-02 (`experiments/R-PG-02/`): its frozen tally, error-item table, parameters and authoring
  design.
- R-LAW-01 (`experiments/R-LAW-01/`): its finding-line definition and reality adjudication.
- R-PG-01b: its sheet treatment, its decision D3, and its quota ledger on the shared run account.

**Names used here.** **The tuning set** is R-PG-02's fresh set, corpus `fresh-v1` (40 + 40), on
which the fix was tuned. It is never called `practice-2` here: in R-LAW-01 that label names a
different run, on practice/v1. **The practice cycle** is the calibration work that tuned the fix;
its **noise run** re-ran K on the tuning set, and its **kept round** is the run of the fixed
rubrics that the stop rule kept.

Nothing in those experiments is changed or re-scored.

**Excluded entirely:** R-PG-01 and everything of it, including R-PG-02's run on R-PG-01's corpus.
No such file is read by any script, session or person in this experiment.

**Rule:** nothing in this file may change after the first metric is produced.
- A measurement that turns out to be impossible as specified is recorded in `RESULT.md` as a
  deviation. The decision it feeds is **not taken**; it is never rewritten (§11).
- An amendment is a new experiment (`R-PG-04`) that cites this one.

---

## 1. Question

**Did the review-calibration fix make the paired specialist reviewers better on design revisions
written after it was frozen, and are they now at least as good as one role-aware generalist
reviewer?** Both directions, every time: the share of injected errors rejected **for the right
reason**, and the share of correct revisions **accepted**.

**Why this is asked.**
- **R-PG-02's P4 failed:** paired J 0.45 against generalist J 0.80, a difference of −0.35 with
  interval [−0.575, −0.125], at 2.34× the tokens.
- **What the practice cycle on the tuning set then found.** That set was spent as a test from the
  moment its reviews were read.
  - Most of the R gap came from the two arms' different scoring rules. Under one common rule, both
    arms reject 34 of 40 for the right reason.
  - The A gap sat on electrical and firmware twins. There the specialists blocked on inputs the
    parts sheet does not give, or charged the revision with conditions the base already had.
- **The fix,** kept under a stop rule fixed in advance, is two rubric rules, placed inside the
  domain sections so that the generalist is untouched:
  - a condition the base already has, with the same numbers, is `noted` and not charged to the
    revision (it refines ARCH-062);
  - an input the parts sheet does not give is `noted`, never `blocked`.

  It was kept **exactly at its bar**, while 8 of 40 twins flipped between two runs of the same
  configuration.
- **Practice numbers are not results.** This experiment is the test.

**The arms** (§3), all reviewing the same items on `claude-sonnet-5`:

| Arm | What |
|---|---|
| **A2, the fixed specialists** | each item reviewed by its role's paired reviewer with the four frozen fixed rubrics (ARCH-060 as built) |
| **A1, R-PG-02's specialists** | the same, with R-PG-02's four rubrics (configuration K) |
| **B, the generalist** | each item reviewed with its role's rubric less the two domain sections, and the cross-domain knowledge, by code; R-PG-02's generalist byte for byte |
| Gate | deterministic; reported from A2's runs; never a question here |

**Not asked:** the gate's catch rate (R-PG-02), a second vendor, a hybrid reviewer, or anything on
R-PG-01's corpus.

## 2. The set: `fresh-v2`

### 2.1 Shape

| Corpus | Author pair | Items | Classes | Base |
|---|---|---|---|---|
| `fresh-v2-x1` | X | 20 injected + 20 twins | 5 each of `unit`, `magnitude`, `equilibrium`, `propagation`; 5 distinct propagation edges | X's |
| `fresh-v2-x2` | X | 20 + 20 | as above; none of x1's edges | X's |
| `fresh-v2-y1` | Y | 20 + 20 | as x1 | Y's |
| `fresh-v2-y2` | Y | 20 + 20 | as x2 | Y's |
| `fresh-v2-z1` | Z | 20 + 20 | as x1 | Z's |
| `fresh-v2-z2` | Z | 20 + 20 | as x2 | Z's |
| `fresh-v2-s` (secondary) | X's base, session C | 10 + 10 | 10 of `standard` (§2.2) | X's |

- **Primary: 120 + 120,** 30 per class, three independent author pairs, each writing R-PG-02's
  design (one base, 40 revisions in two batches of 20 from a brief written for 20, R-PG-02 §2).
  - Each batch is its own corpus, so a block of the run (§10) is one batch, named after it: block
    `x1` reviews `fresh-v2-x1`. Blocks are written in lower case, author sessions (X1, X2, …) in
    capitals.
  - Pairs X, Y and Z share only the frozen inputs. Each has its own base.
- **Secondary: the domain-standard class,** 10 pairs (§2.2, §6.4). It is never part of the
  primary figures.
- **Seeds** are fixed now (§14). Author sessions take no seed.

### 2.2 Who authors, and what they see

**Seven new sessions,** each on `claude-opus-5-5` (R-PG-02's author model), each starting with no
history:

| Session | Writes | Messages it gets |
|---|---|---|
| X1 | X's `base.json`, then revisions `a01`–`a20`, then (resumed) `a21`–`a40`, then (resumed) `s01`–`s10` | the launch message; R-PG-02's continuation and the third continuation (Appendix B); check facts in the fixed template |
| X2 | X's errors for `a01`–`a20`, then (resumed) `a21`–`a40` | the launch message; the fixed continuation |
| Y1, Y2 | as X1 and X2 for pair Y, without `s01`–`s10` | as X1 and X2, without the third continuation |
| Z1, Z2 | as X1 and X2 for pair Z, without `s01`–`s10` | as Y1 and Y2 |
| C | the 10 domain-standard errors in `s01`–`s10` | the launch message only |

Any session cut short by a usage limit or an infrastructure error also gets Appendix B's resume
message (§2.5).

- **The order within a pair:** X1 writes each batch, and each passes §2.5's checks before the next
  message. X2 starts only when `a01`–`a40` have passed. C starts only when `s01`–`s10` have passed.
  The same order holds for Y1 and Y2, and for Z1 and Z2, which have no `s` batch.
- **The passed copies** are a pair's `base.json` and its `clean/*.json` files, nothing else. When
  a batch passes, the runner records the sha256 of each of its `clean/*.json` files, and of
  `base.json` when the pair's first batch passes. Every corpus is assembled from those passed
  copies, never from a later session's directory. Every later session gets its own copies of what
  it needs, in its own directory.
  - `done.md`, `plan.md` and every other file of a session's directory are not passed copies.
    Appendix B's messages ask authors to append to `done.md` in later turns.
  - An error session's `injections/*.json` are recorded by sha256 when they pass their checks,
    after that session has ended, and the corpus takes them from that record.
- **Replacement and restart sessions** run only where §2.5's routes call for them. Each starts
  with no history, in a new directory that holds only its inputs, and gets the same inputs and the
  same messages as the session it replaces. The exception is X3 (§2.5), whose launch message is in
  Appendix B.

**The domain-standard class (`standard`)** is an error that breaks a rule its domain's standards
file states:
- a rating exceeded, a derating not applied, a margin below the standard's minimum, or a timing or
  rate budget overrun;
- in a node of the revision's assigned role's domain;
- where the design and the parts sheet give everything a reader needs to see it.

Session C reads the four domains' `knowledge/<domain>/standards.md` at the run commit, and nothing
of the rubrics.

**What each session sees: only its inputs, each listed with its sha256 in its `inputs.json`:**
- R-PG-02's frozen common files, byte for byte (`architecture.md`, `format.md`, `vocabulary.md`,
  `risk_row_1.md`);
- the briefs, R-PG-02's byte for byte except for the additions of Appendix B: one reading-list
  line in `brief_A.md`; the same line and one sentence in the class list in `brief_B.md`. And
  `brief_C.md` (Appendix B);
- **`rules.md`, the authoring rules (Appendix A);**
- the authors' parts table (§2.4);
- for the error sessions, their own pair's passed `base.json` and `clean/`: for X2, Y2 and Z2,
  `clean/a01`–`a40`; for C, `clean/s01`–`s10` only, as `brief_C.md` says;
- for C, the four standards files.

**What no session sees:**
- any practice material of R-PG-02 or of the calibration cycle: no set, review, tally, reading or
  defect list in its original form. The rules of Appendix A are written generically and name no
  item, node or number from practice;
- the rubrics;
- the gate's code or output, beyond bare check facts to X1, Y1, Z1 and X3;
- the other pairs' files.

**The sandbox** is R-PG-02's:
- Read, Write and Edit only, inside the session's own directory, with a guard that refuses any
  other path;
- no shell, web, settings or servers;
- proven on the scripted endpoint before any launch, and audited after each turn of a session (each
  message and the work it asks for, a resumed turn included) from its stream: tools, refusals,
  models, mentions of a gate or an answer, secrets.

**Who launches.** A runner agent follows a fixed command sheet on the run machine.
- Every message a session receives is a file in Appendix B, or a check script's printed facts
  inside Appendix B's fixed template.
- Every message is published with its sha256.
- The runner reads only counts, exit codes, audit summaries and the facts it forwards.
- So nothing the runner, or anyone involved in tuning, knows of practice can reach an author.

**Between sessions** (R-PG-02 R2), only the base and the clean revisions are checked before the
next session starts, and only their facts go back to an author: X1, Y1, Z1 or X3, as bare facts.
The injections are checked after their session ends. X2, Y2, Z2 and C never see any check output
(§2.5's routes).

### 2.3 The authoring rules and where each comes from

The practice cycle read every rejection of its runs for its reason. It found eleven defects in the
corpus and the base design that misled reviewers or made "clean" twins not clean, and its transfer
check found two more. Each became a generic rule, or is handled elsewhere. Three rules were left
out. Rule numbers here are those of `rules.md` (Appendix A):

| # | Defect found in practice (kind only) | Rule | How it is held |
|---|---|---|---|
| 1 | The reviewers' sheet lost every range, list, min/typ/max and text value (62 of 163 rows) and every note | — | the converter (§2.4) |
| 2 | A margin taken from an absolute-maximum row | 2 | mechanical check (§2.5) |
| 3 | A clean twin deleted quantities, or moved to a chemistry the sheet does not characterise | 3 | mechanical check (deletions); the rule's text (chemistry) |
| 4 | A clean twin relaxed a requirement, with a convenience reason | 4 | requirement and limit changes listed and published (§2.5); the rule's text |
| 5 | An operating point cited as a published limit | 5 | mechanical check (limit names against operating-point rows) |
| 6 | A changed node's edge left without a reason because its target was rewritten for another reason | 6 | the gate's propagation check (ARCH-082) and the rule's text |
| 7 | Quantity names that do not say where a moment or torque acts | — (left out: where a quantity acts) | not given; read after the run (§7) |
| 8 | A duty-limit convention left implicit; a stall margin that depends on the battery's charge | — (left out: the duty-limit convention) | not given; read after the run (§7) |
| 9 | Inputs the rubrics need that the sheet lacks, missing from the account's absences list | — | **not folded:** the account is unchanged (§3.3); the complete sheet supplies several; the fixed rubrics' absent-input rule is what A2 − A1 measures |
| 10 | A datasheet figure with two labels, carried without its note | 1 | the converter carries the note; the rule |
| 11 | The journal order of node writes inside one revision read as a later change | — (left out: node order) | not given; read after the run (§7) |
| 12 | A base physics flaw that revisions re-derive (a reduction counted twice) | 8 | the rule's text; not checked before the run |
| 13 | A clean twin deleted a protective quantity, or put a different datasheet metric under an existing name | 3, 7 | mechanical check (deletions); the rule's text (metric) |

**Where the rules come from, exactly.**
- **Every defect above came from reading reviews of specialist runs:** K's noise run and the fixed
  rubrics' kept round on the tuning set, and the fixed rubrics' transfer run on practice/v1. **No
  generalist review was read** for them.
- **Three rules were drafted from the fixed rubrics' own errors and left out by the owner before
  authoring** (24.10.2026). The kept round newly refused three correct twins of the tuning set, all
  physics misreadings:
  - twin a28, the motor-clamp reaction taken for the axle reaction (where a quantity acts);
  - twin a18, the stall current computed without the duty limit, with a08's false stall-current
    line (the duty-limit convention);
  - twin a21, the order of node writes inside one revision read as a missing follow-up, with the
    noise run's a11 (node order).

  Given to the authors, they would have cleared the new set of the very ambiguities the arm under
  test misread, and Q4 could not see it. Left out, the new set may hold those ambiguities again,
  and every arm meets them. So no qualifier is added to §8's sentences.
- **Rules 2, 3, 4 and 7 remove real twin flaws.** Rules 3, 4 and 7 also draw on practice/v1, where
  no generalist ran.
- **Rule 6 is mixed.** It removes a premise on which K's specialists refused, but whether the
  premise's absence is a real flaw was left undecided (a blind check split 2 to 2). It is kept as a
  twin-flaw rule.

**The direction, stated now, rule by rule.** The table gives what each rule's practice instance
showed: who refused it there, and so which way removing that kind from the new set moves each
contrast in raw A.

| Rule | Its practice instance | Who refused it there | Removing that kind moves |
|---|---|---|---|
| 1 (with the converter) | twin a22: one setting under two labels, its note lost on the stripped sheet | K's noise run refused; the fixed rubrics and the generalist accepted | A1 up: **against Q1** |
| 2 | twin a30: a margin from an abs-max row | K's noise run and the fixed rubrics refused it (a real flaw); the generalist accepted | both specialist arms up against B: **toward Q2 and Q3** |
| 3 | twin a08: deleted quantities, an uncharacterised chemistry | K's noise run and the fixed rubrics refused it (a real flaw); the generalist accepted | **toward Q2 and Q3** |
| 4 | twin a20: a relaxed requirement | all three arms refused | no arm against another on that instance |
| 5 | twin a25: an operating point cited as a limit | the generalist refused; both specialist arms accepted | B up: **against Q2 and Q3** |
| 6 | the five twins of one propagation premise | K's noise run refused two on it; the fixed rubrics refused none of them, and the generalist accepted all five | A1 up: **against Q1** |
| 7 | a different metric under an existing name | practice/v1 only, where no generalist ran | not known |
| 8 | a base reduction counted twice | practice/v1 only (the transfer check) | not known |

- **For Q1 (A2 against A1),** the rules given lean, if anything, against the fix (rules 1 and 6).
  The three rules that leaned toward A2 against both other arms were left out.
- **For Q2 and Q3 (A2 against B),** two rules lean toward the specialists (2 and 3) and one toward
  the generalist (5). The rest are neutral on their instance, or not known.
- **Q4 cannot see any of this,** because the shaping sits in how the set was written, not in a drop
  between sets. The complete sheet also narrows the measured drop (§9 item 2).
- The direction is a threat (§9 item 1), stated before any number.

**What "not checked before the run" leaves.** A twin that breaks a rule held only by its text, or
a kind no rule covers, reaches the run. Any rejection it draws is read for its reason after the run,
blind to the arm (§7). A real flaw there, confirmed (§7), makes the twin "flawed" in the
corrected-A reading.

### 2.4 The parts sheet

- **The authors' table** is R-PG-02's `parts_sheet.md` (sha256
  `29f9568ce8465112ef0b0b164f05f3ba76f9702e3ccbc7a1dea96fbc3d057b3f`) with **one word**
  changed: R6.05's note "answered" becomes "responded". "Answer" is a telltale word that the
  converter refuses. This is the same edit R-PG-01b makes.
  - The drafter measured the edited table's sha256 as
    `0573ef044ebdcee9ff184eec2789e1a10b31fef6f32947735f9005ea8b0daedc`.
  - A word-level diff against R-PG-02's table shows exactly one change.
- **The reviewers' sheet** (`sources.json`, served as `parts_sheet.json`) is written from that table
  by the converter `scripts/parts_sheet_sources.py` (PR #69), at the run commit, after the
  converter's follow-up fixes are merged (PR #77). The call,
  fixed now:

  ```
  uv run python scripts/parts_sheet_sources.py <the edited table, sha256 0573ef04…> <sources.json> \
      --keep-values-from <R-PG-02's sources.json, sha256 bc1e5ec1…> \
      --prose drop \
      --drop-prose-line-sha256 4c7844dc7a445b5e8628c27a5ae14b526275b2d45270d0e4ff571fb4e1dd7a8c
  ```

  The one digest is the "Conventions" line's, the sha256 of its UTF-8 bytes as written. The
  follow-up fixes' proof finds no other prose line that holds a row id (one, by both its strict
  and its loose count). The option's name and the digest are copied from that proof
  (24.10.2026, at a head that was rebuilt before merging), and are checked again at the merged
  head: `dbd9a08`.

  - `--keep-values-from` R-PG-02's `sources.json` (sha256 `bc1e5ec1…`). From the table alone, only
    63 rows give a citable number: count rows and some unit spellings do not read as one number
    with a unit. Keeping the earlier sheet's numbers keeps the same 101 citable rows that fresh-v1's
    authors' derivations were held to, so **the authoring constraint is unchanged and only what
    reviewers see grows**;
  - `--prose drop`. The table's prose lines include "Stand-in design, not the reference solution"
    and the author's "Kit choice: I chose…", which would tell a reviewer the design is an exercise.
    The authors still read them, as R-PG-02's did.
    - **What it also drops,** stated now: the kit's build line (the 50:1 motor, the 80×10 mm
      wheel, six AA NiMH cells), the sheet's conventions (a stated count is a row of its own,
      values are copied verbatim with their unit, a number no source states is not on the sheet),
      the source keys, and the note on which motor the user's guide uses. The authors read these;
      the reviewers do not.
    - No earlier reviewers' sheet carried any prose, so nothing is lost against R-PG-02 or the
      practice cycle. It is an asymmetry between authors and reviewers that every earlier sheet
      also had, and it is disclosed (§9 item 13).
  - **The override, for a prose line that names a row only in passing.** After the follow-up
    fixes, `--prose drop` refuses a table whose prose holds a row id, because the row's id would be
    dropped with the line. The authors' table has one such line, its "Conventions" line, which
    names R1.03 in passing (the follow-up fixes' own count). The override is a repeatable option
    that takes the sha256 of one prose line that may be dropped although it holds a row id.
    - The call names each such line by its digest.
    - A named digest that matches no line of the table refuses, and so does a prose line with a row
      id whose digest is not named.
    - Naming changes nothing that is kept, and every other refusal of `--prose drop` still holds.
    - The follow-up fixes' proof shows that this call, on the edited table, writes the probe's
      sheet below byte for byte (`2efbb6a8…`, 40,095 bytes). The same call without the name
      refuses. With a stale name added it refuses too (shown on the unedited table).
  - **The same call writes `fresh-v1c`'s sheet** (blocks `p1` and `p2`). fresh-v1's own table is
    R-PG-02's `parts_sheet.md` (`29f9568c…`) and its sheet is `bc1e5ec1…`, so `fresh-v1c`'s
    edited table is the same bytes as fresh-v2's (`0573ef04…`). Its reviewers' sheet must be the
    same bytes as fresh-v2's, and §2.5 checks that.
- **The drafter's probe** (23.10.2026, at `fc28f32`, in a scratch directory, counts and digests
  only):
  - 163 rows: 101 with a number, 111 with `given`, 62 with `given` only, **0 with neither**;
  - 130 notes;
  - 9 prose lines dropped;
  - 0 telltale words;
  - 40,095 bytes, sha256 `2efbb6a8ab889ceac54d8ebdba15c8530274d8524c9eaf6181d22abf5ccbef90`.

  A wider scan of every `given` and note (for stand-in, reference, solution, thesis, experiment,
  test, review, error, clean, inject, plant, twin and answer) found nothing else.
- **"Sheet filled"** records the digest and counts at the run commit. The procedure, fixed now:
  - **Every count equals the probe's, and so does the digest:** recorded.
  - **Every count equals the probe's, but the digest differs:** the byte-level difference between
    the two sheets is printed by script and published, and the new digest is recorded. This is a
    fact, not a choice.
  - **Any count differs, or the converter refuses the call:** the sheet is not used, and no author
    session starts. The cause is found by script: by a row-by-row comparison of the two sheets, or,
    for a refusal, from the converter's printed reason and the line or row it names.
    - If the converter's text explains it, the converter is fixed, the fix is merged, `R` is cut
      again, and "Sheet filled" is measured again. This is a precondition, not a deviation (§11).
      A fix that would change the call above, its digests included, changes this file, and so
      falls under the next point.
    - Otherwise the experiment stops for the owner, before any review. Going on with a sheet this
      file does not describe is an amendment, which is a new experiment.
- **What every review is told:**
  - the account's sentence for a sheet with `given` and `note` (pinned since PR #69);
  - the same bytes in every arm.
- **The read limit.** A sheet built the same way was read whole at about 22,800 tokens, about 91 %
  of the binary's 25,000-token read cap (R-PG-01b's trial). Two guards follow:
  - a whole-read smoke on the run machine before the first block;
  - a stream check after each block.

  **A cut read in any review voids its block** (§11).

### 2.5 The acceptance checks, before a corpus's manifest is filled

Run on each corpus of fresh-v2, on the run machine, at `R`:

1. **The loader and completeness:** format, the telltale scan of every node and file name, 5 per
   class and 5 distinct propagation edges per batch, and 10 of `standard` for `fresh-v2-s`.
2. **The gate on the base and on every clean revision:** no failing record. This is the twins'
   precondition (R-PG-02 R4). By construction, the gate's acceptance of the twins is therefore **not
   a result**.
3. **The source check** (`physgate inject-sources`), on the base and the clean revisions, as
   R-PG-02 ran it: `mismatch` 0. `subtracted` and `unresolved`, the sheet's own, are listed.
4. **The rule checks** (`rules_check.py`, mechanical), on the base and the clean revisions:
   - **rule 3:** no node of a revision lacks a quantity that the same node has in the base;
   - **rule 2:** no quantity's source cites a row whose quantity text names an absolute maximum
     (4 rows of the table: R4.04, R4.07, R6.06, R7.09);
   - **rule 5:** no quantity whose name reads as a limit or a rating (`*_limit`, `max_*`, `*_max`,
     `rated_*` or `*_rating`) cites one of these 18 rows, fixed now:
     - the efficiency points R1.16, R1.17, R1.18, R1.19 and R1.20 (named so in their quantity
       text);
     - the rows whose note or value marks the number as typical: R1.05, R1.10, R1a.02, R1a.03,
       R1a.10, R1a.11, R4.09, R4.12, R6.08, R6.09, R6.11, R7.08 and R8.02.

     Two rows whose text says "typical" are left out: R6.03 is a published continuous rating
     (under typical conditions), and R7.07's number is its max column. The first eleven rows give
     a citable number; the other seven give `given` only. The patterns cover the vocabulary's
     limit-like names (`current_limit`, `max_discharge_power`, `max_temperature`,
     `rated_output_power`, `rated_voltage`) and the common forms an author may coin. A limit under
     a name no pattern matches is held by the rule's text;
   - **listed, not returned:** every change to a `requirement`-kind node, and every change to a
     quantity named `*_limit`, `max_*`, `*_max`, `min_*`, `*_min`, `rated_*` or `*_rating`, with
     its old and new value (rule 4).
5. **The sheet:** the converter re-run reproduces "Sheet filled"'s digest.
6. **Blindness:** `require_blind` on a packet built for every item and twin, and R3's scan (§5).
7. **The audit** of every turn of every session (§2.2).

**`fresh-v1c`** (blocks `p1` and `p2`) is not authored, so it takes items 1, 2, 5 and 6, at `R`. That
means the loader and completeness of each batch; the twin precondition again; its sheet equal to
"Sheet filled"'s digest (§2.4); and blindness. Its two manifests go into "Set filled". If either
fails, blocks `p1` and `p2` are not run. §6.4 item 10 then says so, and the primary is untouched.

**What happens when a check fails: every route, fixed now.** No file is ever edited by hand. Every
failure, route, resume, replacement and restart is recorded and published (counts and facts only).

**A turn** is one message to a session and the work it asks for: the launch message, a
continuation or a set of facts. A resume (below) continues the turn it resumes and starts no new
one: **a turn and every resume of it count as one turn,** for the retry ladder and for the
usage-limit rule. The checks of a batch run after the turn that wrote it has ended. Each failure is
routed by the session and the turn it falls in.

| Failure | Route |
|---|---|
| **The clean side** (the base or a clean revision) fails item 1, 2, 3, 4 or 6 | The bare facts go back to the session that wrote it (X1, Y1, Z1 or X3: the check's name, the node, the quantity, the message), in Appendix B's template. A batch gets its first check, then **at most 4 fact rounds**, each followed by a check. |
| **A primary clean batch** (the base with `a01`–`a20`, or `a21`–`a40`) fails the check after its 4th fact round; or X1's, Y1's or Z1's audit fails in a primary turn (the launch message, the continuation to `a21`–`a40`, or a fact round on either), a change to a passed copy included | **The pair restarts from scratch:** a new base, from new sessions X1 and X2 (Y1 and Y2; Z1 and Z2), in new directories, with the same inputs and messages. Nothing of the earlier attempt is kept: not its base or its batches. No error session has started yet then (§2.2's order). |
| **An injection** (X2's, Y2's, Z2's or C's) fails item 1 (format, completeness, telltale) or item 6; or that session's audit fails in any turn, a change to its copy of a passed file included | The error sessions never see check output, so **that error session is replaced** by a new one, in a new directory, with the same inputs (the passed copies) and messages. It writes every batch of that session from the start. The clean side is not touched, and nothing restarts. |
| **`s01`–`s10`** fail the check after their 4th fact round; or X1's audit fails in its `s` turn (the third continuation, or a fact round on `s`), a change to a passed copy of pair X's primary files included | The `s` batch is written once more by a new session **X3**, in a new directory, with X1's inputs, pair X's passed copies of `base.json` and `clean/a01`–`a40` (read-only by its message), and Appendix B's launch message for X3. X3 gets the same first check and 4 fact rounds. Pair X's primary is untouched: it is assembled from its passed copies. |
| **X3's batch** fails the check after its 4th fact round; or X3's audit fails, a change to its copy of a passed file included | `fresh-v2-s`'s cap is reached (below). X3 runs at most once. |
| **A session cut short** (below) | It is resumed with Appendix B's resume message. |
| A failure no author caused (a packet the instrument cannot build, an R3 hit, the sheet, a tool fault in a check, an infrastructure outage past the retry ladder below) | Fixed by its own procedure (§11), and the check is run again. An outage is not fixed but waited out: the cut turn is resumed (below), and its checks run when it has ended. No author file changes, and no fact round, replacement or restart is spent. |

**A session cut short.** A session is cut short when the watcher stops it at
`usage_limit_reached` (§10), or when its stream ends on an infrastructure error before the turn
ends. An infrastructure error is an API, connection or binary error, never a refusal and never
something the author did. In either case the session is resumed with Appendix B's fixed resume
message. The resumed turn finishes the task of the turn it resumes, and its checks and its audit
then run as for that turn.
- **A usage-limit cut** is resumed after the limit that stopped it has reset.
  - **Once per turn:** if the resumed turn is cut by a usage limit too, or the session has already
    used its 2 usage-limit resumes, the session is treated as failing its audit in that turn, and
    is routed as such (the table above).
  - At most 2 such resumes per session, each replacement or restart session having its own.
- **An infrastructure cut** is resumed on the instrument's own retry ladder (`infra_retry_delays_s`,
  §3.4): after 60 s, then 900 s, then 2,700 s, so at most 3 times per turn.
  - **If the same turn is cut a fourth time** by an infrastructure error, it is a failure no author
    caused (the table's last row): the runner waits until the owner confirms that the service is
    back, and the ladder then starts once more for that turn.
  - **If that second ladder is spent too,** the authoring stops for the owner. The owner may only
    wait longer and resume the same turn with the same message, each time recorded, or stop the
    authoring as at the cap of the batch that turn writes (below): the primary's cap for a primary
    batch, `fresh-v2-s`'s for the `s` batch. Nothing of any set has been reviewed then, so the
    ruling is blind.
  - **An infrastructure cut never spends** a fact round, a replacement, a restart or one of the
    session's 2 usage-limit resumes, and it is never an audit failure.
- **Every resume** has its own ledger line (§10), and the resumes are counted apart from the caps.

**What an audit failure is.** A tool other than Read, Write and Edit used; a read or write outside
the session's directory that succeeded; a model other than the pinned one; a secret in the stream;
a message from anyone but the runner's fixed files; or, at the turn's end, a passed copy (§2.2:
`base.json` or a `clean/*.json` file) in the session's directory that is changed or gone. A change
to `done.md`, `plan.md` or any other file of the session's own is never an audit failure. A guard
refusal is recorded, not a failure: it is the sandbox doing its job. A mention of a gate or an
answer is recorded and published, as in R-PG-02's authoring record
(`experiments/R-PG-02/fresh-authoring/`, each session's audit).

**Caps, fixed now.**
- **Across the experiment:** at most 2 restarts per author pair, so 3 attempts in all.
- **Per attempt of a pair** (a restart sets these back to zero, since every session of the pair is
  new):
  - at most 4 fact rounds per batch after its first check;
  - at most 2 replacements per error session (X2, Y2, Z2; and C, for pair X);
  - X3 at most once.
- **Per session:** at most 2 usage-limit resumes, counted apart from the caps above.
- **Per turn, for infrastructure cuts:** 3 resumes on the retry ladder, then 3 more after the owner
  confirms that the service is back; beyond that, each further resume of the same turn only on the
  owner's word, recorded (above). None of them spends a cap.

**When a cap is reached.**
- **For the primary:** authoring stops for the owner. Going on in any changed form (another size,
  another brief, other rules) is an amendment, which is a new experiment. No review has run, so no
  number is seen.
- **For `fresh-v2-s`** (C's third session fails, or X3's route ends at its cap): the `standard`
  class is not run. §6.4 item 9 says so, and §8's class rule reads "not measured". The primary is
  untouched.

**"Set filled"** commits every manifest digest after its corpus passes. From then on no item is
replaced, re-injected or dropped (R5).

### 2.6 What is not used, and why

- **The tuning set (R-PG-02's fresh set) is never a test set again.** The fixed rubrics were tuned
  on it. It appears only as practice: Q4's anchor (§6.3); blocks `p1` and `p2`'s set (§6.4
  item 10), for A1 and B, which were never tuned on it, and for A2 as the sheet-matched practice
  figure; and the false-finding control's cases (§7).
- **R-PG-02's old set is not run.** It has answered its question, and its corpus is R-PG-01's.
- **No pre-run domain check of the twins by a model judge.** In its place:
  - the rules of Appendix A and the mechanical checks;
  - the blind reading of every rejection after the run, pooled across arms (§7).

  A judge that grades twins against the same standards the specialists read would shape the twins
  toward the specialists, and the judges of this kind agreed with nearly every finding put to them
  in practice. A flawed twin matters to an arm contrast only where some arm refuses it, and §7
  reads exactly those cases, blind to the arm.

## 3. What is under test

### 3.1 The arms, and what holds them

| Arm | Checkout | Rubric sha256 on every review line | Generalist? |
|---|---|---|---|
| **A2** | `R` | control `73a1311b5ea85f5dedb82104f099ae2d4577552c351c970c23ece5bc7945dae0`; electrical `f0fcbc2ac8ffa864bf6f5d1867a0d2150672ccf61bed06276b80e6036bddcdd6`; firmware `16bb9fa6cf0e9b0de5216bc265faedfd32b69565e457e2e013f3e69321a689d3`; mechanical `cee5a478d535bcb58cf1d1493a1563b023dac94b7eca37a17baec1719f98e212` | no |
| **A1** | `R_K` | control `08a5cfbc1b6729843bd5f6d8cad5c3596faaeecc596fb472230905815a2677d6`; electrical `5ca8c13584ac896abda9825d52a0a3b8177866024e68249ad75375c59086b445`; firmware `614ad78c9ebceba6903fba31267801e970162d80fbf10df0713064c99377c25e`; mechanical `ee68896b4adce53b1e66330d1c8072e5afbac66a547d077abd4d0325ef8dadf8` (R-PG-02 §3, K) | no |
| **B** | `R_K` | `generalist_of` K's rubrics: control `a75561161064cf498890301ab8356d6e2bd332e7754e4ee6d3cb8386ad584e54`; electrical `12f3b842dd8dd98033b6de50e7449ada993a50f231216ca4c1cff229f2bedab5`; firmware `f22093b19159b730a1eb030834ea2fd975ce18f22e696b38406a3862fdde756a`; mechanical `5f76f510724122fea9c2cc1125892e09c5ac84ef2735fe0ef34a1d0805867e5e` | yes (`--generalist`) |

- **B is R-PG-02's generalist byte for byte.** Built from the fixed rubrics, the generalist differs
  only by the promotion's canary comment line, because the fix lies wholly inside the two domain
  sections that `generalist_of` removes. So no second generalist arm is needed.
- **The drafter's check:** with the code at `fc28f32`, `generalist_of` gives the four digests above
  from K's files.
- **The freeze is identified by these rubric digests,** not by a commit SHA: the commit the cycle
  ran from was rebased before it merged.
- **The knowledge each arm reads is pinned too,** as git trees, identical in `R` and `R_K`:

  | Tree | git tree id |
  |---|---|
  | `knowledge/control` | `260dc0d9deac61166849fa078d1550f0e6c82c06` |
  | `knowledge/electrical` | `64d5ca418c65afff5a67fa624cfe35b9f7f90b7d` |
  | `knowledge/firmware` | `66a6eac5c76b9a472ec5c78867ae5f741d17b86a` |
  | `knowledge/mechanical` | `14cde0b1c32875893a626c8358824fb52c363378` |
  | `knowledge/cross` | `aa03dc8c7ff21529431007c9acdd637548f5f983` |

  - Each is the same at R-PG-02's run commit `0936f1f`, at `d93be3a` and at `fc28f32` (checked by
    this file's reviser).
  - A2 and A1 read their role's tree; B reads `knowledge/cross`, as R-PG-02's generalist did.
  - Each review's packet records the digests of the knowledge files it read (`knowledge_sha256`),
    as it records the rubric's. The tally checks both against the review's arm and role.
    "Commits filled" names the record that carries them. If no record does, the check rests on
    the launch's tree pins alone, and "Commits filled" says so.

### 3.2 The run commit `R` and its rubric-only sibling `R_K`

- **`R`:**
  - descends from master at or after `fc28f32`;
  - holds the converter's follow-up fixes, the instrument change the `standard` class needs (a fifth
    error class, and a completeness rule for a corpus of that class alone), and this experiment's
    scripts;
  - touches neither the four rubrics nor `knowledge/promotions.jsonl`, and holds §3.1's five
    knowledge trees;
  - **A test shows every earlier corpus still loads byte for byte.**
- **`R_K`:** `R` plus one commit that **restores five paths** to K's state. It is not a revert of
  `d93be3a`: that commit also changed a test file, a sixth path, and the launch refuses six. The
  five:
  - the four rubric files, each restored to its bytes at `d93be3a`'s parent `1a7bb0d` (K's
    digests, §3.1);
  - `knowledge/promotions.jsonl`, with exactly the four lines `d93be3a` added removed.

  The rubric loader accepts only the bytes a role's last promotion names, so this is how K's
  rubrics load under today's code. `R_K` is never merged.
- **The launch script refuses:**
  - a `git diff --name-only R R_K` that is not exactly those five paths;
  - an `R_K` `knowledge/promotions.jsonl` that is not `R`'s with exactly those four lines removed,
    compared **by content**, line for line (a name-only diff does not check content);
  - a rubric digest or a `generalist_of` digest that is not §3.1's;
  - a knowledge tree that is not §3.1's, in either checkout;
  - any other tree, blob or digest that differs from "Commits filled".
- **"One commit for all arms"** therefore reads: one code tree for all arms, with only the rubric
  bytes differing between `R` and `R_K`.

### 3.3 Identical in every arm, and what differs from R-PG-02 and the practice cycle

**Identical in every arm:**
- the instrument, gate, reviewers' code and catalogue trees;
- the account's three fixed paragraphs, `ACCOUNT_SHA256`
  `8580efd05af6fd2d304810950f00bb2c3d462302dddfd00b1d12373e340ab838`, as K and the fixed
  configuration were tuned with, **unchanged**;
- the sheet sentence, the sheet, the corpora and the parameters;
- the binary, the machine and the account;
- within a block, the hours.

**What differs from R-PG-02's run (`0936f1f`) and the practice cycle's (`eae78c0`, and
`gr2-r1-run-tree` = `8c51f48`, which is `eae78c0` plus the promotion):**
- **the code.** "Commits filled" publishes `code_changes.py`'s list (§13). For each of the three
  old trees, it lists every commit from that tree to `R` (and from `R` to `R_K`) that touched any
  file under `src/physgate/`, or `pyproject.toml` or `uv.lock`. Inside the list, every file the
  run's processes load is marked (below). The list replaces any list made by hand. It is known now
  to hold PR #69's sheet fields in the instrument, the converter's follow-up fixes to the
  instrument's corpus loader, the `standard` class, changes to the orchestrator's `cli`,
  `decompose`, `events` and `run_config`, and changes to the hook layer's `cli`, `registry` and
  `survivors`;
- **the sheet.** Its converter lies outside `src/physgate/`; the converter's follow-up fixes also
  change the instrument's corpus loader (it now refuses null and blank fields), which the list
  shows. The converter changes the sheet's bytes, which "Sheet filled" pins (§2.4).

**What the list holds.** Per commit: its sha, its PR number where it has one, its subject, and
every path it touched under `src/physgate/` (at `fc28f32`, 175 Python files and 11 others), or
`pyproject.toml` or `uv.lock`. Beside it is `git diff --stat` of the same paths between the two
trees. So the list does not depend on any walk.

**How the list marks the files the run loads.** Every review runs three kinds of process, and the
walk is seeded with each one's entry point:
- **the inject runner,** every module of the package `physgate.evaluation.inject`;
- **the `physgate` console script,** `physgate.cli` (`pyproject.toml`'s `[project.scripts]`),
  through which the run starts and each review installs its hooks (`physgate hooks install`);
- **the hook process of every review session,** `python -I -m physgate.hooks`, so
  `physgate.hooks.__main__`, which loads the hook registry and every handler it names.

`code_changes.py` reads each file with Python's `ast` module, at the old tree and at `R`. It follows
every `import` and `from … import` that names a `physgate` module, at any depth (inside a function,
or under `if TYPE_CHECKING:`, so the mark errs toward more files), until no new file is found. Its
resolution rules:
- `import p.m` and `from p.m import x` resolve to `p/m.py`, or to `p/m/__init__.py` for a package;
- `from p import m` also resolves to `p/m.py` or `p/m/__init__.py` where one exists, since `m` then
  names a submodule;
- the `__init__.py` of every parent package of a module reached counts, since Python runs it on
  import (`physgate/__init__.py` included);
- a relative import resolves against the importing module's package by the same rules (none exists
  at the trees below).

A Python file is marked **loaded** if the walk reaches it at the old tree or at `R`. Every
non-Python file under `src/physgate/` is marked **may be read at run time** (among them
`hooks/trampoline.sh`, through which each hook process starts), and so are `pyproject.toml` and
`uv.lock`.

**The dynamic-import stop, narrowed.** Any of these in a loaded file stops the script, since the
mark could then miss a file:
- a call of `importlib.import_module`, `importlib.__import__`, `__import__`, `runpy.run_module` or
  `runpy.run_path` whose module argument is not a string literal, under any name the function is
  called by (an alias such as `from importlib import import_module as …` included);
- a call of the built-in `exec`, `eval` or `compile` whose code argument is not a string literal;
- a call of `importlib.util.spec_from_file_location`, or of a loader's `exec_module` (a module
  loaded by its file path);
- a call of `importlib.metadata.entry_points` (a module loaded by a plug-in name);
- a launch by `-m` of a `physgate` module whose file the walk does not reach, written as one string
  (`-m physgate.<x>`) or as `-m` followed by the module's name in a list.

An import call whose argument is a literal `physgate` name is followed as an import.
`importlib.util.find_spec` locates a module without importing it (the hook layer's sentinel uses it
this way), so it is not a dynamic import. A stop is a failed precondition (§11).

**Measured before the freeze** (by script, `ast` only, read through `git show`): at `0936f1f`,
`eae78c0`, `8c51f48`, `fc28f32` and the follow-up fixes' head `022cb4e`, no call of the first kind
exists and no relative import. A search of `src/physgate` found none of the other kinds, besides
launches by `-m` of two literal modules: `physgate.hooks`, the hook process (a seed), and
`physgate.ui.assets`, a build step, which the walk reaches. The walk marks 173 of the 175 Python
files at `fc28f32` (169 of 171 at the three practice trees); the two left are
`physgate.bypass_corpus` and `physgate.knowledge.ceiling`. Seeded with the inject package alone, it
would mark 136.

**The prompt identity check covers the packet only.** It cannot see a difference in the runtime
(how a stream is read, how a session is started or retried). The list above is the only record of
those, and §9 item 3 names it. Q4 compares A2 across trees (the kept round at `8c51f48`, fresh-v2
at `R`), so the list is Q4's record too.

**The prompt identity check** (§13). Before launch, one review packet per role and arm is built,
at the run trees and at the trees the practice cycle ran, where the same rubrics load:
- **A2** at `R` against the kept round's tree, the tag `gr2-r1-run-tree` (`8c51f48`), where the
  fixed rubrics load;
- **A1 and B** at `R_K` against the noise run's tree `eae78c0`, where K's rubrics load (B built
  with `--generalist` at both).

**Both trees are fed the same corpus bytes:** the instrument's own test corpus, copied once from
`R`, so that only the instrument can differ. If the older tree's loader refuses a field the
complete sheet adds (`given`, `note`), both trees are fed the same copy with its sheet in the older
form (the same rows with only their numbers), and this is recorded.

Each pair compared holds the same rubric and the same corpus bytes, and both trees copy the sheet
byte for byte. So the packets **must differ only in the account's sheet sentence,** where the two
trees word it differently for the same sheet. Any other difference, the rubric included, stops the
launch. It is a failed precondition (§11): it is fixed only if the fix changes neither this file
nor a pinned digest. Otherwise the experiment stops, and an amendment is a new experiment.

### 3.4 Parameters and runtime

- **Parameters:** R-PG-02's `params_fresh.json` in every field except `lanes`:
  - `claude-sonnet-5` for every role;
  - effort `high`; max output tokens 64,000; token ceiling 400,000;
  - bounds: 80 turns, 4,500 s, 0 binary retries;
  - `infra_retry_delays_s` [60, 900, 2700];
  - a lane-wide pause after 3 consecutive infrastructure failures, for 900 s;
  - 1 repair resume.
- **Lanes:** A2 3, A1 3, B 2, which is 8 in all, R-PG-02's budget (§10).
- **Runtime:** one ARM virtual machine (Linux arm64, 2 cores, 12 GB); Claude Code `2.1.301`,
  sha256 `1e119036a802d359ba5f9886428e031586e8796f7a858d5a8ee179ac7b8604f0`; auth mode
  `subscription`, on the run account (§10).
- **Seeds:** §14.

## 4. Definitions

**The unit is the item** (an injected artefact or a clean twin). An item counts once.

### 4.1 Rejected for the right reason (R), over the injected items

**Primary: the common rule, the same for every arm.** An injected item counts in R when:
- its review is a `fail`; **and**
- it cites (`unmet` or `confirmed`, or as its failing item) an item of the **common cell**; **and**
- its twin's review does not cite that item.

**The common cell** is the role's error cell for the item's class (R-PG-02 §4.1's table, paired
column, verbatim), together with the role's Section 1 consistency line: control A7, electrical
EA-9, firmware AC-9, mechanical MA-10.
- The item ids are identical in K's and the fixed rubrics.
- For B, which has no Section 2 or 3, the cell reduces to the Section 1 line, so B's common R is its
  R-PG-02 R.
- The rule is computed through R-PG-02's frozen `naming`.

**Secondary: the strict cell rule.** R-PG-02's paired rule, the error cell without the Section 1
line, for A1 and A2. B is unchanged.

**Descriptive: the locating rule.**
- The review is a `fail`;
- some rejecting line's evidence holds a changed node's id as a whole word, or a changed quantity's
  name with its node (R-PG-02's `names_pair`);
- no rejecting line of the twin's review does.

**The `standard` class (secondary)** has no row in R-PG-02's table. Its common cell is the role's
Section 2 items, all of them, together with the Section 1 line. The locating rule is printed beside
it, and the class rule's catch half must hold under both (§8), since the common cell is far wider
for A2 here than for B.

**The limits, stated now.**
- The Section 1 line can be cited for any reason. The twin condition removes reasons the two
  revisions share, but the rule is looser than a locating rule.
- The reading's planted-error count (§7) is printed beside every R.

### 4.2 Accepted (A), over the clean twins

- A twin counts in A when its review's verdict is `pass`.
- `blocked` and `review_unavailable` are **not** accepted.
- **Beside it:** R-PG-02's sheet-flaw rejections (§4.2 there), computed by the frozen rule, with A
  and J without them.

### 4.3 Discrimination (J)

**J = R + A − 1,** with R and A as fractions of the pairs. A layer that rejects everything has
J = 0. The raw reject rate is printed beside.

### 4.4 No verdict, and unscored items

As R-PG-02 §4.4:
- `blocked` and `review_unavailable` (including `invalid_verdict`) count against the arm in both
  directions;
- they are never re-drawn;
- figures among items with a verdict, and the range if each had gone either way, are printed
  beside;
- unscored items count against the arm in both directions.

## 5. Rules of fair play

- **R1 First honest version.**
  - This file is frozen before any file of `fresh-v2` exists.
  - Rubrics, generalist, instrument, gate and parameters are those of "Commits filled". Nothing
    changes after it.
  - An instrument defect found after a number is seen is a deviation, in §11's narrow sense.
- **R2 Blindness.**
  - The authors: §2.2.
  - The reviewers see the neutral trajectory, held to `require_blind` before each review: no
    telltale word, no field of a result or corpus, not the item's own id.
  - The reality reading is blind to arm and side (§7).
- **R3 Nothing reachable.** Before every block, a scan (R-PG-02 R3's rule) proves that no copy of
  any of these is readable from where a reviewer runs:
  - `fresh-v2`, the tuning set (`fresh-v1`), practice/v1, `fresh-v1c`;
  - R-PG-01b's corpora and runs, on the same machine and account;
  - the practice cycle's runs on the run machine and R-PG-02's runs;
  - **R-PG-03's own earlier attempts:** void block attempts, discarded authoring files (§2.5),
    the authoring sessions' directories, and any reality packet;
  - the dry-run results, or any answer key.

  Each review root is new and outside every checkout. A hit stops the block.
- **R4 Twin precondition:** §2.5 item 2. It is held again at launch.
- **R5 No re-draw** after "Set filled". The denominators are 120 per direction (primary) and 10
  (`standard`).
- **R6 One registered run per arm,** per block.
  - The gate is deterministic: a second gate pass over every corpus must give byte-identical
    records, and A1's and B's gate records must equal A2's.
- **R7 Exposure, disclosed before the freeze** (carried in `RESULT.md` beside the headline):
  1. The planner of the practice cycle read R-PG-02's published tally, including each fresh item's
     cited rubric item ids for both arms, before reading any review.
  2. **The practice cycle read** every review record of R-PG-02's fresh-set runs, of its own noise
     run and kept round, and of a transfer run on practice/v1. The agent that drafted the two rubric
     rules read only kinds and counts, never review text or item ids. The owner promoted the rules
     having seen practice results.
  3. **Appendix A's rules** were written by this file's drafter from the practice readings' defect
     lists. They name no practice item, node or number, but they shape `fresh-v2` against the
     defects practice showed (§2.3, §9 item 1). Exactly:
     - every defect came from reading reviews of specialist runs; **no generalist review was
       read** for them;
     - **three more rules were drafted from the three false rejects the fixed rubrics newly made**
       on the tuning set (twins a28, a18 and a21: where a quantity acts, the duty-limit
       convention, node order). They would have cleared the new set of ambiguities the arm under
       test misread. **The owner left them out before authoring** (24.10.2026), so they are not in
       `rules.md` and no author reads them;
     - the eight rules given lean in both directions, rule by rule (§2.3's table): two toward the
       specialists against the generalist, one toward the generalist, two toward K against the
       fixed rubrics, the rest neutral on their instance or not known;
     - neither Q4 nor its set-adjusted reading can detect this shaping.
  4. **This file's drafter read:**
     - the practice cycle's plan, close-out, rejection reading, transfer reading, sheet-defect check,
       rulings, quota ledger and round log;
     - R-PG-02's criteria, result, scripts, briefs and authoring records;
     - R-LAW-01's criteria;
     - R-PG-01b's criteria in their pre-freeze draft (sheet treatment, reading, decisions,
       account), which are blind to R-PG-01's result.

     **It computed, by script,** this file's noise and power figures from the practice cycle's
     per-item tallies (ids and 0/1 outcomes). It **probed** the converter and `generalist_of` in a
     scratch directory (counts and digests only).

     **It did not read** any R-PG-01 file, any corpus file by hand, or any review record. **It
     read review text only as quoted** in the rejection and transfer readings, which quote it
     verbatim.

     **This file's first adversarial reviewer** (23.10.2026) checked the commits, the digests and
     the arithmetic by script. It called no model, read no R-PG-01 material and no corpus by hand,
     and read of the authors' table only its prose lines, two rows and the row ids.

     **This file's first reviser** (24.10.2026), who answered that review, read:
     - this draft, the review, and the rulings of the owner and the orchestrator on R-PG-03;
     - the practice cycle's plan, close-out, rejection reading (its findings and summary, not its
       appendix of rows), transfer reading and rulings; and, by script, the rejection reading's
       rows for the twins and for the injected item a22, without their verbatim quotes (run, item,
       verdict, failing item id, class, and the reader's own note on why a line was wrong);
     - R-PG-01b's frozen criteria, for the sequencing, the quota ledger, decision D3 and the
       reality controls only, and its ledger script's header;
     - R-PG-02's fair-play rules and its authoring record's index; R-LAW-01's reality rules, its
       adjudication prompt and its run labels;
     - the authors' table's prose lines, and the quantity text, value and note of the rows §2.5
       names, by script; and, of R-PG-02's practice sheet (`bc1e5ec1…`), whether 25 named rows give
       a number, by script;
     - the converter's prose handling, the instrument's packet fields and account sentences, and
       git trees, diffs and the promotion lines of `d93be3a`.

     It read no R-PG-01 file, no corpus by hand and no review record, and read review text only as
     quoted in the readings.

     **This file's second adversarial reviewer** (24.10.2026, a delta review) read:
     - in full: this draft, its copy before the first revision, and the first review; and the
       practice cycle's rejection reading, including its appendix of twin rows with their
       verbatim quotes;
     - in part: the practice cycle's premise check, quota ledger, close-out, transfer reading (three
       of its rows, a01, a12 and a14, with quotes), round log and run plan; R-PG-01b's criteria
       (§6, §10–§12 and the outline); R-LAW-01's criteria (the outline and §2.3, with its reality
       prompt and schema); R-PG-02's criteria (§4.2's sheet-flaw paragraph and R7), its authoring
       record's README, briefs (headings and reading lists) and continuation digests; the rulings
       on this experiment, which also carry R-LAW-01's figures; the project's current-state notes;
       and the maintenance log's entry on the converter's follow-up fixes, with their counts proof;
     - by script only: of the authors' table, the row ids, matched words and the row id in one
       prose line; of `knowledge/promotions.jsonl`, fields only; the vocabulary's limit-like names;
     - code and git: the rubrics' headings and the electrical rubric's Section 1; git trees,
       digests, diffs and logs; the instrument's account parts and part of its packet code; the
       converter's refusal text at the follow-up fixes' head.

     It read no R-PG-01 file, no corpus by hand, no review record and no secret, called no model and
     ran no experiment script.

     **This file's second reviser** (24.10.2026), who answered that review, read:
     - this draft, its copy before this revision, both reviews, and the owner's decisions and the
       rulings of the orchestrator on this experiment (whose file also carries R-LAW-01's and
       R-PG-01b's run figures);
     - of the practice cycle's rejection reading: its breakdown of twin rejections, its injected
       items, its five named twins (with the short review quotes they carry) and its summary and
       defect list. Not its appendix of rows. Also its quota ledger;
     - of R-PG-01b's frozen criteria: its order, and its account, cost and quota section;
     - the maintenance log's six entries from the converter's fix to its follow-up fixes; the
       follow-up fixes' counts proofs and override proofs (outcomes, counts and digests only); and
       the converter's lines on its prose options and its usage, at the follow-up fixes' head;
     - R-PG-02's authoring record's README and criteria, only the lines that name the audits and
       R7;
     - by script: the vocabulary's limit-like names; the sha256 of fresh-v1's authors' table and
       sheet; the import lines of the instrument's inject package; git branches, logs and file
       lists.

     It read no R-PG-01 file, no corpus by hand, no review record and no secret, read review text
     only as quoted in the rejection reading, and called no model.

     **This file's third adversarial reviewer** (24.10.2026, a delta review) read:
     - in full: this draft and its copy before the second revision (by diff); the first and second
       reviews; the rulings on this experiment, which also carry R-LAW-01's figures and R-PG-01b's
       status; and the converter's follow-up fixes' override proof, counts proof and override test
       list;
     - in part: R-PG-01b's criteria (the header, and §11's account and quota lines); R-LAW-01's
       criteria (the headings and §2.3); R-PG-02's criteria (R7's item list) and its `tally.py`
       (the bootstrap functions); the maintenance log's lines on the follow-up fixes' scope;
     - by script only: of the practice cycle's rejection reading, the co-occurrence counts of the
       false-finding control's case items and their rubric ids, and the counts of the run labels;
       the vocabulary's limit-like names; the sha256 and byte counts of the authors' tables and of
       fresh-v1's `sources.json`, and the one-word edit; the keys of `params_fresh.json`;
     - code and git: the converter's prose-digest code and options at `022cb4e`; the messages of
       `74e3710` and `a70f9d5`, and the dispatch part of `a70f9d5`; the import and command lines of
       the hook layer's `sentinel`, `settings`, `__main__` and `registry`, of `physgate/cli.py`, of
       the orchestrator's `dispatch` and `run_config`, and of the reviewer's `claude.py`; an AST
       probe of the import closure at five trees (counts and module names only); git logs, diffs
       and the worktree list.

     It read no R-PG-01 file, no corpus by hand, no review record and no `.env`, called no model and
     ran no experiment script.

     **This file's third reviser** (24.10.2026), who answered that review, read:
     - this draft, its copies before the second and the third revision (§14 by diff), the three
       reviews, and the rulings on this experiment (lines that also carry R-LAW-01's and R-PG-01b's
       figures);
     - R-PG-01b's frozen criteria: its outline and §10–§12;
     - R-LAW-01's criteria: §2.2–§2.4 and the reality prompt and schema (Appendix E);
     - R-PG-02's `tally.py` (the bootstrap functions) and the lines of its criteria that name P5;
     - code and git, read-only through `git show`: the import lines of `physgate/cli.py` and of the
       hook layer's `__main__` and `registry`; `sentinel`'s `find_spec` lines; the orchestrator's
       `role_python` probe string; the hook command in the hook layer's `settings`; the reviewer's
       hook-install lines; `pyproject.toml`'s scripts; the file lists of `74e3710`, `a70f9d5` and
       `d93be3a`; an AST probe of the import closure at five trees (counts and module names only);
       and the sha256 and byte counts of the four `standards.md` files, by script, never their
       text.

     It read no R-PG-01 file, no corpus by hand, no review record and no `.env`, read no review
     text, and called no model.

     **This file's fourth adversarial reviewer** (24.10.2026, a narrow check) read:
     - in full: this draft and its copy before the third revision (by diff); the third review; and
       the rulings on this experiment, which also carry R-LAW-01's and R-PG-01b's status;
     - in part: the copy before the second revision (§8, §14 and the appendices by diff, the
       owner's decisions 1, 2 and 7, and a search for dates and the sheet digest); R-LAW-01's
       criteria (§2.2 and §2.3), its `law_extract.py` (the `failing_item` lines) and its
       `law_reality.py` (the seeding lines); R-PG-01b's criteria (the headings, §11's timing and
       weekly lines, and a search of §12 and §15); R-PG-02's `tally.py` (the bootstrap functions);
     - code and git, read-only: an AST probe of the import closure at five trees (counts and module
       names); a search of `src/physgate` for dynamic-import and `-m` patterns; the exec lines of
       the hook layer's `trampoline.sh`, the hook command in its `settings`, and the
       orchestrator's `role_python` probe string; `pyproject.toml`'s scripts; the sha256 and byte
       counts of the four `standards.md` files, by script, never their text; the file names of
       the knowledge trees; the file lists of `74e3710` and `a70f9d5`; and the PR numbers in commit
       subjects.

     It read no R-PG-01 file, no corpus, no review record and no `.env`, called no model and ran no
     experiment script.

     **This file's fourth reviser** (24.10.2026), who answered that review, read:
     - this draft and the fourth review in full; of the third review, its checks and its finding
       on the five keys; and the rulings on this experiment (lines that also carry R-LAW-01's and
       R-PG-01b's status);
     - R-LAW-01's criteria (§2.1–§2.3), its `law_extract.py` in full, the packet-cutting lines of
       its `law_reality.py`, and its recorded input digests (their keys); R-PG-02's `tally.py`
       (`boot` and `drop_interval`);
     - of the practice cycle's rejection reading, by script only: its field names, the run, item,
       side, class and rubric item ids of its rows, its table headers, and counts of id-shaped
       tokens; never a quote, a note or a decisive sentence;
     - of the practice cycle's review records (the kept round and the noise run), by script only:
       the five keys' line counts, with the records held to R-LAW-01's recorded digests (§7's
       probe), and the names of the files in the two run directories; never a line's text;
     - the file names of the practice cycle's evidence, the run paths its scoring script names, and
       the file names of `physgate.ui.assets` at five trees and the lines that name it.

     It read no R-PG-01 file, no corpus by hand, no review record by hand and no `.env`, read no
     review text, called no model, and ran no script but §7's probe and the counts above.
  5. **The tuning set shares** the parts sheet, the brief family, the author model and the account
     text with `fresh-v2`. The tuners know `fresh-v2`'s input distribution, not its items.
  6. **The authors use the gate's vocabulary** (R-PG-02 R7 item 4).
  7. **Every message to an author is fixed here** (Appendix B), or is a script's facts.
- **R8 Lanes, blocks and order.**
  - Retries, the lane pause and the repair resume are R-PG-02 R8's.
  - **A block** is one corpus reviewed by all its arms at once: A2, A1 and B, each a separate run,
    each in its own directory and review root, starting within one minute of each other. The launch
    script refuses to start one alone; if one stops in its first minute, the block's attempt is void.
  - All arms of a block use the block's seed, so A2 and A1, with 3 lanes each, have the same lane
    plan, and an item and its twin run on the same lane in every arm.
  - The block order is fixed (§10).
  - A void block is re-attempted whole, in new directories, and **never resumed**.
  - **A void attempt is never read or tallied.** Only its counts are kept: sessions, tokens, stops,
    cut reads and digests (the ledger, §10). Its records are kept and published as they are.
  - **Nothing is tallied, read or counted by verdict until the last block has ended** and passed
    its stream check. Between blocks only stream-level facts are computed (sessions, tokens, stops,
    cut reads, rubric and knowledge digests). So every owner ruling made during the run (§11's
    third void attempt, a raised W5) is made blind to the outcome.
- **R9 The tuning record is published:** the practice cycle's runs' tallies, its noise run, its kept
  round, its transfer check and its readings' rows, with every attempt (§12).
  - **Before it is published,** private run labels, private paths and private document and spec
    ids are replaced by public names, by a script. The script's name map is published with it, so
    every public name traces to one record.
  - Review text inside the readings' rows is published as quoted.

## 6. Metrics

### 6.1 Primary

- **R, A and J for each arm on the 120 pairs, under the common rule.**
  - R and A: Wilson 95 %.
  - J: a bootstrap over pairs, 10,000 draws, seed 13, the 2.5th and 97.5th percentiles, **stratified
    by author pair into three strata of 40** (X's 40, Y's 40 and Z's 40, each resampled with
    replacement within itself, so every draw holds 40 pairs of each).
- **The two paired contrasts on the same pairs, each arm's pairs resampled jointly** (one draw of
  pairs serves all three arms), in the same three strata:
  - **J_A2 − J_A1** (the fix);
  - **J_A2 − J_B** (pairing, R-PG-02's P4 asked again).
- **The cost ratio** of A2 to B, and of A1 to B: tokens and USD per review from the binary's own
  totals.

### 6.2 Run-to-run noise, and why one run per arm

**What practice measured.** Two runs of K on the tuning set (40 pairs, the same rubrics, model and
parameters). They were two days apart, and they also differed in tree (by a stream-halt fix), lane
count and account. So the figures below are an upper bound on pure run-to-run noise:
- 8 of 40 twins changed acceptance;
- 7 of 40 injected items changed under the strict rule, and 3 under the common rule;
- the net counts moved by at most 2;
- J under the common rule differed by −0.025, interval [−0.20, 0.15]. This is the width of a
  contrast when nothing differs.

**What this file does with it.**
- **The intervals already hold it.** Each item gives one draw per arm, so the pair bootstrap's
  spread includes run-to-run noise. A single run is wider, not biased.
- **The noise band** is printed beside every contrast: ±0.175 at 40 pairs, about ±0.10 at 120
  (scaled by the square root of the pair count). A point inside it is labelled "within run-to-run
  noise". **The label is descriptive.** Decisions use
  the intervals (§8).
- **No single item's flip is read as an effect.** The per-item table of A2 against A1 is printed
  with practice's churn beside it (about 20 % of twins).
- **Why more pairs and not a second run.** On the tuning set, run-to-run noise was about 40 % of a
  single-run contrast's variance (0.51 per pair for the fixed rubrics against K; 0.37 for the fixed
  rubrics against the generalist). Item-to-item difference was the rest.
  - A second run shrinks only the noise share. Doubling the pairs shrinks all of it.
  - The projected 95 % half-widths (the drafter's projection; an assumption, not a measurement):

  | Design | fixed − K | fixed − generalist |
  |---|---|---|
  | 40 pairs, 1 run | ±0.22 | ±0.19 |
  | 40 pairs, 2 runs | ±0.20 | ±0.17 |
  | 80 pairs, 1 run | ±0.16 | ±0.13 |
  | 80 pairs, 2 runs | ±0.14 | ±0.12 |
  | **120 pairs, 1 run (this file)** | **±0.13** | **±0.11** |

### 6.3 The criteria

**"Clearly"** means the 95 % interval lies wholly above zero.

| # | Criterion | Form | Why this form |
|---|---|---|---|
| **Q1** | **The fix works** | J_A2 − J_A1's interval lies wholly above 0, **and** A_A2 ≥ A_A1, **and** R_A2 is no more than 5 % of the pairs (6 of 120) below R_A1, under both the common and the strict rule | The fix was tuned to raise acceptance. A gain that only moves A while losing catches is not a gain (R-PG-02 §6). |
| **Q2** | **Pairing adds value** | J_A2 − J_B's interval lies wholly above 0 | R-PG-02's P4, asked again on new material after the fix. |
| **Q3** | **The specialists are not shown worse** | the lower end of J_A2 − J_B's interval lies above **−0.15** | A non-inferiority margin, set before the size was chosen and kept. At 120 pairs the projected half-width of J_A2 − J_B is about ±0.11, so the set resolves a margin somewhat smaller than 0.15. The margin says what difference is taken to matter. It is a judgement, labelled as one. |
| **Q4** | **The fix was not tailored to practice** | P5's form (R-PG-02 §6): **tailoring** if the drop J_A2(tuning set) − J_A2(fresh-v2) has an interval wholly above 0; **possible tailoring** if the point drop is over 0.15 and the interval holds 0 | The practice figure is the kept round's on the tuning set: J common 0.775. Each set's pairs are resampled on its own, **unstratified**: the frozen `drop_interval`, as R-PG-02's P5. |

- **Q4's set-adjusted reading, printed beside and never replacing Q4:**
  - the reading is (the fixed rubrics' drop) − (K's drop), where K's practice figure is the
    per-item mean of K's two runs on the tuning set, which were never tuned on it;
  - it separates a shift of the set (another base, authors, rules and sheet) from tailoring;
  - if Q4 flags but this reading's interval holds 0 and its point is at most 0.15, the label
    "a shift of the set, not shown to be tailoring" is printed beside.
- **What Q4 cannot see, stated now.**
  - Q4's anchor was measured on the lossy sheet, and the kept round was kept exactly at its bar.
    The complete sheet alone can lower the measured drop, and so hide tailoring.
  - Shaping in how the new set was written (§2.3) is invisible to Q4 and to its set-adjusted
    reading alike.
- **The sheet-matched Q4, printed beside and never replacing Q4:** A2's drop from the tuning set
  with the complete sheet (blocks `p1` and `p2`) to `fresh-v2`, in Q4's form; and its set-adjusted
  form, with K's figure from the same blocks (A1's). Both sets then carry the complete sheet.
- **How the readings beside Q4 are resampled, fixed now.** Each is a difference of two drops over
  the same two sets, so each set's pairs are drawn once per draw and serve both arms of that set
  jointly: the tuning set's 40 pairs (A2's kept round and K's two-run mean; or A2 and A1 in blocks
  `p1` and `p2`), and `fresh-v2`'s 120 pairs (A2 and A1). The two sets are drawn independently of
  each other, and within each draw in the frozen `drop_interval`'s order: the tuning set's pairs
  first, then `fresh-v2`'s. **Unstratified,** like Q4, so that a reading beside Q4 differs from it
  in what it subtracts, not in how it resamples. The sheet-matched Q4 itself is the frozen
  `drop_interval`. Seed 13, 10,000 draws, a fresh stream for each interval, as the frozen `boot`.
- **What Q1's guards cost.** The power figures behind this design leave the guards out. The guard
  on R under the strict rule alone fails on noise about 8–20 % of the time: at 120 pairs about 21
  injected items differ between A2 and A1 by chance, an SD of about 4.6 on the net, against a
  tolerance of 6. So the projected chance of meeting Q1 is an upper bound. The guards stay, because
  a gain in A bought with lost catches is not a gain.
- **No criterion is met by A alone.**

### 6.4 Secondary (reported, never scored)

1. Each arm's R, A and J **per author pair, per block, per class and per role**, with the contrasts
   per author pair.
   - **The author pairs, compared, by a rule fixed now:** for each of the two primary contrasts
     (J_A2 − J_A1 and J_A2 − J_B), and for each pair P of X, Y and Z, the difference between the
     contrast on P's 40 pairs and the contrast on the other two pairs' 80, pooled. Each has its
     bootstrap interval (§6.1's draws; P's stratum against the other two strata).
   - That is **3 comparisons per contrast, 6 in all, uncorrected.** "The author pairs differ" is
     printed for a contrast if any of its three intervals excludes 0, with the count of
     comparisons named beside it. No other comparison between pairs is made.
   - These never enter §8's robustness label: at 40 pairs each interval is wider, which by itself
     favours row 3.
2. **The strict rule and the locating rule:** every primary figure and both contrasts under each.
3. **K against the generalist,** J_A1 − J_B: R-PG-02's P4 re-measured with the complete sheet on
   new material.
4. **No verdicts:** `blocked`, `review_unavailable` and `invalid_verdict` per arm, role and side,
   with causes; repair resumes; schema refusals per review.
5. **The per-item table of A2 against A1:** gained and lost, per side, with practice's churn beside.
6. **The reading (§7):** classes per arm and side, "other real flaw" counts, the three controls
   with their cases and the false-finding control's power, the confirmation pass (flaw-making
   lines confirmed and unconfirmed, per arm; on the class's twins, also confirmed twice), the
   flaw-making lines per refused twin review, per arm, the twin statuses, and the corrected-A
   reading in both ways.
7. **Cost:** tokens of all four classes and USD per arm, at the dated price sheet (a list-price
   equivalent, not a bill).
8. **The gate,** from A2's runs: R per class and role, with the evaluated counts beside passes, and
   "nothing in scope" (R-PG-02 §4.4 and §8). Its acceptance of the twins is 100 % by construction,
   and is not a result.
9. **The `standard` class:**
   - R, A and J per arm (10 pairs);
   - injected items one specialist arm names and B misses, and the reverse, under the common rule
     and under the locating rule;
   - **the class rule's halves** (§8): d, A2's credited catches B lacks less B's that A2 lacks,
     under the common rule and under the locating rule; and A2's and B's acceptance of the class's
     twins that §7 does not mark flawed (on this class, a line confirmed by two solo judgments), in
     both of §7's ways, with the raw acceptance of all 10 beside;
   - with n = 10, only large effects show;
   - if the class was not run (§2.5's caps), it is reported so, and §8 reads "not measured".
10. **Blocks `p1` and `p2` (R-PG-01b's decision D3):**
    - A2, A1 and B on the tuning set with the complete sheet (`fresh-v1c`), lanes 3, 3 and 2;
    - split by R-PG-02's two authoring batches (`a01`–`a20`, `a21`–`a40`, each 5 per class with
      distinct edges) into two corpora, so that each block fits §10's 5-hour projection;
    - their R, A and J, and per item against R-PG-02's published `a-fresh` and `b-fresh`;
    - labelled **"the sheet together with tree and day, not the sheet alone"**;
    - A2's figures there are the sheet-matched Q4's practice figure (§6.3);
    - the reading's classes on their reviews, with their own calibration and rejection controls
      (§7), which enter no label;
    - if `fresh-v1c` fails its acceptance checks (§2.5), the blocks are not run, and this item
      says so;
    - it enters no decision here.
11. **Wall clock and outage exposure:** per item start and end, retries, pauses, and each arm's span
    per block.

## 7. Every rejection read for its reason

Every review of A2, A1 and B whose outcome is `fail` or `blocked` gets one class. This covers the
injected items and the twins, primary and `standard`, and the reviews of blocks `p1` and `p2`. Those
are the tuning set's design versions, so they are read in packets of their own, never pooled with
`fresh-v2`'s, and their classes are reported only with §6.4 item 10.

- **Finding lines:** R-LAW-01 §2.2's definition, with every rubric item id replaced by `[rule]`.
- **A line's locus:** the (node, quantity) pairs it names, by R-LAW-01 §2.2's rule. It may be
  empty.
- **A changed pair:** R-LAW-01 §2.3's definition.
- **Reality:** R-LAW-01 §2.3's adjudication, used as R-PG-01b uses it.
  - **The prompt and schema are verbatim:** sha256 `41438ab78097d57a6e986b24f4f8071516fa36c1f0393f408874cd81adb23913`
    and `57c3852f8aa0adf9450de3504509b0bf95f85e78c55ff77b199a9c0998172324`.
  - **The model:** `claude-opus-5-5`, effort high, no tools, settings, servers or persistence, and an
    empty working directory.
  - **Line order.** Lines are numbered in this order: corpus (`fresh-v2-x1`, `-x2`, `-y1`, `-y2`,
    `-z1`, `-z2`, `-s`, then `fresh-v1c`'s batches `a01`–`a20` and `a21`–`a40`), item id, side
    (injected, then twin), arm (A2, A1, B), and the entry's position in its review's `result.items`
    (R-LAW-01 §2.2's order within a review). Every seeded shuffle and draw of this section starts
    from a list sorted by these numbers.
  - **One packet per design version** (per item and side), pooling the lines of all three arms, at
    most 12 lines a packet.
  - **How seed 37 cuts the packets.** One `random.Random(37)`, seeded once, serves `fresh-v2`'s
    design versions: its injected versions in line order, then its twins in line order. Each
    version's lines, in line order, are shuffled once by that stream and cut into consecutive
    packets. Blocks `p1` and `p2`'s versions are cut the same way by a second `random.Random(37)`,
    after `fresh-v2`'s, so that `fresh-v2`'s packets are the same whether or not those blocks run.
  - **Each packet holds:** the base's nodes, the revision's nodes, the corpus's `parts_sheet.md`
    verbatim (its prose included, disclosed as in R-PG-01b), and the lines.
  - **On the `standard` class, each packet also holds the domain's standards.** Every packet built
    for a design version of `fresh-v2-s`, on either side (its reading packets, its rejection-control
    packets and its confirmation packets), also holds its revision's assigned role's
    `knowledge/<domain>/standards.md` at `R`, verbatim, under a heading of its own after the parts
    sheet. `reality.py` refuses any other bytes than these, the blobs of §3.1's pinned trees:

    | Domain | sha256 of `knowledge/<domain>/standards.md` |
    |---|---|
    | control | `96ea261cf359b9b1a1cf2886dc56dbe378fb6c747fe7a37ea01eccbc1e31dff1` |
    | electrical | `adc3c4f2fbdf9a5dc07dd6cfd12e64301983b724cbdaf9f1693c9dd4bfa3cefb` |
    | firmware | `da7594e65d0aedacc57a84ac40849e39ad46454e077b98b84a40c65901fac4b1` |
    | mechanical | `2bc64f3d645a43727bd09ada264b6bf3ba2cb9c7cee65ed7f64fe575278227f0` |

    - **Why.** The class's errors break a rule these files state, and A2's refusals of the class's
      twins cite them. Without the file, the judge cannot check a standards claim, so whether a
      false one is confirmed would rest on the judge's agreeableness alone.
    - **Disclosed:** the prompt is unchanged; it already asks for a decision "from the packet". The
      file is what session C wrote the class's errors from, and what A2's and A1's reviewers of
      that role read (§3.1); B's reviewers never read it. Its presence tells the judge that
      standards matter here, and marks the packet as the domain-standard class's, on both sides
      alike. It states no arm or side, and both sides of a pair carry the same file. No packet of
      the four generic classes carries it.
  - **It never states** the arm, the side, the class, the expected check or a verdict. On the
    `standard` class, only the standards file's presence marks the packet as the class's, on both
    sides alike (above). Pooling keeps it blind to the arm, and ids are masked.

**Three controls.** Each has a bar; a bar that cannot be computed is "not checked".
- **Which packets they are computed on.** All three controls, and so the reliability that gates the
  corrected-A label and the class rule (§8), are computed on `fresh-v2`'s packets only, primary and
  `standard`. Blocks `p1` and `p2`'s reviews get a calibration and a rejection control of their
  own, by the same rules, on their own packets, with a draw of their own (below). These are printed
  with §6.4 item 10 and enter no label. The false-finding control is run once.
- **Calibration** (bar 70 %, at least 10 cases): of `fresh-v2`'s P reviews (below), the share whose
  error-item lines include a `true_flaw` line with origin `introduced` or `both`.
- **Rejection control** (bar 70 %, at least 10 cases): R-LAW-01 §2.3's rule exactly, drawn after
  the injected versions' first judgments exist. The eligible lines are injected-side lines judged
  `true_flaw` with origin `introduced` whose every locus pair is a changed pair. For each injected
  design version of `fresh-v2` that holds one, one is drawn, by one `random.Random(43)` seeded once,
  the versions taken in line order. A drawn line is put in a packet built for the clean twin, where
  the correct verdict is `not_a_flaw`. Blocks `p1` and `p2`'s draw is made the same way from their
  own versions, by a second `random.Random(43)`, after `fresh-v2`'s.
- **False-finding control** (new here; **bar 4 of 4**; its four cases are fixed now, and it is
  checked unless its records cannot be read at their recorded digests, below).
  - **Why.** The other two test an easy false finding: a line naming a planted value that the twin
    does not hold. The corrected-A reading turns on a harder one: a plausible but false finding on
    a correct design. In practice, judges of this kind agreed with nearly every finding put to them.
  - **The cases:** four findings the practice readings showed false, with arithmetic or with the
    authors' table, on correct twins of the tuning set:
    1. the kept round's review of twin a18, its line on item ES-14 (the stall current computed
       without the duty limit);
    2. the kept round's review of twin a21, its line on item D28 (drivers said to get no
       follow-up, though both were rewritten in the same revision);
    3. the kept round's review of twin a28, its line on item MS-3 (the motor-clamp reaction taken
       for the axle reaction);
    4. **a22, one fact of the table, two lines:** the 13 Hz data rate called invalid, though the
       authors' table gives it. The lines are the noise run's review of twin a22, its line on item
       DS-27; and the kept round's review of the injected item a22, its line on item DS-27, placed
       in the packet of twin a22, which holds the same value. **The case passes only if both of its
       lines pass,** so one fact counts once.
  - **How.** Each line is taken from the practice cycle's review records by script (by run, item,
    side and rubric item id), masked as every line is, and put alone in a packet built for its
    twin. The packet holds the tuning set's base, the clean revision, and the edited authors' table
    (`0573ef04…`) verbatim, the table every other packet of this reading carries; it differs from
    the tuning set's own table (`29f9568c…`) only in R6.05's one word. The packets are judged with
    the reading's own prompt, model and settings, after the reading's other packets.
  - **The five keys.** Each of the five lines is named by a key: run, item, side and rubric item
    id. The key is the practice reading's own record of the line: the run, the item and the side of
    the reading's row, and a rubric item the row gives for the finding it showed false. The records
    are R-LAW-01 §2.1's runs `round-1` (the kept round) and `repeat-K` (the noise run), held to the
    digests R-LAW-01 recorded for their files (its §2.4). A key's lines are counted under R-LAW-01
    §2.2's rule for which review line and which entries count. **A line is taken by its key
    alone,** never by its position in a review or by its text.
    - **Counted before the freeze** (a fact filled in this file before it was frozen, on
      24.10.2026, by the count-only probe `ff_key_probe.py`, sha256
      `d1def63279798ee19885647611bf0cd7f16e0617a397bb915e337e0953baf7ad`, which imports R-LAW-01's
      extractor unedited and printed counts only): **every key matched exactly one line.**
      - Case 1 (a18, ES-14): 1.
      - Case 2 (a21, D28): 1.
      - Case 3 (a28, MS-3): 1.
      - Case 4, DS-27, the noise run's twin a22: 1; and the kept round's injected a22: 1.

      Each is an `unmet` entry; none comes from §2.2's failing-item entry. So each key names the
      line the practice reading showed false, and no choice among lines was made.
    - **Counted again** by `reality.py` before the first block, on the same records held to the
      same digests, counts only. The same bytes under the same rule give the same counts, so a
      count other than 1 is a defect of the script: a failed precondition (§11). No line is ever
      chosen among several, by its position or by its text.
    - **If the records cannot be read at those digests,** the control cannot be computed: it is
      "not checked", and so the reading is "unchecked" (below).
  - **What it does not test.** Its four cases are physics misreadings. None is a false claim that a
    standard is broken, since practice had no `standard` class. So nothing calibrates the judge on
    standards claims, the kind A2's refusals of the class's twins make (§8, §9 item 8).
  - **A line passes** unless it comes back `true_flaw` with origin `introduced` or `both`, the one
    verdict that would make a correct twin "flawed" below. The share returned `not_a_flaw` is
    printed beside.
  - **Its power, stated now.** Take a judge that confirms each false finding with probability p,
    independently from case to case, and a22's two lines as one fact. It passes the bar with
    probability (1 − p)⁴: **0.66 at p = 10 %, 0.24 at 30 % and 0.06 at 50 %.** If a22's two lines
    were judged independently, it would be (1 − p)⁵: 0.59, 0.17 and 0.03. So a judge that confirms
    half of all plausible false findings passes about one time in sixteen. A good judge (10 %)
    fails the bar about one time in three. The corrected-A label is then not used, and the class
    rule's acceptance half is counted raw (§8).
  - **Practice false findings not used as cases.**
    - a09 and a35, two duty lines on graph-only work. The design does lack the record they ask
      for, and the revision wrote the very value that record concerns, which ARCH-062 judges as
      it judges any value. So `introduced` or `both` is also a defensible answer there, and they
      are not known false. a35 is also one of the five twins of a propagation premise that the
      practice reading left undecided.
    - a32, a single-voltage pattern charged on a figure that cannot reach a limit. The pattern is
      present, and the prompt counts a present pattern as a defect whether or not it can harm.
      So `true_flaw` is the prompt's own answer there (§9 item 8).
  - Control verdicts are never reality verdicts.
- **The reading is reliable** if all three bars are met, **unreliable** if any is missed, and
  **unchecked** if any is not checked.

**The counting rule: one class per rejection, the first that holds** (R-PG-01b §6's classes, with
the injected side made exact):
1. **B, blocked:** listed with its cause, not adjudicated.
2. **P, credited:** an injected review credited under §4.1's common rule.
3. **P′, planted named outside the common cell** (injected side only): not credited, but some
   `true_flaw` line's locus holds a changed pair. It names the planted error by another item, so
   it is never counted as another flaw.
4. **O, other real flaw:**
   - on the injected side: some `true_flaw` line has a **non-empty** locus that holds **no**
     changed pair;
   - on a twin: some line is `true_flaw`, whatever its locus (a twin has no planted error, so every
     real flaw on it is "other");
   - **O-introduced:** such a line has origin `introduced` or `both`. **O-base:** every such line is
     `already_in_base`.
5. **N, no real flaw:** every line is `not_a_flaw`.
6. **U, undecided:** the rest. This includes an injected review whose only `true_flaw` lines have
   an empty locus: such a line cannot be told from the planted error, so it is neither P′ nor O.

**"Other real flaw" (pre-registered, the owner's standing rule).**
- **Counted per arm and side:**
  - every review in class O;
  - **and** every P or P′ review that also holds a `true_flaw` line whose locus is non-empty and
    holds no changed pair ("planted, with another real flaw").
- **Distinct other flaws** are counted by locus within an item.
- Base flaws are counted apart.

**Beside P, by reading:** "planted named", every injected review in P or P′ with a `true_flaw` line
whose locus holds a changed pair.

**The confirmation pass** (fresh-v2's twins, primary and `standard`):
- **A flaw-making line** is a line in a review of a twin that comes back `true_flaw` with origin
  `introduced` or `both`.
- **The second judgment.** Every flaw-making line is judged a second time, alone in a packet of its
  own, in the false-finding control's form: the twin's base, its clean revision, the corpus's
  `parts_sheet.md` verbatim (on the `standard` class, also the standards file above), and the one
  line, masked. It is judged by a new session, with the reading's prompt, model and settings.
- **Confirmed** if the second judgment is also `true_flaw` with origin `introduced` or `both`.
  **Unconfirmed** otherwise: any other answer, or a packet that never completes. The judgments
  then disagree.
- **On the `standard` class, a third judgment.** Every confirmed line on a twin of `fresh-v2-s` is
  judged once more, by a new session, with the same packet bytes as its second judgment. It is
  **confirmed twice** if the third judgment is also `true_flaw` with origin `introduced` or `both`,
  and unconfirmed otherwise. The class's twin statuses are used only by the class rule's
  acceptance half (§8) and §6.4 item 9, and on them **"a confirmed line" below means a line
  confirmed twice.**
- **Order.** `reality.py` builds the second-judgment packets from the first judgments, after every
  reading and control packet has a verdict or has run out of attempts. It builds the third-judgment
  packets from the second judgments, after every second-judgment packet has. No person reads a
  verdict before the confirmation pass has ended.
- **What the pass protects, stated now.** A correct twin is marked flawed when any one false
  flaw-making line on it, from any arm's review, is confirmed. If its reviews carry k such lines,
  each confirmed with probability r, that happens with probability about 1 − (1 − r)^k.
  - **r is not simply the square of one judgment's rate.** It would be the product of the pooled
    and the solo rates of confirming a false finding only if the judgments erred independently.
    Every judgment uses the same model, prompt and line, so their errors are correlated. And a
    first judge that confirms nearly every finding, as practice suggests, leaves r near the solo
    rate: the rate the false-finding control samples.
  - **So the protection shrinks as refusals carry more lines,** which favours the arm that writes
    the most. At k = 3: about 0.25 with independent errors at 30 % each, and about 0.27 at a solo
    rate of 10 % with a first judge that confirms everything.
  - **On the class, the third judgment** brings r down to the product of the two solo rates if they
    err independently (at 10 % each and k = 3, a twin-level rate of about 0.03), and not at all if
    they are fully correlated (0.27 again). Its packet is the second's, byte for byte, so it
    differs from the second only by sampling. It guards against a chance confirmation, not against
    a lean the packet induces. **The correlated figure is the one to expect.** §8 and §9 item 8
    carry what is left.
- **Projected size:** about 100–300 sessions and about 3–18 M tokens, with no cap, so only the cost
  and the time change. The basis: on the tuning set's 40 twins, the reviews carried 25 finding lines
  in the kept round, 23 and 34 in K's two runs, and 3 in the generalist's (R-LAW-01 §2.2's table),
  so about 150–190 at 120 twins, plus the class's; an agreeable first judge makes most of them
  flaw-making; each is one session of about 25–60 k tokens; the class's third judgments add a few
  dozen at most.
- Blocks `p1` and `p2`'s twins get no status, since they enter no label.

**The corrected-A reading** (a robustness label, never the primary):
- **Each twin gets one status,** from all three arms' reviews of it:
  - **flawed** if some arm's review of it holds a confirmed line;
  - **undecided** if none does, and some arm's review of it holds an unconfirmed flaw-making line
    (the judgments disagree) or is in class U;
  - **unflawed** otherwise.
- **A_corrected for an arm** = the unflawed twins it accepted + the flawed twins it refused with a
  confirmed line of its own, with the undecided twins counted in **both ways**:
  - **way 1:** every undecided twin as unflawed (an arm is credited if it accepted it);
  - **way 2:** every undecided twin as flawed (an arm is credited if its verdict was `fail`).
- **J_corrected** = R (common) + A_corrected − 1, in each way.
- **For §8's labels,** the corrected-A reading agrees with a row or a sentence only if it agrees
  in **both** ways.
- It is used for §8's labels, and for the class rule's acceptance half, only when the reading is
  reliable.
- Class O-introduced is reported from the first judgments, with the confirmed count beside it.

**When and where.**
- On the run account, after the last block, never during a block, with ledger lines (§10).
- **The order:** the injected versions' packets; the twins' packets; the rejection controls,
  drawn from the injected versions' first judgments; the false-finding control; the second
  judgments; the class's third judgments.
- **No packet's verdict is read by any person** until every packet, control and confirmation
  packet has a verdict, or has run out of attempts. Before then, only `reality.py` reads verdicts:
  the injected versions' first judgments, to draw the rejection controls (R-LAW-01 §2.3's rule);
  the twins' first judgments, to build the second-judgment packets; and the second judgments on
  the class's twins, to build the third-judgment packets.
- **A usage limit during the reading** is caught by the same watcher as a block (§10). Packets
  already judged are kept, unread. Any session that ended on the limit, or did not end, is run
  again whole, with the same packet bytes, after the limit resets.
- **At most 3 attempts per packet.** A packet that never completes is "not adjudicated": its lines
  count as `undecidable`, and the packets are listed. A control packet that never completes counts
  as a line not passed. A confirmation packet that never completes leaves its line unconfirmed.

## 8. Decision use, fixed now

**The class rule, fixed now** (the `standard` class's only route into a sentence). On the class's
10 pairs, A2 against B, two halves:
- **The catch half.** **n_A2** = the class's injected items A2 credits and B does not; **n_B** =
  the reverse; **d** = n_A2 − n_B. It holds if **d ≥ 3 under the common rule, and also d ≥ 3 under
  the locating rule** (§4.1), each rule counting its own credits.
- **The acceptance half.** It holds if A2 accepts at most **2** fewer than B of the class's twins
  that §7 does not mark flawed. On this class, a twin is flawed only when some arm's review of it
  holds a line **confirmed by two solo judgments** after the first (§7), each judged with the
  role's standards file in its packet.
  - When §7's reading is reliable, it must hold in both of §7's ways: way 1 counts the unflawed and
    the undecided twins, way 2 the unflawed only.
  - When the reading is unreliable or unchecked, it is counted on all 10 twins (raw).
- **The class rule holds** if both halves hold (§14 item 9a).
- **The class was not measured** if it was not run or not scored (§2.5's caps, §11).

**Why both halves are read this way.** Each reading removes a bias whose direction is known.
- **The catch half.** Under the common rule, A2's cell for this class is the Section 1 line and the
  whole of Section 2, while B's is one line. So when the twin's review cites the Section 1 line,
  B loses its only route to a credit, while A2 keeps the Section 2 items its twin did not cite. The
  common rule alone leans toward d ≥ 3. The locating rule holds both arms alike.
- **The catch half also leans the other way, on this class.** A2, which reads the standards, is
  the arm most likely to refuse the class's twins. A real break on a twin that A2's twin review
  cites (the common rule) or locates (the locating rule) withholds A2's credit for that injected
  item under both rules, and only the acceptance half is corrected for it. That leans toward
  row 2b, the conservative direction.
- **The acceptance half.** The class's twins change ratings and deratings by design, and their
  author never read the standards files. A twin that really breaks a standard, refused by A2 and
  accepted by B, would count against A2 in a raw count.
- **The lean that is left, disclosed.** The filter still leans toward A2, through the judge.
  - A false standards claim that the judge confirms three times drops a correct twin A2 refused,
    and B's lead shrinks by one. Nothing calibrates the judge on standards claims: the
    false-finding control's four cases are physics misreadings (§7).
  - Its size, as an example: say A2 falsely refuses 3 of the 10 twins, with 3 flaw-making lines
    each, and the first judge confirms nearly everything. A judge that confirms a false finding
    alone 10 % of the time then drops about 0.1 of a twin if its two solo judgments err
    independently, and about 0.8 if they are fully correlated, against a tolerance of 2 (§7's
    twin-level form). The correlated figure is the one to expect, since the two solo judgments
    share their packet byte for byte (§7). So about 0.8 of a twin toward row 2a is this example's
    expected size, not a bound.
  - Holding the half in both ways keeps a twin confirmed once but not twice in way 1's count, so
    only a twice-confirmed line can excuse a refusal there.
  - The raw acceptance of all 10 twins is printed in the class clause beside the filtered counts,
    so the filter's effect can be seen.

It is a count on 10 pairs, not a tested effect, and every sentence that uses it says so.

**The class clause,** printed after the sentence of every row: *"On the domain-standard class
(10 pairs, secondary), the fixed specialists credited n_A2 of its errors that the generalist
missed, and the generalist n_B that they missed (under the locating rule, n′_A2 and n′_B); of its k
correct twins that the reading does not mark flawed, they accepted a_A2 against the generalist's
a_B, and of all 10, r_A2 against r_B. A count, not a tested effect."* Where the reading's two ways
differ, k, a_A2 and a_B are given for each way. Where the reading is not reliable, the clause reads
"of its 10 correct twins, they accepted r_A2 against the generalist's r_B", with no filtered count.
(Or: "… the domain-standard class was not measured.")

**The outcome row,** read from the primary contrast J_A2 − J_B (common rule):

| Row | When | The sentence | What it means for the architecture |
|---|---|---|---|
| 1 | **Q2 met** | "After the fix, paired specialists discriminate better than a role-aware generalist on new material: J_A2 − J_B = … (interval), at …× the tokens." | ARCH-060 stands as built. |
| 2a | **Q3 met, Q2 not; the class rule holds** | "After the fix, paired specialists are not shown worse than a role-aware generalist by the margin (0.15)[, and are shown worse by less than the margin], and cost …× as much; on the four generic classes no gain is shown." The bracketed clause is printed when the interval lies wholly below 0. | ARCH-060 stands. ARCH-063's reason for pairing is restated as **resting on the domain-standard class**, with the class clause's counts, labelled "a count on 10 pairs, not a tested effect". |
| 2b | **Q3 met, Q2 not; the class rule does not hold, or the class was not measured** | as row 2a | ARCH-060 stands. ARCH-063's reason for pairing is restated as **resting on nothing measured here**, with the class clause beside it. |
| 3a | **Q3 not met, "shown worse":** the interval's lower end is at or below −0.15, and the interval lies wholly below 0 | **The claim shift, committed on 21.10.2026:** *"On this design class (one stand-in self-balancing robot and its parts sheet) and these four error classes, a role-aware generalist reviewer with the shared verdict policy suffices; paired specialists cost about …× with no measured gain."* | ARCH-060's default becomes the generalist reviewer. The specialist rubrics become optional checklists. ARCH-063 is amended. Those edits are made outside this file. |
| 3b | **Q3 not met, "not shown at least as good":** the interval's lower end is at or below −0.15, and its upper end at or above 0 | *"On this design class (one stand-in self-balancing robot and its parts sheet) and these four error classes, paired specialists were not shown to be at least as good as a role-aware generalist reviewer with the shared verdict policy (margin 0.15), and cost about …× as much. This does not show the two equal: J_A2 − J_B = … (interval)."* Beside it, the generalist's own test: "the generalist is [not] shown worse than the specialists (margin 0.15)", which holds if the interval's upper end lies below +0.15. | **The claim shift applies** (the trigger is "Q3 not met"), as in row 3a: ARCH-060's default becomes the generalist reviewer, the specialist rubrics become optional checklists, and ARCH-063 is amended. The reason is given as "the costlier design did not earn its place; the two were not shown equal". Those edits are made outside this file. |

- **The scope of rows 3a and 3b is their sentence, word for word:** this design class and these four
  error classes. The `standard` class never widens or narrows it; it enters only through the class
  clause and the choice between rows 2a and 2b.

**The fix's sentence (Q1):**
- **met:** "The calibration fix worked on new material: J_A2 − J_A1 = … (interval)";
- **J_A2 − J_A1's interval wholly above 0, but a guard of Q1 fails:** "J rose on new material:
  J_A2 − J_A1 = … (interval). But Q1's guard on [A | R under the common rule | R under the strict
  rule] failed, so the gain is not counted." Each guard that failed is named;
- **J_A2 − J_A1's interval wholly below 0:** "The fix made the specialists worse on new material";
- **otherwise:** "The fix's gain was not shown on new material", with the point and interval.

**Q4's label,** its set-adjusted label and the sheet-matched Q4 are printed with these sentences.

**Success** is Q1 **and** Q3, with Q4 clean (neither tailoring nor possible tailoring). Q2 is the
thesis's original claim, and it is reported as it falls.

**Robustness, printed beside the row and beside the fix's sentence** (each stands either way).
Each reading is applied to the same 120 pairs, and treats the compared arms alike:
- **The row (A2 against B) is robust** if it is the same under:
  - the locating rule, which both arms can be held to alike;
  - the corrected-A reading, when §7 is reliable, in both of its ways.
- **The fix's sentence (A2 against A1) is robust** if it is the same under:
  - the strict cell rule, which both specialist arms can be held to alike;
  - the corrected-A reading, when §7 is reliable, in both of its ways.
- **"The same"** means the same one of rows 1, 2, 3a and 3b. The class rule is not re-read under a
  robustness reading, so rows 2a and 2b count as one row there. Rows 3a and 3b are different rows.
  For the fix's sentence, it means the same one of its four sentences.
- Otherwise each reading that differs is named.
- **Why not the strict rule for the row.** B has no error cell, so the strict rule is R-PG-02's
  asymmetric rule there. On practice it put the contrast at −0.25 against −0.025 under the common
  rule. Rows 1 and 2 could then almost never be robust, and row 3 almost always would be.
- **Why not each author pair alone.** At 40 pairs each interval is wider, which by itself favours
  row 3. The pairs are compared in §6.4 item 1 instead.

**What never changes the row:**
- the `standard` class, which is secondary with n = 10. It enters only by the class rule: the choice
  between rows 2a and 2b, and the class clause.
- blocks `p1` and `p2`.
- the noise label.

**Under a deviation** that voids a primary contrast (§11), Q1–Q3 and the row are **not taken**.
**The claim shift is not applied**, and `RESULT.md` reports it so.

## 9. Threats to validity (stated before the run)

1. **The authoring rules shape the set, rule by rule in both directions** (§2.3). Every rule comes
   from reading reviews of specialist runs; no generalist review was read.
   - **The three rules drawn from the fixed specialists' own misreadings** (where a quantity acts,
     the duty-limit convention, node order) were left out before authoring. So the set is not
     cleared of the ambiguities the arm under test misread, and no qualifier is needed on §8's
     sentences.
   - **The eight rules given, by their practice instances:**
     - rules 2 and 3 remove real twin flaws that both specialist arms refused and the generalist
       accepted: **toward Q2 and Q3**;
     - rule 5 removes a kind the generalist refused and the specialists accepted (an operating
       point cited as a limit): **against Q2 and Q3**;
     - rules 1 and 6 remove kinds that K refused and the fixed rubrics did not (one setting under two
       labels; an undecided propagation premise): they help A1, so **against Q1**;
     - rule 4's instance was refused by every arm; rules 7 and 8 come from practice/v1, where no
       generalist ran, so their direction is not known.
   - On balance, the rules lean against Q1 if at all, and slightly toward Q2 and Q3 (two instances
     against one).
   - **Mitigation:**
     - the rules are generic and fixed before authoring;
     - they apply to all arms;
     - each rule's direction is stated now (§2.3);
     - the corrected-A reading, with its false-finding control and its confirmation pass, is
       printed beside.
2. **The complete sheet changes every arm,** and most likely helps A1, whose rubrics block on blank
   rows. This narrows A2 − A1 against practice, and confounds Q4: Q4's anchor was measured on the
   lossy sheet, so the sheet alone can lower the measured drop and hide tailoring. **Mitigation:**
   Q4's set-adjusted reading; the sheet-matched Q4 (§6.3).
3. **A1 is K's rubrics on today's instrument,** not R-PG-02's configuration byte for byte. The tree,
   the sheet and the account's sheet sentence differ. A2's practice figure, Q4's anchor, comes from
   an older tree too. **Mitigation:** the prompt identity check (§3.3), which covers the packet
   only; and `code_changes.py`'s list of every commit since each practice tree that touched a file
   under `src/physgate/`, `pyproject.toml` or `uv.lock`, with the files the run's processes load
   marked (§3.3), published with "Commits filled". A runtime difference is disclosed by that list.
   It is not measured.
4. **One stand-in design class and one parts sheet;** three author pairs; four generic error
   classes.
   - On these classes, practice found no error that only a specialist caught.
   - Only the `standard` class can show what domain knowledge adds, and it has 10 pairs.
   - Its errors come from the very standards files the specialists read, and the generalist is not
     given them. So it measures whether that knowledge reaches a catch, not a contest of equals.
5. **The common rule's looseness:** the Section 1 line can be cited for any reason. **Mitigation:**
   - the twin condition;
   - the strict and locating rules;
   - the reading's "planted named" beside.
6. **Run-to-run noise** is large per item (about 20 % of twins). One run per arm. The intervals
   carry it (§6.2), and no item's flip is read as an effect.
7. **Drift between blocks.** The blocks run on different hours and possibly different weekly
   windows, on the same pinned model.
   - The arms of a block share the hours, so each contrast is time-matched within a block.
   - Figures per block are printed.
8. **The reality judge is agreeable.** In practice, judges of this kind agreed with nearly every
   finding. An agreeable judge favours, in the corrected-A reading, the arm that refuses most: it
   writes the most lines for the judge to confirm.
   - **Mitigation:** three controls, one of them on false findings about correct designs (§7);
     "unreliable" removes the corrected-A label; and that reading agrees with a row only in both of
     its ways.
   - **The confirmation pass** (§7): a twin is "flawed" only when a second judgment, alone in a
     packet of its own, confirms the line; on the `standard` class, only when a second and a third
     both do, with the role's standards file in every packet of the class.
   - **What remains:**
     - **the confirmation pass protects less than independence would suggest.** Its judgments
       share the model, the prompt and the line, so their errors are correlated, and an agreeable
       first judge leaves a line's chance of being confirmed near the solo rate. A correct twin is
       marked flawed by any one of its confirmed false lines, so the chance grows with the lines
       its refusals carry: about 1 − (1 − r)^k for k lines (§7). That favours the arm that writes
       the most;
     - **on the `standard` class,** the judge sees the standards file, but nothing calibrates it on
       standards claims: the false-finding control's cases are physics misreadings. The filter on
       the class rule's acceptance half leans toward A2 by the judge's agreeableness, by about 0.8
       of a twin in §8's example, the size to expect and not a bound, since the two solo judgments
       share their packet byte for byte; §8 discloses it and prints the raw count beside;
     - the false-finding control has four cases. At its bar of 4 of 4 it passes a judge that
       confirms 30 % of false findings about one time in four, and one that confirms 10 % about
       two times in three (§7). A mild bias often passes it;
     - its cases, and the confirmation pass, are single lines in packets of their own, while the
       reading pools up to 12 lines from three arms. Agreeing findings side by side may make the
       judge more agreeable in the pooled packets than the control shows;
     - the prompt counts a rubric pattern that is present as a defect, whether or not it can harm
       (practice's a32). So the corrected-A reading may credit refusals on patterns that only the
       specialists' rubrics carry. That favours the specialist arms there.
9. **The read limit:** the sheet is read at about 91 % of the read cap. **Mitigation:** the smoke and
   the stream check; a cut voids the block.
10. **The generalist finishes sooner** (about 0.28 M tokens a review, against 0.5–0.65 M), so its
    outage exposure differs. Per-item times and retries are compared (§6.4 item 11).
11. **The gate accepts every twin by construction.** It is not a result for A.
12. **The authors use the gate's vocabulary,** which may favour the gate (R-PG-02 R7 item 4). The gate
    is not a question here.
13. **The reviewers see less prose than the authors.** `--prose drop` leaves out the kit's build line
    and the sheet's conventions, which the authors read (§2.4). Every earlier reviewers' sheet had
    the same gap, and every arm here has it alike.
14. **The power behind the design is projected, and Q1's guards cost power.** The half-widths come
    from one practice set's variance components, scaled to three author pairs. The stratified
    bootstrap holds the three pairs fixed, so its interval leaves out how a fourth author pair might
    differ; §6.4 item 1 shows how far the three differ. The guard on R under the strict rule alone fails on noise about 8–20 % of the time (§6.3). So a real
    gain may well be "not shown".

## 10. Host, account, cost, quota and order

**Host.** The ARM virtual machine of §3.4.
- Two checkouts, `R` and `R_K`.
- Review roots lie outside both.
- Every block is launched detached (`setsid` and `nohup`), outside any agent session's process
  tree.

**Account.** The run account: the account the practice cycle's scored runs used, and R-PG-01b's.
- Its long-lived token is a shape-checked line in the machine's run environment file. It is never
  printed.
- The launch records the owner's label for the account and the first 8 hex digits of the token's
  sha256.
- **No other session runs on the run account during a block,** nor between the owner's
  confirmation that a weekly window has begun and the first block (order item 4). The owner
  confirms this per block, and it is recorded.

**Order, with R-PG-01b, which shares the account:**
1. **R-PG-01b first.** It is ready, and starts after the run account's weekly reset on Thursday
   29.10.2026. Its two rounds and its reality adjudication run under its own rules.
   - **Those rules never wait for a weekly allowance** (R-PG-01b §11: "no round waits for, or is
     stopped by, a weekly allowance"). A round that a usage limit stops is void, and is
     re-attempted after that limit has reset, within its 3 attempts per round (R-PG-01b §12).
   - Its rounds take hours (about 7–11 h each, R-PG-01b §11). So **R-PG-01b runs into a second
     weekly window only through such a void:** a weekly limit that voids one of its rounds, which
     is then re-attempted after the reset of Thursday 5.11.2026.
2. **Meanwhile, nothing of R-PG-03 uses the run account:**
   - this file's freeze;
   - the converter's fixes and the `standard` class;
   - the scripts and their tests on fixtures;
   - `R` and `R_K`;
   - the sheet;
   - the sandbox proof on the scripted endpoint.
3. **The authoring** (X1, X2, Y1, Y2, Z1, Z2, C, any resume, replacement or restart session, and
   the checks between them) runs on the run account. It starts at least 5 hours after R-PG-01b's
   last session has ended, its reality adjudication included, wherever that falls. It never
   overlaps a round of R-PG-01b or a block of R-PG-03.
4. **The blocks start at the beginning of a weekly window of the run account,** after "Set filled",
   and **no earlier than Thursday 5.11.2026.** If R-PG-01b runs into a second window (item 1), the
   first possible start is Thursday 12.11.2026.
   - **"The beginning of a weekly window," operationally:** the first block launches after the
     owner's confirmation, read from the account's usage page, that the weekly limit has reset,
     and **nothing else runs on the run account between that confirmation and the first block.**
     The confirmation is recorded in UTC, since local time moves by an hour against UTC when summer
     time ends on 25.10.2026. `launch.sh` refuses the first block without it.
   - **Blocks are named after their corpora:** block `x1` reviews `fresh-v2-x1`, and so on for
     `x2`, `y1`, `y2`, `z1`, `z2` and `s`; blocks `p1` and `p2` review `fresh-v1c`'s batches
     `a01`–`a20` and `a21`–`a40`. Author sessions keep their capitals (X1 is a session), so a block
     and a session never share a name.
   - **The order** is **`x1`, `y1`, `z1`, `z2`, `y2`, `x2`** (primary), then **`s`**, then **`p1`**
     and **`p2`**.
   - **What the order does:** pair X holds places 1 and 6, Y places 2 and 5, Z places 3 and 4, so
     every author pair's mean place in the primary is 3.5, and time position is balanced between
     the pairs in the mean. A window cut after the third block splits every pair, one block on
     each side.
   - **What it cannot do:** keep every cut from putting both blocks of one pair in one window. A
     cut after the first block leaves pairs Y and Z wholly in the next window; a cut after the
     second leaves pair Z there; a cut after the fourth leaves pair Z wholly in the first window,
     and a cut after the fifth leaves pairs Y and Z wholly in the first window. No order of six
     blocks avoids every such cut.
   - So the contrasts are time-matched within each block (§9 item 7), and the figures per block and
     per author pair are printed (§6.4 item 1).
   - **Two weekly windows may be needed.** The blocks need about 435–590 M tokens and the reading,
     with its confirmation pass, about 31–53 M more (the table below). The most the account has
     carried in one weekly window so far is about 100.5 M, with no limit hit (the practice cycle's
     ledger), and its weekly limit is not known. So the blocks may need two weekly windows, or
     more. A weekly-limit stop voids only the block it hits, and counts as one of its void
     attempts (§11). That block is re-attempted whole after the reset, in the next window (from
     12.11.2026 if the blocks start on 5.11), and the blocks after it follow in their order.
5. **The reality reading** runs after the last block, its confirmation pass included. **Nothing is
   tallied before the last block ends** (R8).

**The 5-hour projection, before each block.** The block starts only if:
- (the tokens the ledger records on the account in the trailing 5 hours)
- \+ (the block's projection: reviews × the upper rates 0.70 M for A2 and A1, 0.35 M for B)
- is at most **W5 = 80 M**, the most the account has carried in one 5-hour span without a limit
  (80.46 M, practice cycle).

Otherwise it waits. The owner may raise W5 at launch from the account's usage page; the figure is
recorded.

**No weekly gate** (the owner's stance for this account, 23.10.2026). Instead:
- **a watcher**, derived from the practice cycle's abort guard, stops all arms of a block at the
  first session that ends with `usage_limit_reached`;
- the block is void, and it is re-attempted whole after the matching reset. A void attempt is never
  read or tallied (R8);
- 429s are counted, and handled by the retries and the pause.
- **Disclosed:** the practice cycle's plan asked for this stop to be built inside the instrument
  before R-PG-03's launch. It is not built there. The watcher is outside the instrument, as in the
  practice cycle and in R-PG-01b.
- **The same watcher** guards the authoring sessions, whose cut sessions are resumed (§2.5), and
  the reality reading (§7).

**The quota ledger** covers every use of the run account, R-PG-01b's included.
- **It opens with R-PG-01b's lines,** copied from R-PG-01b's own ledger as counts: each round's
  tokens and its start and end times (UTC), and its reality adjudication's total and times. If
  R-PG-01b's records give no total for a step, the line says so and gives the times.
- **Then R-PG-03's lines:** one per block attempt (void attempts included), per authoring session
  (replacements and restarts included), per resume of an authoring session (§2.5), and per reality
  step (the confirmation pass included), each written before any scoring.
- **Each line holds** `tokens_every_try` (the binary's own totals), the account, its weekly window,
  and the start and end times.
- **For the 5-hour projection,** a line whose span overlaps the trailing 5 hours counts in full.

**Cost and time** (tokens per review from measured runs: fixed rubrics 0.49 M, K 0.51–0.65 M,
generalist 0.28 M; the complete sheet adds an estimated 0–10 %):

| Step | Reviews / sessions | Tokens | USD (list-price equivalent, not a bill) | Wall clock |
|---|--:|--:|--:|---|
| Authoring (three pairs, C, checks) | 7 sessions + resumes | 51–61 M | 51–61 | about 1–1.5 days |
| Blocks `x1`, `y1`, `z1`, `z2`, `y2`, `x2` (each 40 reviews per arm) | 720 | 307–420 M | 675–840 | about 2.5–3 h each |
| Block `s` (`standard`, 20 reviews per arm) | 60 | 26–35 M | 56–70 | about 1.5 h |
| Blocks `p1`, `p2` (R-PG-01b's D3; A2, A1 and B, 40 reviews each per block) | 240 | 102–136 M | 220–280 | about 2.5 h each |
| Reality reading (≈ 490–560 packets with controls, blocks `p1` and `p2` included) | ≈ 560 sessions | 28–35 M | — | a few hours |
| Confirmation pass (§7: second judgments, and the class's third) | ≈ 100–300 sessions | 3–18 M | — | a few hours |
| **Total** | | **≈ 517–705 M** (blocks ≈ 435–590 M) | **≈ 1,000–1,250** | **≈ 3–4 days of runs, at one block per 5-hour span, over two weekly windows, or more** |

Resumes, replacement sessions and restarts (§2.5) are not in the table. A replacement costs about
one author session's tokens (about 5–10 M), and a restart of a pair about 16 M.

The run has no dollar cap. It is bounded by its counts and by each session's bounds.

## 11. Deviations, fixed now

- **Before any review, a failed precondition is not a deviation.** This covers:
  - the acceptance checks, the sheet's counts and digest, and the rubric, generalist and knowledge
    pins;
  - `code_changes.py`'s list (§3.3), a stop of the script on a dynamic import included;
  - the prompt identity check;
  - the whole-read smoke and R3;
  - the authoring's failures, resumes, replacements, restarts and caps.

  It is handled by its fixed procedure (§2.4, §2.5, §3.2, §3.3) and recorded. A fix is allowed only
  if it changes neither this file nor a pinned digest. Otherwise the experiment stops, and an
  amendment is a new experiment.
- **A void block** (usage limit, a cut read, an arm that stops in its first minute) is re-attempted
  whole, never resumed, and every attempt is reported.
  - **After 3 void attempts of one block,** the owner declares whether the block is impossible as
    specified (the last item below), on the kept logs and the ledger only. Nothing has been tallied
    then (R8), so the ruling is blind to the outcome.
- **An instrument defect found after a number is seen** is a deviation **only if a test that
  depends on no verdict shows it:** a fixture test, a byte comparison of packets or records, or a
  fact of a stream (a cut read, a wrong digest, a missing session).
  - Every block it touches is then re-run at the corrected commit, and both runs are reported.
  - The decision uses the corrected runs.
  - **A defect argued from verdicts or figures alone is not an instrument defect.** It triggers no
    re-run and is reported as a remark. A re-run is a fresh draw of the reviewers' noise, so a
    re-run chosen after seeing numbers would let the numbers choose the draw.
- **A rubric, generalist or knowledge digest on a review line that is not its arm's** voids that
  block, which is re-run.
- **A re-gate that is not byte-identical** is a deviation for the gate's figures only. The reviewer
  decisions stand.
- **Anything else impossible as specified** is a deviation. The decisions it feeds are **not
  taken**, and the claim shift is not applied (§8).

## 12. What is published

`RESULT.md` cites "Commits filled", "Sheet filled", "Set filled" and every component of §3. It
publishes:
- the results rows (one per item and arm) and the tally's full output;
- `physgate catches` over each run, held to the rows;
- fresh-v2's seven corpora and `fresh-v1c`'s two, after the run;
- the authoring records: inputs, messages with sha256, audits per turn, the passed copies'
  digests, every check fact returned, every route taken and every resume, replacement or restart
  (§2.5), and the sandbox proof;
- `code_changes.py`'s list of code changes (§3.3);
- Appendix A and B as frozen files;
- every reality packet's verdicts and the three controls, the false-finding control's five lines
  in its four cases, their keys' counts and their packets included, blocks `p1` and `p2`'s own
  controls, and every confirmation packet (second and third judgments) with its verdict;
- the launch logs, the prompt identity report and the ledger, R-PG-01b's lines included;
- the tuning record (R9), with its name map;
- every R7 exposure beside the headline, and the owner's statement on the authoring (who ran it, and
  that no one involved in tuning opened a file of `fresh-v2` before the run).

Not published: session transcripts and runtime account files.

## 13. The scripts (written after the freeze, tested on fixtures)

Under `experiments/R-PG-03/`, run with `python -I`, each tested by `test_*.py` on the instrument's
own test corpus or a synthetic fixture, never on a set of this experiment.

| Script | What it does |
|---|---|
| `launch.sh` | Pre-flight refusals, then one block's arms together. The refusals cover: `R`/`R_K`, their five-path difference and the content of `R_K`'s `promotions.jsonl`; clean trees; every tree, blob and digest of §3, the knowledge trees included; the binary; the parameters; the manifests; the sheet; the twins' precondition again; R3; the prompt identity check; the smoke (first block); the 5-hour projection, with R-PG-01b's ledger lines; the owner's per-block confirmation; for the first block, the owner's UTC-stamped confirmation that a weekly window has begun, with no ledger line after it. It starts the watcher. Scans count with `scripts/experiment/scan.sh`. |
| `lanes.py` | The 3/3/2 split, each block's seeded plan (a pair on one lane; classes balanced), and the check after the run (R-PG-02's rule). |
| `rules_check.py` | §2.5 item 4: the mechanical rule checks, with rule 2's 4 rows, rule 5's 18 rows and its name patterns, and rule 4's listing. Prints bare facts in Appendix B's template. Also checks every passed copy in a session's directory against its recorded digest. |
| `authoring.sh` | The runner's fixed command sheet for §2.2 and §2.5: each session's launch and messages, the passed copies and their digests, the checks between turns, every route, resume, replacement, restart and cap, and the audits per turn. It reads only counts, exit codes, audit summaries and the facts it forwards. |
| `code_changes.py` | §3.3: for `0936f1f`, `eae78c0` and `8c51f48` to `R`, and `R` to `R_K`, every commit touching a file under `src/physgate/`, `pyproject.toml` or `uv.lock` (sha, PR number, subject, files) and `git diff --stat` of those paths. Inside the list it marks each file the run's processes load: an AST walk at the old tree and at `R`, seeded with every module of `physgate.evaluation.inject`, with `physgate.cli` and with `physgate.hooks.__main__`, by §3.3's resolution rules (submodules of `from p import m`, every parent package's `__init__.py`, imports at any depth). Every non-Python file under `src/physgate/`, `pyproject.toml` and `uv.lock` are marked as possibly read. Any kind of §3.3's dynamic-import stop in a loaded file stops it (a non-literal import call under any name, a non-literal `exec`, `eval` or `compile`, loading by file path, entry points, a `-m` launch of a module the walk does not reach); `find_spec` does not. Prints the counts of marked and unmarked files. Tested on a fixture repository, a test per resolution rule and per kind of stop. |
| `sheet_check.py` | The one-word table diff, the converter re-run with §2.4's call (its named line digest included), the counts and the digest, for fresh-v2 and `fresh-v1c` (§2.4). |
| `prompt_identity.py` | §3.3: A2's packets at `R` against `gr2-r1-run-tree`, A1's and B's at `R_K` against `eae78c0`, every tree fed the same test-corpus bytes copied from `R`; prints every difference. |
| `watch_limit.sh`, `streams.py` | The usage-limit watcher, for blocks, authoring and the reality reading; the stream facts that mark an authoring session cut short (§2.5); and the cut-read stream check (§2.4, §10). |
| `ledger.py` | §10's ledger: R-PG-01b's lines copied as counts, then one line per R-PG-03 attempt, session, resume and step; the trailing-5-hour figure. Counts only; no verdict is read. |
| `tally3.py` | Imports R-PG-02's frozen `tally.py` unedited (`set_facts`, `Run`, `per_item`, `naming`, `names_pair`, `wilson`, `j_of`, `contrast_interval`, `drop_interval`). Adds: the common, strict and locating rules; the `standard` cell; the bootstrap in three strata; Q1–Q4, the set-adjusted reading and the sheet-matched Q4; every §6.4 figure, the six comparisons between author pairs included; the class rule's two halves; the robustness labels; the row of §8. It checks each review line's rubric and knowledge digests per arm. **The frozen `per_item` refuses the class `standard`** (it raises `TallyError`), so `tally3.py` scores `fresh-v2-s` by a path of its own, built from the module's other functions; the module is never patched. It refuses to run before the last block has ended (R8). |
| `reality.py` | §7: lines in §7's line order, loci, packets (R-LAW-01's prompt and schema byte for byte; on the `standard` class, the role's standards file, held to §7's four digests), the three controls on `fresh-v2`'s packets, and blocks `p1` and `p2`'s own calibration and rejection controls apart (the false-finding control's five lines taken from the practice cycle's records by their keys alone, the records held to R-LAW-01's recorded digests, each key counted again before the first block, a count other than 1 stopping it, scored as four cases), the confirmation pass (second judgments built from the first, the class's third from the second, by script alone), the classes, "other real flaw", the twin statuses and the corrected-A reading in both ways. No verdict is shown to a person before every packet, control and confirmation packet is done. |
| `regate.py` | R6, as R-PG-02's. |
| `fixture.py`, `test_*.py` | Built logs and scripted stand-in reviewers; a test per rule, refusal and deviation stop. |

**One script ran before the freeze:** `ff_key_probe.py` (sha256
`d1def63279798ee19885647611bf0cd7f16e0617a397bb915e337e0953baf7ad`), §7's count-only probe of the
false-finding control's five keys. It is published beside the scripts above, byte for byte, and
`reality.py` repeats its count before the first block.

## 14. The numbers the owner sets

The owner's seven decisions of 24.10.2026 are written in (items 1, 4, 9a, 11, 16, 17 and 19, and
the order of §10). Every value below was set before any file of `fresh-v2` existed.

| # | Number | Value | Where |
|---|---|---|---|
| 1 | Set size | 120 + 120: three author pairs (X, Y, Z), each 40 + 40 in two batches of 20; 30 per class | §2.1 |
| 2 | Runs per arm | 1 per block | §5 R6, §6.2 |
| 3 | `standard` class | 10 + 10, on pair X's base, session C | §2.1, §2.2 |
| 4 | Blocks `p1`, `p2` (D3) | A2, A1 and B on the tuning set with the complete sheet (`fresh-v1c`), split by R-PG-02's two batches; never decide; A2's figures give the sheet-matched Q4 | §6.4 item 10, §6.3 |
| 5 | Seeds and block order | blocks, named after their corpora, in this order: `x1` 53, `y1` 59, `z1` 83, `z2` 89, `y2` 67, `x2` 61, then `s` 71, `p1` 73, `p2` 79 (author sessions take no seed); bootstrap 13 (10,000 draws; three strata for the primary and its contrasts, unstratified for Q4 and the readings beside it); reality packets 37 (`fresh-v2`'s stream, then a second for blocks `p1` and `p2`); rejection control 43 (`fresh-v2`'s draw, then blocks `p1` and `p2`'s) | §5 R8, §6, §7, §10 |
| 6 | Lanes | 8: A2 3, A1 3, B 2, in every block, `p1` and `p2` included | §3.4 |
| 7 | Parameters | R-PG-02's `params_fresh.json` except `lanes` | §3.4 |
| 8 | Q1's guards | A_A2 ≥ A_A1; R falls by at most 5 % of the pairs (6 of 120) under either rule | §6.3 |
| 9 | Q3's margin | −0.15 | §6.3 |
| 9a | The class rule | the catch half: d ≥ 3 of 10 under the common rule and under the locating rule; the acceptance half: A2's acceptance at most 2 below B's, over the twins §7 does not mark flawed (in both ways when the reading is reliable; raw otherwise), where a class twin is flawed only with a line confirmed by two solo judgments, each with the role's standards file in its packet; the raw acceptance of all 10 always printed beside | §8, §7 |
| 10 | Q4 | P5's form, 0.15; the set-adjusted reading and the sheet-matched Q4 beside | §6.3 |
| 11 | The claim shift's trigger | Q3 not met, as rows 3a ("shown worse") and 3b ("not shown at least as good"), each with its own sentence; both apply the shift | §8 |
| 12 | Reality controls | calibration and rejection control 70 % each, at least 10 cases; false-finding control 4 of its 4 fixed cases (a22's two lines one case); all three computed on `fresh-v2`'s packets only; the confirmation pass: a second solo judgment for every flaw-making line on a `fresh-v2` twin, and a third for every confirmed line on a class twin; the class's packets carry the role's standards file; packets of at most 12 lines; at most 3 attempts per packet | §7 |
| 13 | W5 | 80 M (raisable at launch, recorded) | §10 |
| 14 | Acceptance rounds and caps | per batch: a first check and at most 4 fact rounds; per attempt of a pair: at most 2 replacements per error session, X3 at most once; per pair: at most 2 restarts; per session: at most 2 usage-limit resumes, apart from the caps; per turn: 3 infrastructure resumes on the retry ladder (60, 900, 2,700 s), then the ladder once more after the owner confirms the service is back, beyond that only on the owner's word; none spends a cap | §2.5 |
| 15 | Void attempts per block | 3, then the owner declares, blind to the outcome | §11 |
| 16 | The account's paragraphs | unchanged (`8580efd0…`) | §3.3 |
| 17 | The authoring rules given | eight rules (Appendix A); the three drawn from the fixed rubrics' own misreadings are left out | §2.3, Appendix A |
| 18 | Robustness readings | the row: the locating rule, and the corrected-A reading in both ways; the fix's sentence: the strict cell rule, and the corrected-A reading in both ways | §8 |
| 19 | The fresh-v2 sheet | the authors' table with R6.05's one word changed; `--keep-values-from` `bc1e5ec1…`; `--prose drop`, with the one row-id prose line named by its digest; after the converter's follow-up fixes are merged | §2.4 |
| 20 | Blocks' earliest start | the beginning of a weekly window after "Set filled", no earlier than 5.11.2026: the first block launches after the owner's usage-page confirmation that the weekly limit has reset, recorded in UTC, with nothing else on the run account in between | §10 |

---

## Appendix A. `rules.md`, the authoring rules (given to every author session)

The file exactly as every author session receives it: eight rules. Three more were drafted from the
fixed rubrics' own practice misreadings (where a quantity acts, the duty-limit convention, node
order) and left out by the owner before authoring (§2.3). They are not in the file.

```markdown
# Rules for this set

Read these after `format.md`. Where they say more than `format.md`, they hold. Some are checked
by a script before the set is used; every one is part of what the set is judged against.

## The parts sheet

1. Write only what a row says, with its qualification. A row whose value is a range, a list or a
   text, or that carries a note, means what its label and note say: a peak is not a continuous
   rating, and a value stated under a condition holds only under it. Where a note gives one setting
   under two labels (a figure in one table, a rounded label for the same setting in another), use
   the row's number and never the other label's.
2. A limit or a margin is never taken from an absolute-maximum row. An absolute maximum is where
   damage begins, not where a design works. If the working range is given only as a range, which a
   `derived:` source cannot cite, the margin is not written.

## What a revision may change

3. A revision never removes a quantity the base has, and never moves to a part, a cell chemistry or
   an arrangement whose numbers the parts sheet does not give.
4. A revision never relaxes a requirement, an acceptance floor or a protective limit. A floor or a
   minimum (a required rate, a minimum margin) is never lowered. A cap or a maximum (a duty cap, a
   current limit) is never raised or deleted, with one exception: a cap re-derived, by the same
   formula and with the same margin, from the rating it protects, because the revision changed a
   part or a supply. Every change has an engineering reason, never a convenience.
5. A limit is written only from a row that publishes it as a limit or a rating. An operating point
   (a speed or a torque at peak efficiency, a typical current) is never written as a limit. A limit
   the sheet does not publish is not written.
6. "Every revision is complete" (`format.md`) covers every `constrains` edge of every changed node,
   also when the target node is rewritten in the same revision for another reason. Then its numbers
   also follow from this change, or it carries a `no_change_justified` entry keyed by the changed
   node.
7. A revision never puts a different datasheet figure under an existing quantity name (another kind
   of thermal resistance, another rating). A different figure takes a name that says which it is.

## The base

8. Each factor in a derived number applies once. A rating the sheet gives at a part's output
   already includes that part's internal reduction, and is never multiplied by it again.
```

## Appendix B. The fixed messages and the new brief

**Added to `brief_A.md` and `brief_B.md`** (otherwise R-PG-02's frozen briefs, byte for byte):
- in the reading list, after `format.md`: "`rules.md`: rules this set adds to the format. Where they
  say more than `format.md`, they hold."
- in `brief_B.md` only, appended to the class list's last paragraph: "Your error breaks the revision
  in exactly one place; every rule of `rules.md` still holds everywhere else."

**The continuations** to `a21`–`a40` (for X1, Y1 and Z1, and for X2, Y2 and Z2) are R-PG-02's two
continuation messages, byte for byte (sha256 `4cef18d7…` and `660015c3…`).

**The third continuation, for X1 only:**

> Your forty revisions are written. Now write ten more revisions of the same base, `clean/s01.json`
> to `clean/s10.json`, exactly as `brief.md` says for the others: one change each, every revision
> complete, each with its `assigned_role` and its one-sentence `summary`. Each changes a part's
> rating or derating, a supply's or regulator's operating range, a thermal path, or a timing or
> sample rate, with every dependent number re-derived. At least two are assigned to each of the four
> roles. None makes the same change as any of `a01` to `a40`. Do not change `base.json` or any
> earlier revision. When all ten exist, add their lines to `done.md`. Then stop.

**The launch message for X3** (only if §2.5's route calls for it; X3's directory holds X1's inputs
and pair X's passed `base.json` and `clean/a01.json` to `clean/a40.json`):

> Read `brief.md` and every file it names first. Another session wrote the design in `base.json`
> and forty revisions of it, `clean/a01.json` to `clean/a40.json`, as `brief.md` says. Do not change
> any of them. Write ten more revisions of the same base, `clean/s01.json` to `clean/s10.json`,
> exactly as `brief.md` says for the others: one change each, every revision complete, each with
> its `assigned_role` and its one-sentence `summary`. Each changes a part's rating or derating, a
> supply's or regulator's operating range, a thermal path, or a timing or sample rate, with every
> dependent number re-derived. At least two are assigned to each of the four roles. None makes the
> same change as any of `a01` to `a40`. When all ten exist, add their lines to `done.md`. Then stop.

**The resume message** (any author session cut short by a usage limit or an infrastructure error,
§2.5):

> Your session was stopped before you finished. Continue the task of the last message from where
> you stopped. Change nothing already written unless that task says so. Then stop.

**The facts template** (X1, Y1, Z1 and X3, after a check):

> The design was checked. These facts need a change before the next check:
> `<one line per fact: the check, the node, the quantity, the message>`
> Change only what these facts need, and keep every rule of `rules.md`. Then add one line to
> `done.md` saying the facts are answered, and stop.

**`brief_C.md`:**

```markdown
# Brief: ten errors against the domains' own standards

You are writing errors for an experiment in a thesis on checking engineering designs made by AI
agents. Another session wrote a design (`base.json`) and ten valid revisions of it
(`clean/s01.json` to `clean/s10.json`). **You make each revision wrong in exactly one place, so that
it breaks a rule its domain's standards state.**

Everything you need is in this directory. Read these first, in this order:

1. `architecture.md`: how a design is written down, and the checks the architecture names.
2. `format.md` and `rules.md`: the node format, the files, and the rules the revisions keep.
3. `vocabulary.md` and `parts_sheet.md`: the quantity names and the parts' data.
4. `standards/control.md`, `standards/electrical.md`, `standards/firmware.md`,
   `standards/mechanical.md`: each domain's standards.
5. `base.json` and the ten files in `clean/`.

You can read and write files in this directory only. There is no shell and no web. Do not change
`base.json` or anything in `clean/`.

## The errors

Each is a number that breaks a rule its domain's standards file states: a rating exceeded, a
derating not applied, a margin below the standard's minimum, a timing or rate budget overrun. It
sits in a node of the revision's `assigned_role`'s domain. The design and the parts sheet give
everything a careful reader needs to see it. It is not a unit slip, a scale slip with no standard
behind it, a structure that no longer balances, or a node a change did not reach. It is one a
competent engineer, or a capable model, could plausibly make and not notice. Spread them over the
four domains, at least two in each.

## What to write

`injections/s01.json` to `injections/s10.json`, in the form `format.md` gives for an injection,
with `error_class` `"standard"`, `edge` `null`, `expected_check` the check in the architecture's
table nearest to it, and a `description` that names the standards file and the rule, the quantity,
what it should be, what it is, and why. Nothing in any node may say that it is wrong or that
anything was changed on purpose (`format.md`, "Words").

## How to work

Read everything first. Write `plan.md`: for each revision, the rule it will break and where. Then
write the ten injection files. Then stop.
```
