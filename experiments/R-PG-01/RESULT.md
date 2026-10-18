# R-PG-01 — result

**Pre-registration:** `CRITERIA.md` frozen at commit `8bc03fc` (2026-10-18), sha256
`c7a7da47505988fd06ca7b613b7ecacd4395d87aa67052272464d774936f53a4`. Nothing under this
directory changed after the freeze; this file is added beside it.
**Run:** attempt 1, from a clean checkout of `8bc03fc` on the macOS laptop, started
2026-10-18 03:33:27 UTC; the last review ended 15:50:01 UTC and the last gate line was written
15:50:12 UTC (12 h 17 min of wall clock, against about 11 h expected). Run id `rp1-1`, seed `7`.
**Analysis:** the experiment's own scripts at `8bc03fc` (`tally_rows.py`, `read_catches.py`,
`regate_r6.py`), run from the run's checkout against the run directory after the run had
ended. No script, threshold, rule or criterion was changed, and no review was re-run.

### What the launch script verified before the first review

Every line below is `ok` in the launch log; any mismatch would have stopped the run.

| Pinned (§2) | Verified value |
|---|---|
| Run commit, clean, on `origin/master`, last to change `experiments/R-PG-01` | `8bc03fc65f3a555f8f4f737eb5eeea1c6f179670` |
| Gate tree `src/physgate/gate/` | `29e7c8061e4f5e54b815afd41bf98f9e6455a7c3` |
| Bounds blob / sha256 | `cdeb9736d93362120f8f08f0244ab449b7bd5f90` / `b75d14d541243108d02f0afc1414a8cd61493f694325c9c2e4f09e30cfa27071` |
| Unit-spelling blob | `eaa4ce697092d27545a19c87c6d92fc6f1e966fc` |
| Instrument tree `src/physgate/evaluation/inject/` | `af7ead4ac5579c86b6e19ffe7a02991ac9872eca` |
| Reviewers tree `src/physgate/reviewers/` | `7df979eecb5b9acba572c5687747ea33586a87e1` |
| Rubrics tree `knowledge/reviewers/` | `dd203340de8cee2f42878bb09ee72e64dfe1465b` |
| Rubric sha256, control | `18be8569a3743d6f9f5ff554ac6fd7e7c86b082ffaad4c08d0a40a00bac111f5` |
| Rubric sha256, electrical | `a1b78302cf116ce471bf24a484de24a1e98e8679256e41d5f36b3dd4f48219b3` |
| Rubric sha256, firmware | `e265ef4733443d1af8a8152a8831fa97f999c3fcae0acc8f12f48fe1faed5f8a` |
| Rubric sha256, mechanical | `3ca83fe1099481ff4c32681b7e63a594e907dd01bcd6a56a8160ed0a8e0783fa` |
| Corpus tree / manifest sha256 | `77782679f15eae4301e86516541b4a3c5c6613b0` / `41553301d5b036f84df289ee6d8c87ecce4504d5a09969e05291e23c9ebc026a` |
| Quantity catalogue digest | `171b054b61f703fee2aaf750b4ff107754bbf0726882e18531cb92db0028d69f` |
| Binary sha256 / version | `1f04c69e1c24e4d0a716a863af0aad8fc64d49a499334c29701f073700276b99` / `2.1.301` |
| `params.json` (validated against the instrument's schema) | sha256 `51e1e42deaad7cba5c149612de7bba5839f454e6e01a5c63e76a33adb6437f6a` |
| R3 scan | no problem; 15 library files checked against 45 corpus files |
| R3 read allowance on the pinned binary | 29 passed; what a reviewer is shown: 2 passed |
| R4 at the run's commit | 40 of 40 twins with no failing record, 40 of 40 `pass`, records sha256 `ea3d581a027abd3538c3aa5271f169ca8ddc2d868e5f7fe104739ef1ccb8e75c` (the pinned value) |

Every one of the 54 reviews that came to a verdict records the rubric digest of its role above,
and every review line, with or without a verdict, records `claude-sonnet-5`. `instrument.json`
records binary version `2.1.301`, auth `subscription`, effort `high`, max output tokens
`64000`, token ceiling `400000`, 80 turns, 4500 s, 0 binary retries, clean twins reviewed,
seed 7, gate mode `observe`.

**Run files** (sha256): `results.jsonl`
`a7babbdddbf01439591a13ce940b1fcff6a8c8c4e9dfad17620d42d5522fdbe4`; `events.jsonl`
`565357bb04c1cdd46e090e54094d91e5b5eaadc6a58300c9c485b6220f2b1559`; `controls/events.jsonl`
`56eec2f9ae707c15f43ec624d83e7794e28ca7322fad61a9f7abf77e0cade20a`; `instrument.json`
`4db410f72a8f5aa656609eedd9e36e7e6aece5c9ff1a62de9c2b9b1f123d1157`.

---

## Primary result: the kill criterion fires

| Quantity (§3, §5) | Value | n |
|---|--:|--:|
| **A**, injected artefacts the reviewers approved | **0** | 40 |
| **C**, of those A, caught by the gate | **0** | 0 |
| Kill criterion (C < 10 or A < 4) | **fires**, on both limbs | |

- The reviewers came to a verdict on 28 of the 40 injected artefacts and rejected all 28
  (`fail`). The other 12 came to no verdict (`review_unavailable`, see below) and count as not
  approved (§3). No injected review was `blocked`.
- **The neutral-trajectory bias (R2) runs upward:** reviewers shown less than a full trajectory
  have less to object to, which plausibly raises A and C. A is 0 regardless.
- **Interval method:** `CRITERIA.md` names none, so no interval is part of the pre-registered
  result. For reading only, not pre-registered: the exact (Clopper–Pearson) 95 % interval for
  the approval rate is 0 to 0.088 over the 40 artefacts, and 0 to 0.123 over the 28 judged ones.
- **The headline quantity is empty.** With no approved artefact there was nothing for the gate
  to catch "after the reviewers passed it", so this run does not show the gate catching an
  error the reviewers approved, and it does not show that it would fail to. It shows that these
  reviewers, on this corpus, approved nothing.
- **`physgate catches --run-dir`** agrees with the rows: `caught_after_reviewer_passed` 0 = C,
  `artefacts_caught` 17 = the rows' gate catches, and the controls log catches 0
  (`read_catches.py` holds; output in the appendix).

### How much the unavailable reviews could move it

The frozen rule counts the 12 unavailable injected reviews as not approved. Had every one of
them been an approval instead, A would be 12 and C would be 5 (the gate caught 5 of those 12:
`a01`, `a03`, `a19`, `a24`, `a35`). C < 10 under every assignment of the 12, so **the kill
criterion fires whatever those reviews would have said**. The A < 4 limb alone is not robust to
them: it would not fire if 4 or more of the 12 had been approvals.

## Reviews that came to no verdict

### The frozen rule, as written

- §2: the instrument retries a review once when, and only when, it ended for an infrastructure
  failure; any other cause is not retried.
- §3: a review that still produces no verdict counts as **not approved** and is listed; the
  artefact is never re-drawn. R5: the denominator stays 40.
- §6 item 9: a `blocked` or `review_unavailable` review lowers A, and the kill reading of §5
  is not changed by this count.
- §6 item 10: a review with no `review_ran` line cites nothing; so does a twin's.

The run applied it exactly. 26 of the 80 reviews came to no verdict: 12 injected artefacts and
14 clean twins.

- **25 ended with `api_error`** (cause `infrastructure`, detail "the session ended with
  api_error"). Each was retried once and the retry also ended with `api_error`. The retry
  began at once and ended about 64 s after the failure before it: the instrument's one retry
  has no delay (the run parameters' retry delays belong to the orchestrator's loop, which the
  instrument does not use).
- **1 ended with `invalid_verdict`** (twin of `a03`, mechanical, 07:01:14 UTC): the binary's
  cap on refused structured verdicts (5 attempts) ended the session. Not an infrastructure
  failure, so not retried.
- **2 more reviews failed once with `api_error` and recovered on their retry** (twins of `a02`
  and `a11`; both then rejected); they are judged reviews.

### By time window (UTC, 2026-10-18; the time a session ended)

| Window | Session ends with `api_error` | Injected artefacts left unavailable | Twins left unavailable | Recovered on retry |
|---|---|--:|--:|---|
| 1 | 11:12:05 – 11:16:28 | 0 | 2 (`a36`, `a24`, both control) | twin `a02` (retry ended 11:31:46) |
| 2 | 14:01:38 – 14:51:23 | 12 | 11 | twin `a11` (retry ended 15:03:12) |
| — | 07:01:14, `invalid_verdict` | 0 | 1 (`a03`, mechanical) | — |
| **Total** | | **12** | **14** | 2 |

- The review that ended just before window 1 finished at 10:45:40; the first session of window 1
  ran from then until its `api_error` at 11:12:05. The review before window 2 finished at
  13:59:05. In window 2 every one of the 47 sessions ended with `api_error`, 64 to 66 s
  apart, and the next session (twin `a11`'s retry) came to a verdict.
- The operator's account puts the second outage at about 14:33 – 14:48. The log shows session
  failures from 14:01:38 to 14:51:23. Whether that was one outage or several cannot be told from
  the log: it records when sessions ended, so it only bounds the window.
- The run went on through the outage: 23 reviews were lost in 50 minutes, each to two quick
  failures.

Each failure, as the log records it (session end time of the first try, then of the retry):

| Arm | Artefact | Role | First try | Retry | Window |
|---|---|---|---|---|---|
| twin | a36 | control | 11:12:05 | 11:13:11 | 1 |
| twin | a24 | control | 11:14:17 | 11:15:23 | 1 |
| twin | a20 | firmware | 14:01:38 | 14:02:42 | 2 |
| artefact | a06 | mechanical | 14:03:46 | 14:04:50 | 2 |
| twin | a16 | electrical | 14:05:53 | 14:06:57 | 2 |
| twin | a25 | control | 14:08:01 | 14:09:05 | 2 |
| artefact | a08 | electrical | 14:10:09 | 14:11:13 | 2 |
| artefact | a27 | control | 14:12:16 | 14:13:20 | 2 |
| artefact | a35 | electrical | 14:14:24 | 14:15:28 | 2 |
| artefact | a01 | electrical | 14:16:32 | 14:17:35 | 2 |
| twin | a07 | mechanical | 14:18:39 | 14:19:43 | 2 |
| artefact | a11 | mechanical | 14:20:47 | 14:21:51 | 2 |
| artefact | a31 | firmware | 14:22:57 | 14:24:02 | 2 |
| artefact | a24 | control | 14:25:08 | 14:26:14 | 2 |
| twin | a21 | control | 14:27:20 | 14:28:26 | 2 |
| twin | a04 | mechanical | 14:29:32 | 14:30:37 | 2 |
| artefact | a03 | mechanical | 14:31:43 | 14:32:49 | 2 |
| artefact | a12 | electrical | 14:33:54 | 14:35:00 | 2 |
| twin | a35 | electrical | 14:36:06 | 14:37:11 | 2 |
| twin | a18 | firmware | 14:38:17 | 14:39:23 | 2 |
| twin | a23 | control | 14:40:28 | 14:41:34 | 2 |
| twin | a40 | control | 14:42:40 | 14:43:45 | 2 |
| artefact | a07 | mechanical | 14:44:51 | 14:45:57 | 2 |
| artefact | a19 | control | 14:47:03 | 14:48:08 | 2 |
| twin | a19 | control | 14:49:14 | 14:50:19 | 2 |

Five pairs have no verdict on either side: `a03`, `a07`, `a19`, `a24`, `a35`.

### By role and arm (§6 item 9), each with its cause

| Role | Injected: unavailable | Injected: blocked | Twins: unavailable | Twins: blocked |
|---|---|---|---|---|
| control (17) | 3: a19, a24, a27 (infrastructure) | 0 | 7: a19, a21, a23, a24, a25, a36, a40 (infrastructure) | 3: a32, a38, a39 (blocking spec defect) |
| electrical (11) | 4: a01, a08, a12, a35 (infrastructure) | 0 | 2: a16, a35 (infrastructure) | 0 |
| firmware (3) | 1: a31 (infrastructure) | 0 | 2: a18, a20 (infrastructure) | 0 |
| mechanical (9) | 4: a03, a06, a07, a11 (infrastructure) | 0 | 3: a04, a07 (infrastructure); a03 (invalid verdict) | 0 |
| **all (40)** | **12** | **0** | **14** | **3** |

**Its reading (§6 item 9).** The unavailable reviews are a property of the laptop's network,
not of the reviewer or the error: 25 of the 26 fall in two outage windows and are distributed
over roles and arms by the seeded review order. They say nothing about the injected errors. The
three `blocked` reviews are all control twins whose injected artefacts were judged (all three
rejected). By the frozen reading that is the case where a difference could bear on the injected
errors; with n = 3 and no blocked review on any injected artefact, this file draws nothing from
it.

### What they weaken, result by result

| Result | As scored | If every unavailable review had gone the other way |
|---|---|---|
| A (of 40) | 0 | 0 to 12 |
| C (of A) | 0 | 0 to 5 |
| Kill criterion | fires | fires in every case (C ≤ 5) |
| Twins refused (§6 item 7, of 40) | 21 | 21 to 35 |
| Twins approved (of 40) | 2 | 2 to 16 |
| Named, with the twin condition (§6 item 10) | 13 | 9 to 22 |
| Caught, not named (§6 item 10) | 7 | 2 to 10 |
| Named and caught | 10 | 7 to 15 |
| Named, without the twin condition | 13 | 13 to 23 |

The ranges for item 10 are per cell, each taken alone: an unavailable injected review could
have cited anything or nothing, and an unavailable twin review could have cited any of its
artefact's error items. `a31`'s twin cited its only error item, so `a31` could not have been
named. The gate's figures (§6 items 2 to 6) do not depend on the reviews and are not weakened.

## Secondary results (§6, reported, never scored)

### 1 and 8. A and C per class and per role, with the gate's catches beside them

| Class | Artefacts | Reviews: fail / unavailable | **A** | **C** | Gate caught (any review) |
|---|--:|---|--:|--:|--:|
| unit | 10 | 9 / 1 | 0 | 0 | 4 |
| magnitude | 10 | 7 / 3 | 0 | 0 | 1 |
| equilibrium | 10 | 6 / 4 | 0 | 0 | 2 |
| propagation | 10 | 6 / 4 | 0 | 0 | 10 |
| **all** | **40** | **28 / 12** | **0** | **0** | **17** |

| Role | Artefacts | Reviews: fail / unavailable | **A** | **C** | Gate caught (any review) |
|---|--:|---|--:|--:|--:|
| control | 17 | 14 / 3 | 0 | 0 | 5 |
| electrical (newly promoted) | 11 | 7 / 4 | 0 | 0 | 7 |
| firmware | 3 | 2 / 1 | 0 | 0 | 2 |
| mechanical (newly promoted) | 9 | 5 / 4 | 0 | 0 | 3 |

The roles are not balanced: the run's log assigns 17 artefacts to the control role and 3 to
firmware.

### 2. The failing check

All 17 caught artefacts failed on their class's expected check (17 of 17; 0 of 0 among C).
One (`a29`, unit) also failed the propagation check. No artefact was caught only on another
check. Two equilibrium-class artefacts (`a10`, `a13`) have `conservation` as their expected
check and were caught on it.

### 3. `unchecked` records, and errors the gate could not judge

| Class | `unchecked` records | Not caught, with `unchecked` records on the expected check (script's list) |
|---|--:|---|
| unit | 731 | 6: a04, a06, a21, a23, a39, a40 |
| magnitude | 678 | 9: a22, a27, a28, a31, a32, a33, a34, a37, a38 |
| equilibrium | 1005 | 0 |
| propagation | 792 | 0 |

- The script lists an uncaught artefact when its gate result holds any `unchecked` record on
  the expected check. The clean design itself carries such records (the twins have 3758 records
  in all), so the list shows artefacts the gate did not catch where it also left something on
  that check unjudged; it does not by itself show that the planted quantity was the unjudged one.
- **Unit:** the 6 match §7's stated limit (6 of 10 unit-class artefacts are same-dimension
  scale errors the check cannot judge); the other 4 were caught, as §7 states.
- **Magnitude:** 9 of 10 uncaught, consistent with §7's limit (the bounds table holds two
  sourced ranges). The one caught is `a24`.
- **Equilibrium, counted by the analyst from the gate records (counts only, not from the
  script):** the 8 equilibrium-class artefacts whose expected check is `equilibrium` each carry
  two `equilibrium` records, both `pass`, and none `unchecked`. The check judged them and
  passed them. These are misses, not a stated coverage limit; this run does not say why.

### 4. Propagation edges by domain pair

| Edge (source domain → target domain) | Artefacts | A | C | Gate caught |
|---|---|--:|--:|--:|
| control → firmware | a03, a19, a26 | 0 | 0 | 3 |
| electrical → control | a18 | 0 | 0 | 1 |
| electrical → firmware | a15, a17 | 0 | 0 | 2 |
| electrical → mechanical | a01, a02, a35 | 0 | 0 | 3 |
| mechanical → control | a30 | 0 | 0 | 1 |

Five targets are firmware, three mechanical and two control; no concentration on the control
loop. All 10 propagation artefacts were caught.

### 5. The gate's catches by review outcome

| Review outcome | Artefacts | Gate caught |
|---|--:|--:|
| pass | 0 | 0 |
| fail | 28 | 12 |
| blocked | 0 | 0 |
| review_unavailable | 12 | 5 |
| **all** | **40** | **17** |

The gate's total detection is 17 of 40 (descriptive Clopper–Pearson 95 %: 0.27 to 0.59). All
17 catches are on artefacts the reviewers rejected or never judged.

### 6. Gate events and records

| | Injected | Controls (twins) |
|---|--:|--:|
| Gate lines | 40 | 40 |
| Records | 3727 | 3758 |
| Failing records | 26 | 0 |
| Artefacts with a failing record | 17 | 0 |

`physgate catches`: 520 checks run per log; 26 blocking failures, 20 stamped "reviewer had
failed", 6 with no review, 0 "reviewer had passed".

### 7. The reviewers on the 40 clean twins

| Twin review outcome | Count |
|---|--:|
| fail (correct work refused) | **21** |
| pass | 2 (`a14`, `a17`, both electrical) |
| blocked | 3 (control) |
| review_unavailable | 14 |

- **Rate of correct work refused: 21 of 40** (descriptive 95 %: 0.36 to 0.68). Among the 23
  twins that got a pass or fail verdict it is 21 of 23 (0.72 to 0.99).
- So a rejection did not separate an injected artefact from its clean twin, as in the
  instrument pilot (R8).

### 9. `blocked` and `review_unavailable` per role

Above, under "Reviews that came to no verdict".

### 10. Named against caught

Decided by `tally_rows.py` from the item ids in the run's logs; no language model read a review.

| Class | Named and caught | Named, not caught | Caught, not named | Neither | No error item |
|---|--:|--:|--:|--:|--:|
| unit | 3 | 1 | 1 | 5 | 0 |
| magnitude | 0 | 2 | 1 | 7 | 0 |
| equilibrium | 1 | 0 | 1 | 4 | 4 |
| propagation | 6 | 0 | 4 | 0 | 0 |
| **all** | **10** | **3** | **7** | **16** | **4** |

| Role | Named and caught | Named, not caught | Caught, not named | Neither | No error item |
|---|--:|--:|--:|--:|--:|
| control | 2 | 2 | 3 | 10 | 0 |
| electrical | 4 | 0 | 3 | 0 | 4 |
| firmware | 2 | 0 | 0 | 1 | 0 |
| mechanical | 2 | 1 | 1 | 5 | 0 |

- **Named: 13 of the 36 artefacts with an error item** (descriptive 95 %: 0.21 to 0.54). A lower
  bound on naming, as §6 states.
- **Without the twin condition: also 13.** The tables are identical; the condition removed no
  artefact. For 7 of the 13 it was not tested, because the twin's review cited nothing: 4 twins
  unavailable (`a04`, `a18`, `a20`, `a36`), 2 blocked (`a32`, `a38`), 1 approved (`a17`).
- **Caught, not named: 7.** Five of them (`a01`, `a03`, `a19`, `a24`, `a35`) are there because
  the review was unavailable and so cites nothing. Among reviews that came to a verdict, the
  gate caught 12 artefacts with an error item, and the reviewer named 10 of them; the two it
  caught and the reviewer did not name are `a10` (equilibrium, electrical, `conservation`) and
  `a25` (unit, control, `units`).
- **Named, not caught: 3** (`a04`, `a32`, `a38`): the reviewer cited an error item and the gate
  did not catch the error. `a04`'s twin was unavailable, `a32`'s and `a38`'s blocked.
- **No error item: 4** (`a08`, `a12`, `a14`, `a16`): equilibrium artefacts assigned to the
  electrical role, whose `equilibrium` cell is empty.
- The full per-artefact list is in the appendix.

## Reviewer requests' defaults, measured at launch (§2)

The dry run (scripted endpoint, dummy token, no model call) at `8bc03fc` on the pinned binary
recorded 120 requests, all of one shape:

- model `claude-sonnet-5`; `max_tokens` 64000; `output_config.effort` `high`;
- `thinking`: `{type: adaptive, display: updates}`;
- `context_management`: one edit, `clear_thinking_20251015`, keep `all`;
- no sampling field (`temperature`, `top_p`, `top_k` absent);
- beta header: `claude-code-20250219`, `context-management-2025-06-27`, `effort-2025-11-24`,
  `extended-cache-ttl-2025-04-11`, `interleaved-thinking-2025-05-14`, `oauth-2025-04-20`,
  `prompt-caching-scope-2026-01-05`, `thinking-display-updates-2026-08-18`,
  `thinking-token-count-2026-05-13`.

Against the role sessions on this version: the thinking type and the context management are
the same; the beta header is not.

## The instrument pilot (R8), as instrument validation

Reported in `CRITERIA.md` R8 and repeated here as instrument validation, never as a result: on
17.10.2026 at `1c5e988`, on the instrument's four-role test corpus (never this corpus), all 8
reviews rejected; 0 `blocked`, 0 `review_unavailable`; the parts sheet read in 8 of 8; $7.09
for the 8, a mean of 8.0 minutes per review; each injected review carried every class of
rejecting item its twin's review carried. This run reproduced that last pattern on the real
corpus (§6 item 7).

## Blindness (R2) and the rubrics' approval

- The corpus's authors worked blind to the gate's code and output (§2). The error-item table
  was drawn from the rubrics' text alone (§4 R2). The blindness check passed for all 80 review
  worktrees before the freeze (§4 R2), and R3 held at launch.
- The rubrics were drafted, as R2 requires, by authors who had not read the corpus, and
  promoted by the project's human owner (commits `5b49709` and `bd14da5`).
- **Open: whether the approver had seen the corpus or a gate outcome on it.** R2 requires this
  file to state it. The repository does not record it, and the analyst cannot state it. It is
  to be filled in by the owner before this file is merged.

## What this run shows, and what it does not

- **Shown.** The paired reviewers (`claude-sonnet-5`, the four promoted rubrics) approved none
  of the 28 injected artefacts they judged, so A = 0, C = 0, and the kill criterion fires. It
  fires whatever the 12 unavailable reviews would have said.
- **Shown.** The same reviewers refused 21 of the 23 clean twins they judged. Their rejections
  did not distinguish an injected error from correct work on this stand-in design.
- **Shown.** The gate, run on all 40, caught 17 (4 unit, 1 magnitude, 2 equilibrium,
  10 propagation), each on its expected check, with no failing record on any of the 40 twins,
  and gave byte-identical records on a second pass (R6).
- **Shown, by item ids alone and as a lower bound.** Among the reviews that came to a verdict,
  the reviewer's own rubric items named 10 of the 12 errors the gate caught, and named 3 that
  the gate did not catch.
- **Not shown.** That the gate catches errors the reviewers approve: no error was approved, so
  the headline is empty, not negative. Nothing about the 12 injected artefacts that got no
  review. Nothing about reviewer variance (one run, R6). Nothing beyond the stand-in design.
- **Not shown.** Why the equilibrium check passed the 8 equilibrium-class artefacts expected
  on it.

## Departures and anomalies

### 1. The launch script exited 1, after the run, from its own token scan

The run itself completed: `run.log` holds the instrument's closing summary line (`reviews`:
blocked 3, fail 49, pass 2, review_unavailable 26), which it prints only after every row is
written, and `results.jsonl` has 40 rows.

The exit came after that. The script runs under `set -euo pipefail`. Its post-run scan counts
files containing the token with `hits="$(grep -rlF -- "$pattern" … | wc -l | tr -d ' ')"`.
When grep finds nothing (the outcome the scan wants), it exits 1; `pipefail` makes the pipeline
exit 1; the assignment takes that status; and `set -e` ends the script with 1 at the first
pattern. This was reproduced with a pattern absent from an empty directory. So:

- the launch log stops at "the run starts"; the scan lines, the "run ended" line, the
  instrument's exit code and its last line were never written;
- the instrument's exit code is not on record. By its own rule (`cli.py`) it returns 1 whenever
  any review is `blocked` or `review_unavailable`, so with 29 such it would have returned 1 in
  any case;
- **the analyst repeated the two literal-pattern scans afterwards** (counts only): `sk-ant-` and
  `oat01` occur in no file of the run directory or the install; in the logs directory each
  occurs in one file, `dry-run.out`, whose own scan summary names the two patterns as keys with
  count 0. The scan for the token's own value was not repeated: it needs the token, which the
  analyst does not read.

`launch.sh` is an experiment script, not the instrument of §2, and the defect touched no
review, gate record or number. It is not an R1 instrument defect.

### 2. 26 reviews came to no verdict

25 from two network outages on the operator's laptop and 1 from the binary's cap on refused
verdicts. The pilot (R8) had none. The frozen rule handled them as written (above). The
effect: 12 of 40 injected artefacts have no review, which leaves A's and §6 item 10's figures
with the ranges given above; the kill reading is unaffected.

### 3. The instrument's one retry has no delay

The instrument retries an infrastructure failure once, at once. The run parameters'
`infra_retry_delays_s` (`[60, 300]`) are read by the orchestrator's loop and not by the
instrument. Under an outage longer than about two minutes the retry is always spent. This is
what §2 specifies ("retries a review once"), so it is not a departure; it is why one outage
cost 23 reviews.

### 4. The second outage was longer than the operator's estimate

About 14:33 – 14:48 UTC by the operator's account; session failures from 14:01:38 to 14:51:23
UTC in the log. An earlier window, 11:12:05 – 11:16:28 UTC, also cost two twin reviews.

### 5. Time and cost

12 h 17 min against about 11 h expected. The run directory records tokens, not dollars. The
54 reviews that came to a verdict used 520 input, 3,679,657 output, 21,246,645 cache-read and
7,819,862 cache-creation tokens; peak context per session was 92k to 215k tokens (injected)
and 112k to 228k (twins), above the pilot's 85k to 140k.

### 6. No interval method was pre-registered

`CRITERIA.md` names none. The counts above, with their n, are the result. The Clopper–Pearson
intervals given are descriptive and were chosen by the analyst after the run.

### 7. Secondary result 3 is the script's proxy, and one count is the analyst's

The script's "not judged on the expected check" list is read as stated under item 3. The
equilibrium counts under item 3 were added by the analyst from the gate records, counts only.

### 8. The rubric approver's exposure is not yet stated

R2 requires it; see "Blindness (R2)". Open until the owner fills it in.

### 9. The gate on `master` has since changed

`master` has changed `src/physgate/gate/units.py` since `8bc03fc`. Every figure here is the
gate at tree `29e7c806…`, as pinned; none applies to a later gate.

## Checks after the run

| Check | Script | Outcome |
|---|---|---|
| Rows to A, C, kill and §6 | `tally_rows.py` (with `--corpus` for item 4) | exit 0; 40 rows; every row's review outcome and gate verdict agree with the logs |
| Its tests (§9) | `test_tally_rows.py` | 7 passed at `8bc03fc` |
| `physgate catches` held to the rows | `read_catches.py` | holds: C 0 = 0, caught 17 = 17, controls 0 |
| R6, a second gate pass | `regate_r6.py` | 80 compared (40 injected, 40 twins), **0 differ** |
| Controls through the gate (R4's guarantee) | `tally_rows.py` | 0 of 40 twins with a failing record |

---

## Appendix A. Secondary result 10, per artefact

"Named" uses the twin condition; "cited at all" does not. "Deciding items" are the error items
the review cited and the twin's review did not. "unavailable" is `review_unavailable`.

| Artefact | Class | Role | Expected check | Error items | Review | Items the review cited | Twin's review | Items the twin's review cited | Deciding items | Named | Cited at all | Caught |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| a01 | propagation | electrical | `propagation` | ES-34 | unavailable | none | fail | EA-9, EH-1, EH-6, EP-4, EP-5, ES-11, ES-14, ES-15, ES-16, ES-21, ES-6 | none | no | no | yes |
| a02 | propagation | electrical | `propagation` | ES-34 | fail | EA-9, EH-6, EP-4, EP-5, ES-11, ES-14, ES-34 | fail | EA-9, EP-4, EP-5, ES-14, ES-15, ES-16, ES-21 | ES-34 | yes | yes | yes |
| a03 | propagation | mechanical | `propagation` | MS-5 | unavailable | none | unavailable | none | none | no | no | yes |
| a04 | unit | mechanical | `units` | MS-2 | fail | MA-10, MH-2, MS-1, MS-2, MS-28, MS-3 | unavailable | none | MS-2 | yes | yes | no |
| a05 | equilibrium | mechanical | `equilibrium` | MS-4 | fail | MA-10, MP-10, MS-28, MS-3 | fail | MA-10, MS-28 | none | no | no | no |
| a06 | unit | mechanical | `units` | MS-2 | unavailable | none | fail | MA-10, MS-28, MS-3 | none | no | no | no |
| a07 | equilibrium | mechanical | `equilibrium` | MS-4 | unavailable | none | unavailable | none | none | no | no | no |
| a08 | equilibrium | electrical | `equilibrium` | none | unavailable | none | fail | EA-9, EH-6, EP-4, EP-5, ES-14, ES-15, ES-16, ES-21 | none | no error item | — | no |
| a09 | equilibrium | mechanical | `equilibrium` | MS-4 | fail | MA-10, MH-2, MH-5, MS-1, MS-28, MS-3, MS-6 | fail | MA-10, MP-8, MS-24, MS-28 | none | no | no | no |
| a10 | equilibrium | electrical | `conservation` | ES-7, ES-9, ES-33 | fail | EA-9, EH-1, EH-6, EP-4, EP-5, ES-14, ES-15, ES-16, ES-21 | fail | EA-9, EH-1, EP-4, EP-5, ES-11, ES-14, ES-15, ES-16 | none | no | no | yes |
| a11 | equilibrium | mechanical | `equilibrium` | MS-4 | unavailable | none | fail | MA-10, MS-28 | none | no | no | no |
| a12 | equilibrium | electrical | `equilibrium` | none | unavailable | none | fail | EA-9, EH-6, EP-4, EP-5, ES-11, ES-14, ES-15, ES-16 | none | no error item | — | no |
| a13 | equilibrium | mechanical | `conservation` | MS-3, MS-26 | fail | MA-10, MS-26, MS-28, MS-3 | fail | MA-10, MS-28 | MS-26, MS-3 | yes | yes | yes |
| a14 | equilibrium | electrical | `equilibrium` | none | fail | EA-9, EH-1, EP-4, EP-5, ES-16, ES-32 | pass | none | none | no error item | — | no |
| a15 | propagation | electrical | `propagation` | ES-34 | fail | EA-9, EH-1, EH-5, EH-6, EP-4, EP-5, ES-10, ES-11, ES-14, ES-15, ES-16, ES-21, ES-27, ES-28, ES-34, ES-6, ES-7 | fail | EA-9, EH-6, EP-4, EP-5, ES-10, ES-11, ES-14, ES-15, ES-16, ES-21, ES-27, ES-28, ES-33, ES-5, ES-7, ES-8 | ES-34 | yes | yes | yes |
| a16 | equilibrium | electrical | `equilibrium` | none | fail | EA-9, EH-6, EP-4, EP-5, ES-10, ES-11, ES-14, ES-15, ES-16, ES-17, ES-21, ES-27, ES-28, ES-32, ES-33, ES-5, ES-7 | unavailable | none | none | no error item | — | no |
| a17 | propagation | electrical | `propagation` | ES-34 | fail | EA-9, EH-1, EH-3, EH-5, ES-34 | pass | none | ES-34 | yes | yes | yes |
| a18 | propagation | firmware | `propagation` | DS-30 | fail | AC-9, DS-30, DS-4 | unavailable | none | DS-30 | yes | yes | yes |
| a19 | propagation | control | `propagation` | D28 | unavailable | none | unavailable | none | none | no | no | yes |
| a20 | unit | firmware | `units` | DS-27 | fail | AC-9, DS-27, DS-4, DS-5 | unavailable | none | DS-27 | yes | yes | yes |
| a21 | unit | control | `units` | D25, D26 | fail | A7, D10, D11, D13, D17, D22, D23, D29, D3, D30, D33, D4, D6, D7, D8, D9, R1, S2, S4, S5 | unavailable | none | none | no | no | no |
| a22 | magnitude | control | `magnitude` | D25, D27 | fail | A7, D10, D11, D12, D13, D14, D17, D22, D23, D24, D29, D3, D30, D33, D4, D5, D6, D7, D8, D9, R1, S2, S4, S5 | fail | D1, D13, D17, D22, D23, D24, D29, D30, D32, D33, D4, D6, D8, D9, S2, S4, S5 | none | no | no | no |
| a23 | unit | control | `units` | D25, D26 | fail | A7, D1, D10, D11, D12, D17, D22, D23, D24, D27, D29, D3, D30, D32, D33, D4, D5, D6, D7, D8, D9, R9, S2, S4, S5 | unavailable | none | none | no | no | no |
| a24 | magnitude | control | `magnitude` | D25, D27 | unavailable | none | unavailable | none | none | no | no | yes |
| a25 | unit | control | `units` | D25, D26 | fail | A7, D1, D10, D11, D12, D13, D16, D17, D22, D23, D24, D29, D3, D30, D32, D33, D4, D5, D6, D7, D8, D9, R1, S2, S4, S5 | unavailable | none | none | no | no | yes |
| a26 | propagation | control | `propagation` | D28 | fail | A7, D1, D10, D11, D13, D17, D22, D23, D24, D28, D29, D3, D30, D32, D33, D4, D5, D6, D7, D8, D9, R1, R2, S2, S4, S5 | fail | A7, D10, D11, D13, D14, D17, D23, D24, D29, D3, D30, D33, D4, D6, D7, D8, D9, R2, S2, S4, S5 | D28 | yes | yes | yes |
| a27 | magnitude | control | `magnitude` | D25, D27 | unavailable | none | fail | A7, D1, D17, D23, D24, D29, D30, D32, D33, D6, D8, D9, R1, S2, S4, S5 | none | no | no | no |
| a28 | magnitude | control | `magnitude` | D25, D27 | fail | A7, D1, D17, D23, D24, D29, D30, D33, D4, D6, D8, D9, R1, R2, S2, S4, S5 | fail | A7, D1, D10, D11, D13, D17, D21, D22, D23, D24, D29, D3, D30, D33, D4, D5, D6, D7, D8, D9, R1, S2, S4, S5 | none | no | no | no |
| a29 | unit | electrical | `units` | ES-31, ES-32 | fail | EA-9, EH-3, EH-5, EP-3, ES-1, ES-21, ES-3, ES-31, ES-32, ES-33, ES-4 | fail | EA-9, EH-3, EP-3, ES-1, ES-21, ES-3, ES-4 | ES-31, ES-32 | yes | yes | yes |
| a30 | propagation | mechanical | `propagation` | MS-5 | fail | MA-10, MS-5 | fail | MA-10, MP-10, MS-26 | MS-5 | yes | yes | yes |
| a31 | magnitude | firmware | `magnitude` | DS-27 | unavailable | none | fail | AC-9, DS-27, RH-2 | none | no | no | no |
| a32 | magnitude | control | `magnitude` | D25, D27 | fail | A7, D25, D28, R7, R9 | blocked | none | D25 | yes | yes | no |
| a33 | magnitude | control | `magnitude` | D25, D27 | fail | A7, D13, D15, D28, R9, S5 | fail | D1, D13, D17, D23, D29, D30, D33, D6, R1, S2, S4, S5 | none | no | no | no |
| a34 | magnitude | control | `magnitude` | D25, D27 | fail | A7, D13, D15, D17, D28, D6 | fail | A7, D17, D30, D6, S5 | none | no | no | no |
| a35 | propagation | electrical | `propagation` | ES-34 | unavailable | none | unavailable | none | none | no | no | yes |
| a36 | unit | control | `units` | D25, D26 | fail | A7, D25 | unavailable | none | D25 | yes | yes | yes |
| a37 | magnitude | control | `magnitude` | D25, D27 | fail | A7, D1, D10, D11, D12, D13, D14, D17, D23, D24, D29, D3, D30, D33, D4, D5, D6, D7, D8, D9, R1, R2, S2, S4, S5 | fail | A7, D1, D17, D30, D6, D8, D9, S5 | none | no | no | no |
| a38 | magnitude | control | `magnitude` | D25, D27 | fail | A7, D25, D27, D28, R7 | blocked | none | D25, D27 | yes | yes | no |
| a39 | unit | control | `units` | D25, D26 | fail | A7, R9 | blocked | none | none | no | no | no |
| a40 | unit | control | `units` | D25, D26 | fail | A7 | unavailable | none | none | no | no | no |

## Appendix B. The results file

`results.jsonl` as the instrument wrote it, one row per artefact in corpus id order (sha256
`a7babbdddbf01439591a13ce940b1fcff6a8c8c4e9dfad17620d42d5522fdbe4`). `review_id` and
`control_id` are the seeded subtask ids of the injected and the twin review.

<details><summary>40 rows</summary>

```json
{"artefact": "a01", "control_blocking": [], "control_id": "r7c5937cf7daa", "control_reviewer_verdict": "fail", "control_verdict": "pass", "error_class": "propagation", "expected_check": "propagation", "gate_blocking": ["propagation"], "gate_seq": 125, "gate_verdict": "fail", "review_cause": "infrastructure", "review_id": "rc93d11505402", "review_seq": 78, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 0, "reviewer_verdict": "review_unavailable"}
{"artefact": "a02", "control_blocking": [], "control_id": "r9586c782b470", "control_reviewer_verdict": "fail", "control_verdict": "pass", "error_class": "propagation", "expected_check": "propagation", "gate_blocking": ["propagation"], "gate_seq": 116, "gate_verdict": "fail", "review_cause": null, "review_id": "r9c9f8710a94b", "review_seq": 64, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 1071077, "reviewer_verdict": "fail"}
{"artefact": "a03", "control_blocking": [], "control_id": "r4363fa4a4404", "control_reviewer_verdict": "review_unavailable", "control_verdict": "pass", "error_class": "propagation", "expected_check": "propagation", "gate_blocking": ["propagation"], "gate_seq": 129, "gate_verdict": "fail", "review_cause": "infrastructure", "review_id": "rdc5ea3136439", "review_seq": 86, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 0, "reviewer_verdict": "review_unavailable"}
{"artefact": "a04", "control_blocking": [], "control_id": "rd8bd62908fa0", "control_reviewer_verdict": "review_unavailable", "control_verdict": "pass", "error_class": "unit", "expected_check": "units", "gate_blocking": [], "gate_seq": 114, "gate_verdict": "pass", "review_cause": null, "review_id": "r99ce162a5d89", "review_seq": 62, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 455673, "reviewer_verdict": "fail"}
{"artefact": "a05", "control_blocking": [], "control_id": "r37c26145d329", "control_reviewer_verdict": "fail", "control_verdict": "pass", "error_class": "equilibrium", "expected_check": "equilibrium", "gate_blocking": [], "gate_seq": 94, "gate_verdict": "pass", "review_cause": null, "review_id": "r01c2a47e288b", "review_seq": 42, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 633200, "reviewer_verdict": "fail"}
{"artefact": "a06", "control_blocking": [], "control_id": "r152ac3d7f6d5", "control_reviewer_verdict": "fail", "control_verdict": "pass", "error_class": "unit", "expected_check": "units", "gate_blocking": [], "gate_seq": 121, "gate_verdict": "pass", "review_cause": "infrastructure", "review_id": "rb3faeb037264", "review_seq": 70, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 0, "reviewer_verdict": "review_unavailable"}
{"artefact": "a07", "control_blocking": [], "control_id": "rca0f127cb978", "control_reviewer_verdict": "review_unavailable", "control_verdict": "pass", "error_class": "equilibrium", "expected_check": "equilibrium", "gate_blocking": [], "gate_seq": 131, "gate_verdict": "pass", "review_cause": "infrastructure", "review_id": "rea3178d586a6", "review_seq": 90, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 0, "reviewer_verdict": "review_unavailable"}
{"artefact": "a08", "control_blocking": [], "control_id": "r8441df568221", "control_reviewer_verdict": "fail", "control_verdict": "pass", "error_class": "equilibrium", "expected_check": "equilibrium", "gate_blocking": [], "gate_seq": 122, "gate_verdict": "pass", "review_cause": "infrastructure", "review_id": "rc637d37386cb", "review_seq": 72, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 0, "reviewer_verdict": "review_unavailable"}
{"artefact": "a09", "control_blocking": [], "control_id": "r5b6df40b1430", "control_reviewer_verdict": "fail", "control_verdict": "pass", "error_class": "equilibrium", "expected_check": "equilibrium", "gate_blocking": [], "gate_seq": 112, "gate_verdict": "pass", "review_cause": null, "review_id": "r801bdfa46f6b", "review_seq": 60, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 554159, "reviewer_verdict": "fail"}
{"artefact": "a10", "control_blocking": [], "control_id": "r1a235e474361", "control_reviewer_verdict": "fail", "control_verdict": "pass", "error_class": "equilibrium", "expected_check": "conservation", "gate_blocking": ["conservation"], "gate_seq": 96, "gate_verdict": "fail", "review_cause": null, "review_id": "r091858a68332", "review_seq": 44, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 746222, "reviewer_verdict": "fail"}
{"artefact": "a11", "control_blocking": [], "control_id": "rf195fa2e09fd", "control_reviewer_verdict": "fail", "control_verdict": "pass", "error_class": "equilibrium", "expected_check": "equilibrium", "gate_blocking": [], "gate_seq": 126, "gate_verdict": "pass", "review_cause": "infrastructure", "review_id": "rd0c282534ce1", "review_seq": 80, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 0, "reviewer_verdict": "review_unavailable"}
{"artefact": "a12", "control_blocking": [], "control_id": "r1d5dac237daa", "control_reviewer_verdict": "fail", "control_verdict": "pass", "error_class": "equilibrium", "expected_check": "equilibrium", "gate_blocking": [], "gate_seq": 130, "gate_verdict": "pass", "review_cause": "infrastructure", "review_id": "rdf3a95b73fb0", "review_seq": 88, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 0, "reviewer_verdict": "review_unavailable"}
{"artefact": "a13", "control_blocking": [], "control_id": "r61b7106faa73", "control_reviewer_verdict": "fail", "control_verdict": "pass", "error_class": "equilibrium", "expected_check": "conservation", "gate_blocking": ["conservation"], "gate_seq": 104, "gate_verdict": "fail", "review_cause": null, "review_id": "r4b916275aa3d", "review_seq": 52, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 744388, "reviewer_verdict": "fail"}
{"artefact": "a14", "control_blocking": [], "control_id": "r619f139a407f", "control_reviewer_verdict": "pass", "control_verdict": "pass", "error_class": "equilibrium", "expected_check": "equilibrium", "gate_blocking": [], "gate_seq": 106, "gate_verdict": "pass", "review_cause": null, "review_id": "r4f46819f57ed", "review_seq": 54, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 525264, "reviewer_verdict": "fail"}
{"artefact": "a15", "control_blocking": [], "control_id": "rf49c5499e8e8", "control_reviewer_verdict": "fail", "control_verdict": "pass", "error_class": "propagation", "expected_check": "propagation", "gate_blocking": ["propagation"], "gate_seq": 110, "gate_verdict": "fail", "review_cause": null, "review_id": "r5fa3104eeacf", "review_seq": 58, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 616723, "reviewer_verdict": "fail"}
{"artefact": "a16", "control_blocking": [], "control_id": "rb765e6294d3f", "control_reviewer_verdict": "review_unavailable", "control_verdict": "pass", "error_class": "equilibrium", "expected_check": "equilibrium", "gate_blocking": [], "gate_seq": 117, "gate_verdict": "pass", "review_cause": null, "review_id": "ra23cbcc0a20f", "review_seq": 65, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 741668, "reviewer_verdict": "fail"}
{"artefact": "a17", "control_blocking": [], "control_id": "rb0596d444913", "control_reviewer_verdict": "pass", "control_verdict": "pass", "error_class": "propagation", "expected_check": "propagation", "gate_blocking": ["propagation"], "gate_seq": 102, "gate_verdict": "fail", "review_cause": null, "review_id": "r31ccdfbb46ff", "review_seq": 50, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 289318, "reviewer_verdict": "fail"}
{"artefact": "a18", "control_blocking": [], "control_id": "re0fc0e8af968", "control_reviewer_verdict": "review_unavailable", "control_verdict": "pass", "error_class": "propagation", "expected_check": "propagation", "gate_blocking": ["propagation"], "gate_seq": 95, "gate_verdict": "fail", "review_cause": null, "review_id": "r04c2f3582cad", "review_seq": 43, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 676157, "reviewer_verdict": "fail"}
{"artefact": "a19", "control_blocking": [], "control_id": "rf0aed7215e07", "control_reviewer_verdict": "review_unavailable", "control_verdict": "pass", "error_class": "propagation", "expected_check": "propagation", "gate_blocking": ["propagation"], "gate_seq": 132, "gate_verdict": "fail", "review_cause": "infrastructure", "review_id": "ref9e517b05c7", "review_seq": 92, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 0, "reviewer_verdict": "review_unavailable"}
{"artefact": "a20", "control_blocking": [], "control_id": "rb193a617af76", "control_reviewer_verdict": "review_unavailable", "control_verdict": "pass", "error_class": "unit", "expected_check": "units", "gate_blocking": ["units"], "gate_seq": 109, "gate_verdict": "fail", "review_cause": null, "review_id": "r59812582ef0b", "review_seq": 57, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 597995, "reviewer_verdict": "fail"}
{"artefact": "a21", "control_blocking": [], "control_id": "rd6f012c6a4df", "control_reviewer_verdict": "review_unavailable", "control_verdict": "pass", "error_class": "unit", "expected_check": "units", "gate_blocking": [], "gate_seq": 97, "gate_verdict": "pass", "review_cause": null, "review_id": "r0f01c2cc206a", "review_seq": 45, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 459820, "reviewer_verdict": "fail"}
{"artefact": "a22", "control_blocking": [], "control_id": "r961378db2923", "control_reviewer_verdict": "fail", "control_verdict": "pass", "error_class": "magnitude", "expected_check": "magnitude", "gate_blocking": [], "gate_seq": 119, "gate_verdict": "pass", "review_cause": null, "review_id": "ra84dd6ff3afe", "review_seq": 67, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 427212, "reviewer_verdict": "fail"}
{"artefact": "a23", "control_blocking": [], "control_id": "re19e7e68090e", "control_reviewer_verdict": "review_unavailable", "control_verdict": "pass", "error_class": "unit", "expected_check": "units", "gate_blocking": [], "gate_seq": 111, "gate_verdict": "pass", "review_cause": null, "review_id": "r62c4112b9a98", "review_seq": 59, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 602282, "reviewer_verdict": "fail"}
{"artefact": "a24", "control_blocking": [], "control_id": "r94f3200ccff1", "control_reviewer_verdict": "review_unavailable", "control_verdict": "pass", "error_class": "magnitude", "expected_check": "magnitude", "gate_blocking": ["magnitude"], "gate_seq": 128, "gate_verdict": "fail", "review_cause": "infrastructure", "review_id": "rd348c1d937d5", "review_seq": 84, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 0, "reviewer_verdict": "review_unavailable"}
{"artefact": "a25", "control_blocking": [], "control_id": "rc35edf720771", "control_reviewer_verdict": "review_unavailable", "control_verdict": "pass", "error_class": "unit", "expected_check": "units", "gate_blocking": ["units"], "gate_seq": 103, "gate_verdict": "fail", "review_cause": null, "review_id": "r381008f3abf0", "review_seq": 51, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 706706, "reviewer_verdict": "fail"}
{"artefact": "a26", "control_blocking": [], "control_id": "raa8be75e07e3", "control_reviewer_verdict": "fail", "control_verdict": "pass", "error_class": "propagation", "expected_check": "propagation", "gate_blocking": ["propagation"], "gate_seq": 120, "gate_verdict": "fail", "review_cause": null, "review_id": "rafd7a6b9280d", "review_seq": 68, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 607787, "reviewer_verdict": "fail"}
{"artefact": "a27", "control_blocking": [], "control_id": "r3e1ed213eb02", "control_reviewer_verdict": "fail", "control_verdict": "pass", "error_class": "magnitude", "expected_check": "magnitude", "gate_blocking": [], "gate_seq": 123, "gate_verdict": "pass", "review_cause": "infrastructure", "review_id": "rc6682af1a30b", "review_seq": 74, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 0, "reviewer_verdict": "review_unavailable"}
{"artefact": "a28", "control_blocking": [], "control_id": "rfa2bd6fc2b06", "control_reviewer_verdict": "fail", "control_verdict": "pass", "error_class": "magnitude", "expected_check": "magnitude", "gate_blocking": [], "gate_seq": 105, "gate_verdict": "pass", "review_cause": null, "review_id": "r4bcdc2e8f91e", "review_seq": 53, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 268259, "reviewer_verdict": "fail"}
{"artefact": "a29", "control_blocking": [], "control_id": "rf5431554c717", "control_reviewer_verdict": "fail", "control_verdict": "pass", "error_class": "unit", "expected_check": "units", "gate_blocking": ["units", "propagation"], "gate_seq": 118, "gate_verdict": "fail", "review_cause": null, "review_id": "ra2f5f5f4557e", "review_seq": 66, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 739735, "reviewer_verdict": "fail"}
{"artefact": "a30", "control_blocking": [], "control_id": "r50122d941eb2", "control_reviewer_verdict": "fail", "control_verdict": "pass", "error_class": "propagation", "expected_check": "propagation", "gate_blocking": ["propagation"], "gate_seq": 113, "gate_verdict": "fail", "review_cause": null, "review_id": "r8cdeb773e0fe", "review_seq": 61, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 459659, "reviewer_verdict": "fail"}
{"artefact": "a31", "control_blocking": [], "control_id": "ra8a95f7ce822", "control_reviewer_verdict": "fail", "control_verdict": "pass", "error_class": "magnitude", "expected_check": "magnitude", "gate_blocking": [], "gate_seq": 127, "gate_verdict": "pass", "review_cause": "infrastructure", "review_id": "rd1d30ca8cca6", "review_seq": 82, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 0, "reviewer_verdict": "review_unavailable"}
{"artefact": "a32", "control_blocking": [], "control_id": "r6ef32e90c20c", "control_reviewer_verdict": "blocked", "control_verdict": "pass", "error_class": "magnitude", "expected_check": "magnitude", "gate_blocking": [], "gate_seq": 108, "gate_verdict": "pass", "review_cause": null, "review_id": "r58be9c89ac1a", "review_seq": 56, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 599591, "reviewer_verdict": "fail"}
{"artefact": "a33", "control_blocking": [], "control_id": "r89976749d257", "control_reviewer_verdict": "fail", "control_verdict": "pass", "error_class": "magnitude", "expected_check": "magnitude", "gate_blocking": [], "gate_seq": 101, "gate_verdict": "pass", "review_cause": null, "review_id": "r2eefb6382136", "review_seq": 49, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 321550, "reviewer_verdict": "fail"}
{"artefact": "a34", "control_blocking": [], "control_id": "r273f81d76659", "control_reviewer_verdict": "fail", "control_verdict": "pass", "error_class": "magnitude", "expected_check": "magnitude", "gate_blocking": [], "gate_seq": 107, "gate_verdict": "pass", "review_cause": null, "review_id": "r5576185df180", "review_seq": 55, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 630676, "reviewer_verdict": "fail"}
{"artefact": "a35", "control_blocking": [], "control_id": "re0e8ad1945f7", "control_reviewer_verdict": "review_unavailable", "control_verdict": "pass", "error_class": "propagation", "expected_check": "propagation", "gate_blocking": ["propagation"], "gate_seq": 124, "gate_verdict": "fail", "review_cause": "infrastructure", "review_id": "rc827d4a904f0", "review_seq": 76, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 0, "reviewer_verdict": "review_unavailable"}
{"artefact": "a36", "control_blocking": [], "control_id": "r92d3163cb789", "control_reviewer_verdict": "review_unavailable", "control_verdict": "pass", "error_class": "unit", "expected_check": "units", "gate_blocking": ["units"], "gate_seq": 100, "gate_verdict": "fail", "review_cause": null, "review_id": "r282bf05e8f2d", "review_seq": 48, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 582256, "reviewer_verdict": "fail"}
{"artefact": "a37", "control_blocking": [], "control_id": "rab6382a0e1ba", "control_reviewer_verdict": "fail", "control_verdict": "pass", "error_class": "magnitude", "expected_check": "magnitude", "gate_blocking": [], "gate_seq": 99, "gate_verdict": "pass", "review_cause": null, "review_id": "r1afb014d14d7", "review_seq": 47, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 563763, "reviewer_verdict": "fail"}
{"artefact": "a38", "control_blocking": [], "control_id": "r5c2e3588bf2e", "control_reviewer_verdict": "blocked", "control_verdict": "pass", "error_class": "magnitude", "expected_check": "magnitude", "gate_blocking": [], "gate_seq": 115, "gate_verdict": "pass", "review_cause": null, "review_id": "r9b4b4dc4c4d9", "review_seq": 63, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 470524, "reviewer_verdict": "fail"}
{"artefact": "a39", "control_blocking": [], "control_id": "rae3c71d3a811", "control_reviewer_verdict": "blocked", "control_verdict": "pass", "error_class": "unit", "expected_check": "units", "gate_blocking": [], "gate_seq": 93, "gate_verdict": "pass", "review_cause": null, "review_id": "r00447e2e3a66", "review_seq": 41, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 463173, "reviewer_verdict": "fail"}
{"artefact": "a40", "control_blocking": [], "control_id": "re67bbb2b56d9", "control_reviewer_verdict": "review_unavailable", "control_verdict": "pass", "error_class": "unit", "expected_check": "units", "gate_blocking": [], "gate_seq": 98, "gate_verdict": "pass", "review_cause": null, "review_id": "r1074e696777f", "review_seq": 46, "reviewer_model": "claude-sonnet-5", "reviewer_tokens": 681044, "reviewer_verdict": "fail"}
```

</details>

## Appendix C. `physgate catches --run-dir`

As printed by `read_catches.py` over the run directory and its `controls` directory, with the
script's own check as the last line.

```text
injected {"artefacts_caught": 4, "blocking_failures": 8, "caught_after_reviewer_passed": 0, "check": 1, "checks_run": 80, "gate_mode": "observe", "name": "units", "no_review": 0, "reviewer_had_failed": 8, "reviewer_had_passed": 0}
injected {"artefacts_caught": 1, "blocking_failures": 2, "caught_after_reviewer_passed": 0, "check": 2, "checks_run": 80, "gate_mode": "observe", "name": "magnitude", "no_review": 2, "reviewer_had_failed": 0, "reviewer_had_passed": 0}
injected {"artefacts_caught": 0, "blocking_failures": 0, "caught_after_reviewer_passed": 0, "check": 3, "checks_run": 80, "gate_mode": "observe", "name": "equilibrium", "no_review": 0, "reviewer_had_failed": 0, "reviewer_had_passed": 0}
injected {"artefacts_caught": 0, "blocking_failures": 0, "caught_after_reviewer_passed": 0, "check": 4, "checks_run": 80, "gate_mode": "observe", "name": "power", "no_review": 0, "reviewer_had_failed": 0, "reviewer_had_passed": 0}
injected {"artefacts_caught": 2, "blocking_failures": 4, "caught_after_reviewer_passed": 0, "check": 5, "checks_run": 80, "gate_mode": "observe", "name": "conservation", "no_review": 0, "reviewer_had_failed": 4, "reviewer_had_passed": 0}
injected {"artefacts_caught": 0, "blocking_failures": 0, "caught_after_reviewer_passed": 0, "check": 6, "checks_run": 80, "gate_mode": "observe", "name": "thermal", "no_review": 0, "reviewer_had_failed": 0, "reviewer_had_passed": 0}
injected {"artefacts_caught": 11, "blocking_failures": 12, "caught_after_reviewer_passed": 0, "check": 7, "checks_run": 40, "gate_mode": "observe", "name": "propagation", "no_review": 4, "reviewer_had_failed": 8, "reviewer_had_passed": 0}
injected {"artefacts_caught": 17, "blocking_failures": 26, "caught_after_reviewer_passed": 0, "check": null, "checks_run": 520, "gate_mode": "observe", "name": "all", "no_review": 6, "reviewer_had_failed": 20, "reviewer_had_passed": 0}
controls {"artefacts_caught": 0, "blocking_failures": 0, "caught_after_reviewer_passed": 0, "check": 1, "checks_run": 80, "gate_mode": "observe", "name": "units", "no_review": 0, "reviewer_had_failed": 0, "reviewer_had_passed": 0}
controls {"artefacts_caught": 0, "blocking_failures": 0, "caught_after_reviewer_passed": 0, "check": 2, "checks_run": 80, "gate_mode": "observe", "name": "magnitude", "no_review": 0, "reviewer_had_failed": 0, "reviewer_had_passed": 0}
controls {"artefacts_caught": 0, "blocking_failures": 0, "caught_after_reviewer_passed": 0, "check": 3, "checks_run": 80, "gate_mode": "observe", "name": "equilibrium", "no_review": 0, "reviewer_had_failed": 0, "reviewer_had_passed": 0}
controls {"artefacts_caught": 0, "blocking_failures": 0, "caught_after_reviewer_passed": 0, "check": 4, "checks_run": 80, "gate_mode": "observe", "name": "power", "no_review": 0, "reviewer_had_failed": 0, "reviewer_had_passed": 0}
controls {"artefacts_caught": 0, "blocking_failures": 0, "caught_after_reviewer_passed": 0, "check": 5, "checks_run": 80, "gate_mode": "observe", "name": "conservation", "no_review": 0, "reviewer_had_failed": 0, "reviewer_had_passed": 0}
controls {"artefacts_caught": 0, "blocking_failures": 0, "caught_after_reviewer_passed": 0, "check": 6, "checks_run": 80, "gate_mode": "observe", "name": "thermal", "no_review": 0, "reviewer_had_failed": 0, "reviewer_had_passed": 0}
controls {"artefacts_caught": 0, "blocking_failures": 0, "caught_after_reviewer_passed": 0, "check": 7, "checks_run": 40, "gate_mode": "observe", "name": "propagation", "no_review": 0, "reviewer_had_failed": 0, "reviewer_had_passed": 0}
controls {"artefacts_caught": 0, "blocking_failures": 0, "caught_after_reviewer_passed": 0, "check": null, "checks_run": 520, "gate_mode": "observe", "name": "all", "no_review": 0, "reviewer_had_failed": 0, "reviewer_had_passed": 0}
{"C_from_rows": 0, "caught_from_rows": 17, "holds": true}
```
