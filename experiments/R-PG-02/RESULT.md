# R-PG-02 — result

> **Preface, 22 October 2026: the reviewers' parts sheet was incomplete. It changes no
> number; everything below it is as first committed.**
>
> - **What happened.** From PR #26 (17 October 2026) on, the parts sheet in every review
>   packet was the corpus's `sources.json`, copied byte for byte. Its format lets a row hold
>   one number or nothing and has no note field, so every row whose value is a range, a list,
>   a min/typ/max or text reached the reviewers empty, and no notes reached them. On the
>   reference design's sheet that is 62 of 163 rows (44 with two or more numbers, 11 with one
>   number plus qualifying words, 7 text only) and all 130 notes. The designs' authors worked
>   from the complete sheet. The physics gate never reads the parts sheet and was unaffected.
> - **What it means here.** Both arms received identical sheets, so the comparison of arm
>   against arm below is not biased by this. Reviewers in both arms were handicapped wherever
>   a check needed a range, a limit or a note, and that handicap may weigh differently on
>   different reviewer roles, so per-role figures should be read with it in mind.
> - **What follows.** The sheet format is being fixed, and a new pre-registered experiment,
>   R-PG-01b, will re-run R-PG-01's reviewer arm with the complete sheet. No number in this
>   file changes.

**Pre-registration:** `CRITERIA.md`, frozen at commit `254a2ff` (19.10.2026); its facts filled
by `4fe482a` (the pick: K) and `841e6d4` (the fresh set's manifest digest), both 19.10.2026,
before the first review; R7 item 11 added with `ac40cff` and amended with `73c492c`, `8a690d7`
and `0132d01` (all 19.10.2026, before any review); R7 item 12 added with `0936f1f`
(20.10.2026), which also changed R8's lane count and §12 row 9 from 4 lanes to 8. That commit
was made after attempt 1 had started producing reviews, none of which was read. The file as run is git blob
`dd3d23d4ed894799e58769d344819a6e2f51228b` (sha256
`c3dc40fea1b0a218e3b1e19af2dd8a543292176a9b7da10dd7d9fb064c0b9eb0`) at `0936f1f`.
**Run commit:** `0936f1f7a36392cecc2091f28cd7b3dee524b02f`, the last commit that changes
`experiments/R-PG-02/`, descending from the tuning-freeze commit (configuration K,
`48929eb2f1ba0d770b02914e4a2b29a62a27e486`). The launch script held it to every hash of §3
and refused nothing (`evidence/launch_attempt-2.log`).
**Run:** attempt 2, 20.10.2026. The three runs started together at 05:44:26 UTC; the last ended
13:55:13 UTC, and the launch script ended at 13:55:36 UTC.
**Machine:** one ARM virtual machine (Linux arm64, 2 cores, 12 GB). Claude Code `2.1.301`, Linux
arm64 build, sha256 `1e119036…8604f0`; auth mode `subscription`. Reviewers on
`claude-sonnet-5`, every role, paired and generalist.
**Scored:** 20.10.2026, with the frozen scripts at the run commit, on copies of the three run
directories taken from the machine after the runs ended. The scripts' own tests pass at that
commit (55 passed).

---

## Verdict

| # | Criterion | Form | Measured | 95 % interval | |
|---|---|---|---|---|---|
| P1 | The gate accepts every correct revision | A_gate = 40/40 on the old set | **40/40** (strict, every failing record counted: 40/40) | Wilson [0.912, 1.000] | **met** |
| P2 | The gate rejects for the right reason | R_gate on the fresh set ≥ 20 of 40 | **20/40** | Wilson [0.352, 0.648] | **met**, at the floor |
| P3 | The paired reviewers discriminate | J_paired's interval wholly above 0 | **J_paired = 0.45** | bootstrap [0.25, 0.65] | **met** |
| P4 | Pairing adds value | J_paired − J_generalist's interval wholly above 0 | **−0.35** | bootstrap [−0.575, −0.125] | **not met** |
| P5 | The fixes were not tailored | tailoring if the practice-to-fresh drop's interval is wholly above 0; possible tailoring if the point drop > 0.15 and the interval holds 0 | paired: drop **−0.40**; gate: drop **0.05** | paired [−0.75, −0.05]; gate [−0.225, 0.325] | **met** for both layers: neither tailoring nor possible tailoring |

**P4 is not met, and not by a margin the set cannot resolve.** On the same 40 pairs at the same
commit, the generalist reviewer's J (0.80) is higher than the paired reviewers' (0.45), and the
interval of the difference lies wholly below zero. The pre-registration stated before the run
that the generalist's right-reason rule is looser than the paired rule (its cell is one
consistency line per role, which cannot locate the error) and that this biases J_generalist
upward against J_paired (§4.1, §9). That bias is real and is printed beside the result; it does
not change the criterion's outcome. The generalist also accepted more correct twins (38/40
against 29/40), and that half of J does not depend on the naming rule at all.

**P2 is met exactly at its floor** (20 of 40), with an interval that spans 0.35 to 0.65.

**P1's fresh-set half is not a result:** the fresh twins pass the gate 40 of 40 by construction
(R4).

## Primary results, fresh set (40 injected, 40 twins)

| Layer | R (of 40) | A (of 40) | J | Raw reject | No verdict (inj. / twins) |
|---|---|---|---|--:|---|
| Paired reviewers (arm A) | **29** [0.572, 0.839] | **29** [0.572, 0.839] | **0.45** [0.25, 0.65] | 37 | 1 / 5 |
| Generalist reviewer (arm B) | **34** [0.709, 0.929] | **38** [0.835, 0.986] | **0.80** [0.625, 0.95] | 36 | 0 / 0 |
| Gate (from arm A's run) | **20** [0.352, 0.648] | 40 (by construction, R4) [0.912, 1.000] | **0.50** [0.35, 0.65] | 20 | — |

R and A intervals are Wilson 95 %; J intervals are the bootstrap over pairs, 10,000 draws, seed
13, 2.5th and 97.5th percentiles (§6).

- **The primary contrast:** J_paired − J_generalist = **−0.35**, paired bootstrap
  **[−0.575, −0.125]**.
- **Cost ratio,** paired to generalist, tokens per item from the binary's own totals: median
  **2.10**, ratio of totals **2.34**. The paired arm spent 51,962,576 tokens over its 80 reviews
  (649,532 per review; USD 100.54 at the 2026-10-16 price sheet, a list-price equivalent with
  cache writes at the one-hour rate, not a bill); the generalist arm 22,161,445 (277,018 per
  review; USD 47.22).
- **The right-reason condition's effect:** the paired reviewers rejected 37 of 40 injected items
  and named the error in 29; the generalist rejected 36 and named it (on its consistency line,
  with the twin condition) in 34. Without the twin condition: paired 29, generalist 36.

### Reviews with no verdict, and unscored items (§4.4)

Every one counts against its layer in both directions, as pre-registered. Unscored items: **0**
in every arm (every cell of §4.1's table is filled).

| Arm | Item | Role | Outcome | Cause |
|---|---|---|---|---|
| A, fresh | injected `a12` | control | `review_unavailable` | `invalid_verdict` |
| A, fresh | twin `a31` | electrical | `blocked` | blocking specification defect |
| A, fresh | twin `a33` | electrical | `blocked` | blocking specification defect |
| A, fresh | twin `a09` | firmware | `blocked` | blocking specification defect |
| A, fresh | twin `a19` | firmware | `blocked` | blocking specification defect |
| A, fresh | twin `a34` | firmware | `review_unavailable` | `invalid_verdict` |
| B, fresh | — | — | none | — |
| A, old | twin `a12` | electrical | `blocked` | blocking specification defect |
| A, old | twin `a18` | firmware | `blocked` | blocking specification defect |
| A, old | twin `a20` | firmware | `blocked` | blocking specification defect |

No review ended unavailable on an infrastructure failure: the two that met one (a-fresh) reached
a verdict on a retry (below).

Beside the headline, for the paired reviewers on the fresh set:

- **among items with a verdict only:** R 29/39, A 29/35, J 0.572;
- **the range if each no-verdict review had gone either way:** R 29–30, A 29–34, J 0.45–0.60.

The upper end of that range does not reach the generalist's 0.80, so P4's outcome does not
depend on the six reviews without a verdict.

### Sheet-flaw rejections (§4.2)

| Arm and set | Sheet-flaw rejections | A without them | J without them |
|---|--:|---|--:|
| Paired, fresh | 1 | 29 of 39 | 0.469 |
| Generalist, fresh | 0 | 38 of 40 | 0.80 |
| Paired, old | 3 | 25 of 37 | 0.351 |

The primary figures above count them as rejections (conservative), as pre-registered.

## The old set (secondary; R-PG-01's corpus, seen at class level, R7 item 2)

| Layer | R (of 40) | A (of 40) | J | Raw reject |
|---|---|---|---|--:|
| Paired reviewers | 27 [0.520, 0.799] | 25 [0.470, 0.758] | 0.30 [0.075, 0.50] | 37 |
| Gate | 16 [0.263, 0.554] | **40** [0.912, 1.000] | 0.40 [0.25, 0.55] | 16 |

- **In R-PG-01's sense** (any failing record), the gate caught **16 of 40**, beside R-PG-01's 17
  of 40. Every one of the 16 is a right-reason catch ("caught, elsewhere": 0), and every one is
  on its item's expected check (16/16).
- The paired reviewers approved **3 of 40** injected artefacts (R-PG-01: 0 of 40) and accepted
  **25 of 40** twins (R-PG-01: 2 of the 23 twins they judged).
- Paired, among verdicts only: R 27/40, A 25/37, J 0.351; range R 27–27, A 25–28, J 0.30–0.375.
- **Old twins whose own numbers the source check finds differ from their cited rows
  (`mismatch`): 8** (`a17`, `a18`, `a23`, `a24`, `a29`, `a31`, `a36`, `a40`). Reported, never
  scored.
- **Old minus fresh J:** paired **−0.15**, bootstrap [−0.45, 0.15]; gate **−0.10**, bootstrap
  [−0.30, 0.125] (each set's pairs resampled on its own, 10,000 draws, seed 13, §6). Both
  intervals hold 0, so **the difference is unresolved** for both layers. An independent
  re-derivation got the same points and the gate's interval, and [−0.45, 0.125] for the paired
  reviewers; the upper bounds differ by one bootstrap step.

## The practice set (reported, never a result)

The practice run the pick names for K is the last calibration round's run (seed 11, the account's
fixed paragraphs, sha256 `8580efd0…ab838`); the practice set's manifest is the one §3 names
(`ddc255ab…ddfb0`).

| Layer | R (of 20) | A (of 20) | J |
|---|---|---|---|
| Paired reviewers, last round | 14 | 7 | 0.05 |
| Gate, the practice set gated at the run commit by the tally | 11 [0.342, 0.742] | 20 [0.839, 1.000] | 0.55 [0.35, 0.75] |

The frozen tally reads the paired reviewers' practice R as 14 of 20; the pick (§3) read it as 13
of 20. The two differ by one item because the pick was read, as §3 says, with the first practice
run's scripts and item map, which key the error items by the expected check (R-PG-01's table);
the tally keys them by error class (§4.1's regrouped table). A is 7 of 20 under both. Neither
count changes the pick: K needed A ≥ 6 and R ≥ 11.

## §7, the risk table's first row (reported only, no verdict drawn)

On the fresh set, **A = 2** (injected artefacts the paired reviewers approved, of 40) and
**C = 0** (of those, caught by the gate in R-PG-01's any-record sense). The row's thresholds
(C < 10, or A < 4) are printed beside, as pre-registered, and no verdict is drawn here. R-PG-01's
figures were A = 0, C = 0. As §7 stated before the run, a reviewer that approves fewer injected
errors lowers A and so C; the row and this experiment pull in opposite directions.

For the generalist arm, which the row does not name: it approved 4 of 40 injected artefacts, and
the gate caught 2 of those 4.

## Secondary results (§8)

### 1 and 2. Per class and per role

Fresh set (per class n = 10 pairs):

| Class | paired R | paired A | paired J | generalist R | generalist A | generalist J | gate R | gate J |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| unit | 9/10 | 6/10 | 0.50 | 9/10 | 10/10 | 0.90 | 3/10 | 0.30 |
| magnitude | 4/10 | 7/10 | 0.10 | 7/10 | 9/10 | 0.60 | 0/10 | 0.00 |
| equilibrium | 7/10 | 8/10 | 0.50 | 10/10 | 10/10 | 1.00 | 7/10 | 0.70 |
| propagation | 9/10 | 8/10 | 0.70 | 8/10 | 9/10 | 0.70 | 10/10 | 1.00 |

| Role (pairs) | paired R | paired A | paired J | generalist R | generalist A | generalist J | gate R | gate A |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| control (15) | 6 | 14 | 0.33 | 10 | 13 | 0.53 | 9 | 15 |
| electrical (10) | 9 | 5 | 0.40 | 10 | 10 | 1.00 | 3 | 10 |
| firmware (6) | 5 | 1 | 0.00 | 5 | 6 | 0.83 | 3 | 6 |
| mechanical (9) | 9 | 9 | 1.00 | 9 | 9 | 1.00 | 5 | 9 |

Old set:

| Class | paired R | paired A | paired J | gate R | gate J |
|---|--:|--:|--:|--:|--:|
| unit | 6/10 | 7/10 | 0.30 | 4/10 | 0.40 |
| magnitude | 3/10 | 8/10 | 0.10 | 0/10 | 0.00 |
| equilibrium | 8/10 | 5/10 | 0.30 | 2/10 | 0.20 |
| propagation | 10/10 | 5/10 | 0.50 | 10/10 | 1.00 |

| Role (pairs) | paired R | paired A | paired J | gate R | gate A |
|---|--:|--:|--:|--:|--:|
| control (17) | 9 | 15 | 0.41 | 4 | 17 |
| electrical (11) | 9 | 2 | 0.00 | 7 | 11 |
| firmware (3) | 1 | 0 | −0.67 | 2 | 3 |
| mechanical (9) | 8 | 8 | 0.78 | 3 | 9 |

Per class n is 10, so only large effects show. The pattern most visible in both sets: the gate
catches no magnitude error (0 of 10 on each set), every propagation error (10 of 10 on each),
and the paired reviewers' acceptance is lowest on the electrical and firmware twins.

### 3. No verdict, repair resumes, schema refusals

The no-verdict reviews are listed above. Per run:

| Run | Repair resumes used | Verdicts after one | `invalid_verdict` lines | Schema refusals (reviews with any) |
|---|--:|--:|--:|---|
| a-fresh | 1 | 1 | 2 | 97 (63) |
| b-fresh | 0 | 0 | 0 | 66 (57) |
| a-old | 3 | 3 | 0 | 97 (59) |

### 4. The gate's checks

Fresh set, arm A's run. Passes are printed with the observations they judged; a pass with nothing
judged is "nothing in scope".

| Check | Injected: fail / pass (evaluated; nothing in scope) / unchecked | Twins: fail / pass (evaluated; nothing in scope) / unchecked |
|---|---|---|
| units | 6 / 74 (3,571; 0) / 968 | 0 / 80 (3,858; 0) / 970 |
| magnitude | 0 / 0 (0; 0) / 1,137 | 0 / 0 (0; 0) / 1,137 |
| equilibrium | 0 / 26 (0; **26**) / 54 | 0 / 26 (0; **26**) / 54 |
| power | 0 / 49 (98; 0) / 134 | 0 / 49 (98; 0) / 134 |
| conservation | 14 / 72 (130; 0) / 82 | 0 / 80 (146; 0) / 82 |
| thermal | 0 / 19 (0; **19**) / 122 | 0 / 19 (0; **19**) / 122 |
| propagation | 16 / 10 (64; 0) / 96 | 0 / 21 (109; 0) / 109 |

Old set, arm A's run:

| Check | Injected: fail / pass (evaluated; nothing in scope) / unchecked | Twins: fail / pass (evaluated; nothing in scope) / unchecked |
|---|---|---|
| units | 8 / 72 (4,122; 0) / 1,132 | 0 / 80 (4,520; 0) / 1,133 |
| magnitude | 0 / 46 (46; 0) / 1,436 | 0 / 46 (46; 0) / 1,438 |
| equilibrium | 0 / 28 (0; **28**) / 104 | 0 / 28 (0; **28**) / 104 |
| power | 0 / 75 (140; 5) / 75 | 0 / 74 (140; 4) / 76 |
| conservation | 4 / 76 (76; 0) / 315 | 0 / 80 (80; 0) / 316 |
| thermal | 0 / 5 (0; **5**) / 150 | 0 / 4 (0; **4**) / 152 |
| propagation | 12 / 21 (204; 0) / 250 | 0 / 29 (253; 0) / 273 |

- **The equilibrium check judged nothing on either set.** Every equilibrium pass is "nothing in
  scope", and every other equilibrium record is `unchecked`. Equilibrium passes made on forces
  alone: **0**, on both sets. The fresh set's 7 equilibrium-class catches came from other checks
  (the mass relations of the conservation check among them).
- **The magnitude check judged nothing on the fresh set** (every record `unchecked`), and judged
  46 observations, all passing, on the old set.
- "Caught, elsewhere": **0** on both sets. The expected-check share among the caught: fresh
  **13 of 20**, old **16 of 16**.
- `unchecked` records per class, injected items, fresh: unit 647, magnitude 635, equilibrium 651,
  propagation 660; old: 796, 743, 1,073, 850.
- Headroom refusals against a continuous-rating `current_limit`: **none** on either set; the
  number of `current_limit` values whose cited row is a continuous rating is **0** in each set.
- Quantity names the catalogue does not know, recorded `unchecked`: **44** distinct names on the
  fresh set, **15** on the old (listed in `evidence/tally_2026_10_20.json`).

### 5. R-PG-01-sense figures

| | Fresh, paired | Fresh, generalist | Old, paired |
|---|--:|--:|--:|
| Injected items approved | 2 | 4 | 3 |
| Gate caught, any record | 20 | 20 | 16 |
| Named and caught (R-PG-01's table, by expected check) | 11 | 0 | 14 |
| Named, not caught | 12 | 0 | 8 |
| Caught, not named | 5 | 16 | 2 |
| Neither | 7 | 19 | 12 |
| No error item in R-PG-01's table | 5 | 5 | 4 |

The same two-by-two under this experiment's naming rule (§4.1): fresh paired 15 / 14 / 5 / 6;
fresh generalist 17 / 17 / 3 / 3; old paired 15 / 12 / 1 / 12 (named and caught / named not
caught / caught not named / neither), 0 items without a cell. R-PG-01's table has no generalist
column, so the generalist's row under it is not a naming result.

### 6. The fresh set's pre-run record (R4)

Between session A and session B, the base design and the forty clean revisions went through the
loader, the gate and the source check three times:

- **first pass:** the base returned once, by the loader (a derived quantity cited a row that is
  not one number);
- **second pass:** **all 40 clean revisions returned once, by the gate, on the conservation
  check** (231 failing records, every one a mass relation); the source check returned none;
- **third pass:** nothing returned.

So the gate returned 40 twins (once each, all on conservation) and the source check returned 0.
At the launch the precondition held again at the run commit: 40 of 40 twins with no failing
record, source check `mismatch` 0 (`subtracted` 71 and `unresolved` 30, the sheet's own, listed),
records sha256 `f7868191…0002621`, as filled in §3. `current_limit` values citing a continuous
rating: 0.

### 7. Lanes, retries, pauses and wall clock

| Run | Lanes | Wall clock (UTC) | Retries (delays) | Lane pauses |
|---|--:|---|---|--:|
| a-fresh | 3 | 05:44:29 – 11:51:05 | 3 on 2 reviews (60 s, 60 s, 900 s); both ended with a verdict | 0 |
| b-fresh | 3 | 05:44:30 – 07:52:33 | 0 | 0 |
| a-old | 2 | 05:44:29 – 13:55:13 | 0 | 0 |

The launch log prints b-fresh's end as 11:51:24 because the script waits on the runs in order;
its last review ended at 07:52:33. Every review and its twin ran on the lane drawn before the run
(`lanes.py check`: holds on all three runs, no record off its lane, none missing).

Per lane (R_rev / A_rev / reviews with no verdict, of the pairs on the lane):

| Run | Lane 0 | Lane 1 | Lane 2 |
|---|---|---|---|
| a-fresh | 11 / 8 / 2 (13 pairs) | 9 / 10 / 3 (13) | 9 / 11 / 1 (14) |
| b-fresh | 10 / 12 / 0 (13) | 12 / 13 / 0 (13) | 12 / 13 / 0 (14) |
| a-old | 12 / 11 / 2 (20) | 15 / 14 / 1 (20) | — |

The two fresh arms shared every hour from 05:44 to 07:52; after that only arm A was reviewing.
The three tries that met an infrastructure failure started between 06:23 and 06:31 UTC, while all three runs were running; the retries that followed reached a verdict.

### 8. Cost

| Run | Tokens, every try | Per review | Input / output / cache read / cache write (verdict lines) | USD, list-price equivalent |
|---|--:|--:|---|--:|
| a-fresh | 51,962,576 | 649,532 | 774 / 5,312,543 / 31,485,593 / 10,279,050 | 100.54 |
| b-fresh | 22,161,445 | 277,018 | 696 / 2,033,189 / 14,110,578 / 6,016,982 | 47.22 |
| a-old | 47,352,089 | 591,901 | 736 / 5,453,374 / 31,210,620 / 10,687,359 | 103.53 |

Price sheet 2026-10-16; cache writes at the one-hour rate; a lower bound where a review ended
with no verdict. The run was on a subscription, so this is not a bill.

### 9 and 10

Given above: the row's A and C (§7), and the sheet-flaw rejections (§4.2).

## Run integrity

- **R6, the gate is deterministic:** a second gate pass over each set into a fresh directory gave
  byte-identical records, **80 of 80** on the fresh set and **80 of 80** on the old; arm B's gate
  records on the fresh set equal arm A's, **80 of 80**. No deviation.
- **`physgate catches`** over each run directory equals the rows' totals on all three runs
  (a-fresh: caught 20, C 0, twins failed 0; b-fresh: 20, 2, 0; a-old: 16, 0, 0).
- **R3:** the reachability scan over the three sets, the practice copies and runs, and the three
  review roots found no problem; the reviewer's read allowance on the pinned binary passed (29
  tests), and what a reviewer is shown passed (2).
- **R4:** the fresh twins' precondition held (above); the old twins reproduced the freeze's count
  and records exactly (40 of 40, records sha256 `4a23d22d…f8598d11`).
- **The reviewer requests' defaults,** by the instrument pilot's dry run (no model call): 120
  requests, one distinct set of defaults (`claude-sonnet-5`, max tokens 64,000, effort `high`,
  adaptive thinking), recorded in the run's `request_defaults.json`.

### The scans after the run

The launch script's end scans over attempt 2's directory: the real token's value in **0** files;
the prefixes `sk-ant-` and `oat01` in **10** files each. All 10 lie in the dry run's output, none
in the three runs' directories:

- **8** are the sentinel's snapshots of the dry run's eight scripted sessions
  (`dry/rs/<session>/…/sentinel/blobs/pack-…`). They carry repository text that names the two
  patterns (this file's R7 item 11, and a document stating the literal-pattern scans);
- **2** are the dry run's own result (`dry/result.json`) and its console output
  (`logs/dry-run.out`), where the two prefixes appear as the names of the dry run's scan counts.

None of the 10 holds a token-shaped string (either prefix followed by 16 or more token
characters): 0 matches in each file. This is the self-match R7 item 11 anticipated. The launch
log, written after the scan, now also names the prefixes in its own scan lines.

## Attempts

- **Attempt 0** (19.10.2026): its dry run found the instrument fix of R7 item 11. No review ran.
- **Attempt 1, stopped** (R7 item 12): launched at run commit `0132d01` with 4 lanes (1/1/2); the
  three runs started together at 21:23:40 UTC on 19.10.2026. The subscription's weekly usage
  limit was reached 23 minutes after launch (429, `usage_limit_reached`), and the attempt was
  stopped; the three runs ended on the stop signal at 05:27:14 UTC on 20.10.2026 (exit 143), with
  no results file written. **No review of attempt 1 was read or scored**, and none is reported
  here. Its end scans: token 0 files, `sk-ant-` 10, `oat01` 10 (`evidence/launch_attempt-1.log`).
- **Attempt 2,** this result: run commit `0936f1f`, 8 lanes (3/3/2), another subscription
  account. A void attempt is never resumed; attempt 2 started in new directories and new review
  roots.

## Deviations and disclosures

**Deviations: none.** Every pre-registered step ran as written, in the CRITERIA's order, with
the frozen scripts at the run commit: the lane check, the tally (with the practice run and set
the pick names), `read_catches.py` over each run, and `regate.py` (again on both sets; arm B
against arm A). No measurement was impossible as specified, no item was re-drawn, dropped or
replaced, and no review was re-run.

**Disclosed exposure before the freeze (R7), carried beside the headline:**

1. The planner of the fixes saw R-PG-01 corpus detail beyond its published counts (base node
   identifiers; the injection sites of `a23`, `a29`, `a40`; the shapes of the ten unit-class
   errors). Two hand-made node names that coincided with base identifiers were renamed before any
   fix. From then on, nobody working on the fixes read the planning note, R-PG-01's result or its
   readiness material. This is one reason the fresh set is primary.
2. The old set is seen at class level; the fixes target the error kinds R-PG-01's counts named.
   The old set cannot show that the fixes generalise.
3. The old twins' gate outcome was measured once, count only, at the freeze (40 of 40).
4. The gate's fixes were written against hand-made errors. Three gate relations were proposed
   from the practice authors' vocabulary (`_mass` read as a mass; `torque_peak` against
   `reaction_moment`; `supported_mass` against the masses carried), each written as a general
   rule with its own false-positive check on every clean design. The fresh set's authors use
   the same vocabulary, which may favour the gate on the fresh set.
5. The drafter of the pre-registration read R-PG-01's criteria and published counts, the
   planner's exposure statement, the practice set's tuning metrics and its provenance; no file of
   the old or fresh set, no review, gate record or results row of R-PG-01.
6. The practice set shares the fresh set's parts sheet and brief, by design.
7. The runtime differs from R-PG-01's: Linux arm64 on an ARM virtual machine, not macOS on the
   laptop.
8. The neutral trajectory plausibly biases J_rev downward; in K, the account's fixed paragraphs
   are meant to reduce this.
9. From the evening of 18.10.2026, development and review agents ran on `claude-fable-5-1`. The
   two calibration rounds' rubric rules were drafted blind by a development agent on that model
   and approved and promoted by the owner. No evaluation session (author, reviewer or role) ran on
   it; the four authoring sessions' checks record `claude-opus-5-5` alone.
10. The order change: the fresh set was authored while the last practice round ran, and the
    configuration that judged it was picked afterwards, mechanically (K: A 7/20, R 13/20).
    The authoring ran on the ARM virtual machine as new sessions in sandboxes of their own (Read,
    Write and Edit only); their recorded checks show no tool outside that set, no guard refusal,
    no gate or answer mention, and no secret in their output.

    The owner's statement (Yasin Hessnawi, 21.10.2026):

    > The fresh set was authored on 19.10.2026 by four new Opus sessions on the Oracle server,
    > launched by a runner agent following a fixed command sheet; the runner read only counts,
    > exit codes and audit summaries. No person or agent involved in tuning the gate or the
    > reviewers opened a file of the fresh set before the run.
11. An instrument fix before the run (19.10.2026, attempt 0's dry run): the pilot's stand-in and
    parameters, in the pilot script only; no pinned tree changed. The dry run's prefix scans
    self-match on repository text, as found again here (above).
12. Wider lanes after a stopped attempt (20.10.2026, before any review was read): 4 lanes to 8,
    another subscription account. No review of attempt 2 ended unavailable on a rate limit.

**Observations made while scoring, none of which changes a number:**

- The practice R for P5 is 14 of 20 by the frozen tally and was 13 of 20 by the pick's practice
  scripts; the two keys differ (above). P5 uses the tally's figure, as §6 says.
- The launch log's end time for b-fresh is the time the script reached it, not the run's (above).

**The rubric approver's exposure statement (R2)** (Yasin Hessnawi, 21.10.2026):

> Yasin Hessnawi approved and promoted the rubric changes for practice rounds 1 and 2 on
> 19.10.2026. Before approving he had seen the drafters' change summaries, the practice-round
> results (rounds 0 and 1), and R-PG-01's published result. He had not seen any file of the fresh
> set or any R-PG-02 review.

**Published under §10:**

| What | Where |
|---|---|
| The results rows, one per item and arm | `evidence/rows_*.jsonl` |
| The tally's full output; `physgate catches` over each run, held to the rows | `evidence/tally_2026_10_20.json`, `evidence/post_run_checks_2026_10_20.txt` |
| The fresh corpus (manifest sha256 `e76a4904…d37620c`, checked after the copy) | `corpora/injected-errors/fresh-v1/` |
| Its authors' records, the frozen briefs and the two continuation messages (each digest checks) | `fresh-authoring/` |
| The practice corpus (manifest sha256 `ddc255ab…ddfb0`, checked after the copy) | `practice/corpus-v1/` |
| The tuning record (R9): every reviewer-track iteration, the round not kept included, with its configuration, both directions and its tokens; the two rubric rules | `practice/README.md`, `practice/tuning/` |
| Every R7 exposure, beside the headline; the rubric approver's statement | this file |

Before they were committed, the added files were scanned, counts only: 133 files; the real
token's prefixes `sk-ant-` and `oat01` appear in 2 files, the two launch logs' own scan lines,
and no file holds a token-shaped string. The sessions' transcripts and the runtime's account
files are not published (`fresh-authoring/README.md`).

## Limits

The limits stated before the run (§9) hold, and four of them bear directly on these numbers:

- **One stand-in design and one parts sheet** for all three sets; nothing here generalises beyond
  this design class. **One author pair** wrote the fresh set, so one author's style can be part of
  the primary result.
- **The generalist's right reason cannot locate the error.** Its R is read under a looser rule
  than the paired R, which biases J_generalist upward. The acceptance half of the contrast (38/40
  against 29/40) carries no such bias.
- **The gate's reach is narrow, as stated:** the unit check judges dimension and sign, not scale;
  the magnitude check holds one sourced range and no class envelope (it judged nothing on the
  fresh set and caught no magnitude error on either set); the equilibrium check judged nothing on
  either set, so the equilibrium-class catches are the mass relations'.
- **At 40 per direction,** about 30 points is the smallest difference between two layers this
  resolves; per class (n = 10) only large effects show. Reviewers are not deterministic and each
  arm ran once, so no claim about reviewer variance is made.

## Reproducing it

- Run commit `0936f1f`; configuration K, `48929eb`; gate tree `1e169aac`, reviewers tree
  `e072e6a9`, instrument tree `93e5c327`, rubrics tree `b5d5a31e`, rubric digests, bounds tables,
  spelling module, catalogue digest and account paragraphs as in `CRITERIA.md` §3, each checked by
  the launch script (`evidence/launch_attempt-2.log`).
- Sets: old `corpora/injected-errors/v1/` (manifest `41553301…c026a`, seed 7); fresh `fresh-v1`
  (manifest `e76a4904…d37620c`, seed 13); practice (manifest `ddc255ab…ddfb0`, seed 11).
- Scoring, from a checkout of `0936f1f`, on the three run directories:
  - `python -I experiments/R-PG-02/lanes.py check <run> <set> <seed> <lanes>`, each run;
  - `python -I experiments/R-PG-02/tally.py --a-fresh … --b-fresh … --a-old … --fresh-corpus …
    --old-corpus corpora/injected-errors/v1 --practice-run <last round's run> --practice-corpus
    <practice set>`;
  - `python -I experiments/R-PG-02/read_catches.py <run>`, each run;
  - `python -I experiments/R-PG-02/regate.py again <set> <run> <seed> <new dir>` for both sets,
    and `regate.py compare <a-fresh> <b-fresh>`.
- Evidence: `evidence/rows_a-fresh.jsonl`, `evidence/rows_b-fresh.jsonl`,
  `evidence/rows_a-old.jsonl` (the results rows, one per item and arm);
  `evidence/tally_2026_10_20.json` (every figure above, per item included);
  `evidence/post_run_checks_2026_10_20.txt` (the lane checks, `physgate catches` output, the
  regate results and the scripts' tests); `evidence/launch_attempt-1.log` and
  `evidence/launch_attempt-2.log`.
