# R-LAW-01 — result

**Pre-registration:** `CRITERIA.md`, frozen at commit `f81842c` (22.10.2026, PR #67, merged by
`4839d90`): git blob `00ffe6a3b507a826d8ee85892a02051128eaf381`, sha256
`eefb0efe832b450c862ed6f4505fa9721c1a97d0423b94039685cde6044f5d87`. The freeze is the only commit
that touches the file. The readings fixed before any session are in `README.md` (readings 1–17).

**The three facts filled after the freeze:**

| Commit | What | As it stands on master |
|---|---|---|
| "Inputs filled", `3816c10` (22.10.2026, on the tooling branch) | the digests of every input (§2.4) | PR #70 was squashed into `7c1ca73`. Its `inputs/digests.json` is blob `30ad7679…`, the same blob as at `3816c10`; sha256 `e3792c3ae13a8942586d2f483810016b810eee9ca7ebc1e41d8b6fca9334afb9`. |
| "Slice filled", `a9a4841` (22.10.2026, on the tooling branch) | the six calibration pairs (§6) | Squashed into `7c1ca73` too. Its `slice.json` is blob `a9dddd49…`, the same blob as at `a9a4841`; sha256 `33db7f86c18820004914335c823668fe7d38070f076381a38751483df65d6c40`. Fresh `a14`, `a06`, `a03`, `a35`; practice `a08`, `a20`. |
| "Prompt filled", `672618e` (23.10.2026, PR #75) | each prompt version with its sha256, round 1's disagreement counts and the bank items taken (§6) | Merged with the merge commit `579ac99`, so `672618e` is on master unchanged. |

**The gate (§3):** `src/physgate/gate/` is tree `1e169aac5679d743d4b0585090a45bcd06ea1a63` at the freeze,
at `7c1ca73` and at `672618e`. Bounds blobs `3bbdc33b…` (electrical) and `b68fd58f…` (cross); the
unit-spelling module blob `eaa4ce69…`; catalogue digest `9bf73a7d…51a841c88`, carried by all 120
re-gate records.

**The run:** 23.10.2026, on the macOS laptop, in a clean run worktree, on the development account.
- **Calibration** ran from `7c1ca73` (preflight held at 11:49:34Z and 11:50:04Z; ledger lines from
  11:50:39Z to 12:08:30Z; the phase ended 12:08:31Z, exit 0).
- **The measured phase** ran from `672618e` (preflight held at 12:11:30Z; ledger lines from
  12:12:28Z to 14:11:13Z; the phase ended 14:11:18Z, exit 0).
- **Binary:** Claude Code `2.1.301`, macOS build, sha256 `1f04c69e…00276b99` (`law_sessions.sh`,
  `PIN_MAC`). It ran with only the seven allowlisted environment names (README reading 15; launch
  log).
- **Models:** `claude-opus-5-5` for the coders, the adjudicator and reality (530 ledger lines);
  `claude-fable-5-1` for the cross-model audit (25). Every ledger line used the model it asked for.

**The tally:** `law_tally.py` at `672618e`, run by hand after the measured phase ended, exit 0, no
error output. Its full output is `data/tally.json`, sha256
`79190e7b8abfb6e698db8d8ad1beb2864d0b271e0694773fba9fd5580f71d350`. **Every figure below is copied
from it**, unless the line names another file the tally read. Percentages are its shares to one
decimal. The exceptions are the section "Figures added after the run" and the lines that point to
it. Their figures come from `data/report_extra.json`, which `law_report.py` computed after the run;
that script was itself added after the run.

---

## In plain English

**The question.** Reviewers found flaws in the designs. Of the real ones, how many could a fixed
physics formula over the numbers the design already holds catch, beyond what the physics gate's
seven checks already catch? That share is the ceiling for a law library added to the gate.

**The answer: 50 of 250 real flaws, 20.0 %.** Its 95 % intervals are 15.5 % to 25.4 % (Wilson)
and 13.9 % to 27.3 % (cluster bootstrap, which allows for flaws of one design hanging together).
The threshold fixed before the run is 15 %. The share is above it, so by the frozen rule the law
library is **a priority**: the gate's next extension, scoped from the law frequency table, with
the existing relations the gate did not form fixed first.

**Two labels go with the decision. It stands either way, labelled, as §10 says.**
- **Not resolved at this size.** The wider of the two intervals is the cluster bootstrap's. It
  reaches down to 13.9 %, below 15 %. At this sample size, the share is not shown to lie above
  the threshold.
- **Not robust.** One of the six pre-registered sensitivity readings falls below 15 %. S3 gives
  each flaw the most frequent code among its lines, rather than the first of G, L, L-if-data, D, N
  that any of its lines has, and it gives 14.0 %. The other five give 17.2 % to 19.9 %.

**The rest held.** The two coders agreed above the floor set before the run (weighted κ 0.777 over
the five codes and 0.781 for "law or gate" against the rest; floor 0.60). The reality check met
both of its control bars. No deviation occurred, so the decision is taken. The run had no
interruption and used 20,731,440 tokens against a guard of 60,000,000.

**What it means.** On these designs, one real flaw in five is a defect that a textbook law over
values the nodes already hold would expose, and that the gate as built does not catch. By the rule
fixed before the run, that makes the law library the gate's next extension.

**What it does not mean.** It is a ceiling: what a perfect library could catch, not what a built
one catches. It counts only flaws that reviewers found, on one stand-in design per set, built from
one parts sheet. It is not a measure of the gate's catch rate or of the reviewers' accuracy. The
planted errors were chosen to be checkable; on the flaws away from them the share is 17.8 %, also
above 15 %, so the decision does not depend on that mix.

---

## Verdict

| | Rule | Measured | Outcome |
|---|---|---|---|
| κ floor (§7) | weighted κ₅ ≥ 0.60 and weighted κ_L ≥ 0.60 | κ₅ **0.777**, κ_L **0.781** | **met** |
| Reality (§2.3) | calibration bar ≥ 70 % and rejection bar ≥ 70 % | 52 of 53 versions calibrated; 32 of 34 controls `not_a_flaw` | **reliable**: the primary uses the reality verdicts |
| Deviations (§12) | none recorded | none | **the decision is taken** |
| Mix-dependent (§10) | the share on the injection and the share elsewhere on different sides of T | 24.1 % and 17.8 %, both at or above 15 % | **no**: the deciding share is the primary |
| Deciding share (§8.1, §10) | L / real flaws, against T = 15 % | **20.0 %** (50 of 250) | **at or above T: a priority** |
| Resolved (§10) | the wider of the Wilson and cluster intervals lies wholly on one side of T | the wider is the cluster interval, [13.9 %, 27.3 %] | **not resolved at this size** |
| Robust (§10) | all six readings of §8.3 on the deciding share's side of T | S3 gives 14.0 % | **not robust**: S3 crosses |

### The decision, as §10 words it

> **A priority.** The library is the gate's next extension, scoped from the law frequency table,
> with the existing relations the gate did not form fixed first.

It is **not resolved at this size** (the cluster-bootstrap interval holds 15 %) and **not robust**
(reading S3 crosses). §10: "It stands either way, labelled."

**Printed beside it (§10)**, on every real flaw, since the decision is not mix-dependent:

| Beside the decision | Value |
|---|---|
| Strict-law share (S5: `limit` relations not counted as L) | **18.8 %** (47 of 250) |
| L flaws whose relation has one input on each side and a non-integer literal | **0** |
| L + L-if-data | **24.8 %** (62 of 250) |
| The data-side scope note (L below T, L + L-if-data at or above it) | not triggered: L is not below T |
| Below the κ floor | no |

---

## The population (§2, §6)

- **Extraction** reproduced §2.2 exactly (`data/extract_counts.json`): 993 finding lines from 262
  reviews, every one with verdict `fail`, with the per-source counts of §2.2's table. By section:
  domain standards 494, acceptance criteria 258, reward hacking 164, antipatterns 77. 219 lines
  have an empty locus.
- **Grouping** reproduced §2.2 exactly (`data/group_counts.json`): 214 section 1 lines absorbed at
  step A; 427 flaws after step B, 367 after step C, 348 after step D (practice 187, fresh 161). 36
  base flaws merge into 17; 8 span more than one pair; the largest spans 3. So the count deviation
  of §12 did not occur.
- **The slice** (`slice.json`): 129 calibration lines on six pairs. 52 flaws touch the slice. One
  flaw spans slice and measured pairs, and it is a base flaw (the count §6 asks for: **1**).
- **Measured:** 864 lines, 297 flaws. **Real: 250**; not real: 34; undecided: 13.
- **Clusters** for the bootstrap: 67 (the design pairs, each base flaw a cluster of its own).
- §10 expected about 310 real flaws in the measured set; there are 250.

## Primary result (§8.1)

| Share | Value | Flaws | Wilson 95 % (%) | Cluster bootstrap 95 % (%) | Clusters |
|---|--:|--:|---|---|--:|
| **L / all real flaws** | **20.0 %** | 50 of 250 | [15.5, 25.4] | [13.9, 27.3] | 67 |

The cluster bootstrap resamples the 67 clusters with `random.Random(13)`, 10,000 draws. The
denominator is every real flaw: G, L, L-if-data, D, N and uncoded.

## Agreement (§7)

The two coders on the 864 measured lines, on their codes after §5.5 and before §5.6. Each line is
weighted by 1 / (the measured lines of its flaw), so each flaw weighs one. A missing form is the
category `none` and agrees with nothing (README reading 8).

| | Weighted | 95 % cluster interval | Unweighted | Raw agreement, weighted / unweighted | PABAK, weighted / unweighted | Units |
|---|--:|---|--:|---|---|--:|
| **κ₅** (five codes) | **0.777** | [0.698, 0.843] | 0.776 | 0.851 / 0.845 | 0.821 / 0.814 | 864 lines |
| **κ_L** ({G, L} against the rest) | **0.781** | [0.656, 0.887] | 0.814 | 0.934 / 0.931 | 0.900 / 0.896 | 864 lines |
| κ at the flaw level (reported, never a floor) | 0.772 | [0.669, 0.865] | 0.772 | 0.840 / 0.840 | 0.808 / 0.808 | 250 flaws |

**Per coder, measured step** (reported, never a floor):

| | Forms | Without a form | §5.5 failures (the fallback code is used) | Inconsistent L-if-data forms | Share of G-caught lines it claimed G |
|---|--:|--:|---|--:|--:|
| Coder 1 | 864 | 0 | unparsed 78, pairing 22, no input 11, dimension 7 | 0 | 63.2 % |
| Coder 2 | 864 | 10 | unparsed 59, no input 14, pairing 12, dimension 10, on no node 2; no form 10 | 0 | 63.2 % |
| Adjudicator | 124 | 0 | unparsed 35, pairing 8 | 0 | 0.0 % |
| Cross-model audit | 170 | 0 | unparsed 13, dimension 6, pairing 3 | 0 | 28.6 % |

The last column is taken over the G-caught lines each coder was given, on its own codes after
§5.5 (README reading 11).

**The adjudicator's choices:** on the 124 disputed lines it chose coder 1's form 49 times and
coder 2's 75 times. It never chose a third code.

**The cross-model audit** (`claude-fable-5-1`, reported only: it never changes a code, a share or
the decision). 25 of coder 1's 123 packets, 170 lines. Against the final line codes (§5.7 rule 1,
before §5.6):

| | Weighted | 95 % cluster interval | Unweighted | Raw agreement, weighted / unweighted | PABAK, weighted / unweighted | Lines |
|---|--:|---|--:|---|---|--:|
| κ₅ | 0.626 | [0.472, 0.784] | 0.577 | 0.737 / 0.688 | 0.684 / 0.626 | 170 |
| κ_L | 0.683 | [0.455, 0.910] | 0.633 | 0.920 / 0.865 | 0.880 / 0.797 | 170 |

On the audited subset's 146 real lines, the L share is **27.4 %** by the audit's codes and
**19.2 %** by the final codes. The only model the ledger records for the audit is
`claude-fable-5-1`.

## Reality (§2.3, §8.2 item 6)

- **Calibration control:** 52 of the 53 injected versions holding a line whose locus holds a
  changed pair are calibrated. Bar 70 %: **met**.
- **Rejection control:** 32 of 34 control lines came back `not_a_flaw`. Bar 70 %: **met**. The two
  that came back `true_flaw` are `L0303` and `L0606` (`data/reality_summary.json`). Control
  verdicts are never reality verdicts.
- **Reliable:** yes. So the primary does not presume every line real.

**Line verdicts, by side** (864 measured lines):

| Side | `true_flaw` | `not_a_flaw` | `undecidable` |
|---|--:|--:|--:|
| injected | 552 | 65 | 20 |
| twin | 179 | 41 | 7 |

**Flaws:** 250 real, 34 not real, 13 undecided. tally.json does not split the flaw verdicts by side.
That split, computed after the run, is in "Figures added after the run". Each flaw's verdict is in
`data/reality_summary.json`.

**Agreement with the prior adjudication** on its 51 lines (all 51 matched and adjudicated here):
43 agree, Cohen's κ **0.407**.

| Prior verdict → verdict here | Lines |
|---|--:|
| `true_flaw` → `true_flaw` | 40 |
| `true_flaw` → `not_a_flaw` | 7 |
| `not_a_flaw` → `not_a_flaw` | 3 |
| `undecidable` → `not_a_flaw` | 1 |

## Secondary results (§8.2, reported, never scored)

### 1. The codes of the real flaws

| Code | Share | Flaws |
|---|--:|--:|
| G | 8.8 % | 22 |
| **L** | **20.0 %** | **50** |
| L-if-data | 4.8 % | 12 |
| D | 45.2 % | 113 |
| N | 20.8 % | 52 |
| uncoded | 0.4 % | 1 |

tally.json gives the parts and kinds below as counts of flaws, not as shares. The shares, computed
after the run, are in "Figures added after the run".
- **G's two parts** (§5.7 rule 3): caught where the coders also claimed G, **13**; caught where they
  coded L or L-if-data, **9**.
- **D by kind:** record 54, source 31, table 3, and `fallback` 25 (the deciding form of the flaw's
  representative line claimed another code and fell back to D under §5.5). No simulation or
  numeric.
- **N by kind:** traceability 45, judgement 3, process 2, `fallback` 2. No wording.
- **A coder's G the gate did not fail, turned into L (gap):** 0 L flaws.

### 2. L + L-if-data

**24.8 %** (62 of 250), Wilson [19.9, 30.5] %, cluster [18.0, 32.6] %, 67 clusters.

### 3. How the 50 L flaws split

Each L flaw is counted once, by its representative line: the lowest-numbered of its `true_flaw`
lines whose final code is L.

| Split | Counts |
|---|---|
| `relation_origin` | new relation 42; existing relation the gate did not form 8 |
| `unformed_by` (for an existing relation) | name 8; edge 0; formed 0. The 42 new relations have none (`None`). |
| `joined` | two nodes joined by one edge 22; neither 17; one node 11 |
| kind | `law` 46; `limit` 4 |
| law | 44 law names, as the deciding forms word them: Appendix A |

The kind row and the strict-law share (S5, 18.8 %, 47 of 250) count differently. The kind row
counts one representative line per flaw. S5 replaces every `limit` line by its fallback code and
then aggregates each flaw's lines again (README reading 6).

### 4. The L share by role, class, set, reviewer kind and origin

Each row has its own cluster bootstrap. A base flaw counts under role and class "base". A flaw
counts under each reviewer kind that found it. tally.json gives the L share per group only. Every
code's share per group, computed after the run, is in "Figures added after the run".

| By role | L share | Flaws | Wilson 95 % (%) | Cluster 95 % (%) | Clusters |
|---|--:|--:|---|---|--:|
| base | 46.7 % | 7 of 15 | [24.8, 69.9] | [20.0, 73.3] | 15 |
| control | 11.4 % | 9 of 79 | [6.1, 20.3] | [3.1, 25.9] | 18 |
| electrical | 23.8 % | 19 of 80 | [15.8, 34.1] | [13.3, 37.1] | 14 |
| firmware | 18.5 % | 5 of 27 | [8.2, 36.7] | [5.0, 30.0] | 8 |
| mechanical | 20.4 % | 10 of 49 | [11.5, 33.6] | [6.1, 37.3] | 12 |

| By error class | L share | Flaws | Wilson 95 % (%) | Cluster 95 % (%) | Clusters |
|---|--:|--:|---|---|--:|
| base | 46.7 % | 7 of 15 | [24.8, 69.9] | [20.0, 73.3] | 15 |
| equilibrium | 23.1 % | 15 of 65 | [14.5, 34.6] | [10.0, 40.0] | 14 |
| magnitude | 8.9 % | 4 of 45 | [3.5, 20.7] | [0.0, 20.0] | 12 |
| propagation | 18.3 % | 11 of 60 | [10.6, 29.9] | [8.2, 27.9] | 12 |
| unit | 20.0 % | 13 of 65 | [12.1, 31.3] | [7.5, 42.1] | 14 |

| By set | L share | Flaws | Wilson 95 % (%) | Cluster 95 % (%) | Clusters |
|---|--:|--:|---|---|--:|
| fresh | 26.5 % | 35 of 132 | [19.7, 34.6] | [16.8, 37.4] | 41 |
| practice | 12.7 % | 15 of 118 | [7.9, 19.9] | [6.8, 21.1] | 26 |

| By reviewer kind | L share | Flaws | Wilson 95 % (%) | Cluster 95 % (%) | Clusters |
|---|--:|--:|---|---|--:|
| paired | 19.8 % | 48 of 242 | [15.3, 25.3] | [13.7, 27.3] | 66 |
| generalist | 35.1 % | 13 of 37 | [21.8, 51.2] | [19.4, 51.4] | 33 |

| By origin | L share | Flaws | Wilson 95 % (%) | Cluster 95 % (%) | Clusters |
|---|--:|--:|---|---|--:|
| on the injection | 24.1 % | 21 of 87 | [16.4, 34.1] | [12.9, 36.0] | 47 |
| elsewhere | 17.8 % | 29 of 163 | [12.7, 24.4] | [10.9, 26.0] | 53 |

The earlier definition of "on the injection" (any injected-side line whose locus holds a changed
pair), for description only: **459** lines.

### 5. The false-positive audit

Each L relation of the measured set, with its node and quantity addresses and its tolerance, was
evaluated on every clean twin of its set whose data holds all its inputs. **56 relations; 515
blocks in all; 60 distinct clean twins blocked** (the two sets hold 60 clean twins between them,
§2.1). Clean twins can carry real flaws, so a block is not proven false; reported only. Every
relation and its count: Appendix C.

### 6. Reality

Given above.

### 7. Counts

- **`multiple_defects` lines:** 249. The codes of their `further` defects (reported only, never in
  a share): N 163, D 74, L 40, G 34, L-if-data 8.
- **Base flaws:** 17 in the measured set; 1 spans slice and measured pairs.
- **The excluded records of §2.2, per run:** Appendix D.

### 8. The literals of every L relation

Listed per relation in Appendix B: 60 relations, each with the measured lines whose final code is L
and that state it (README reading 9). The only literals the tally lists are 2.0 and 6.0.

## Sensitivity readings (§8.3)

Each computed on the deciding share (all real flaws). "Side" is the reading's side of T = 15 %.

| # | Reading | Share | Flaws | Wilson 95 % (%) | Cluster 95 % (%) | Clusters | Side |
|---|---|--:|--:|---|---|--:|---|
| — | **Primary** | **20.0 %** | 50 of 250 | [15.5, 25.4] | [13.9, 27.3] | 67 | at or above |
| S1 | Base flaws once per pair | 19.9 % | 53 of 266 | [15.6, 25.1] | [14.0, 26.9] | 83 | at or above |
| S2 | Every line its own unit | 19.2 % | 140 of 731 | [16.5, 22.2] | [13.0, 25.5] | 52 | at or above |
| **S3** | **Majority aggregation** | **14.0 %** | 35 of 250 | [10.2, 18.8] | [9.3, 19.4] | 67 | **below: crosses** |
| S4 | Every line real | 17.2 % | 51 of 297 | [13.3, 21.9] | [11.5, 23.9] | 70 | at or above |
| S5 | Strict law | 18.8 % | 47 of 250 | [14.4, 24.1] | [12.9, 25.9] | 67 | at or above |
| S6 | Wider base merge | 19.6 % | 47 of 240 | [15.1, 25.1] | [13.2, 27.1] | 57 | at or above |

So the decision is **not robust**, and the reading that crosses is **S3**.

---

## Threats to validity (§9), and what the run showed

1. **The corpus's injected-error mix.** The share on the injection is 24.1 % (21 of 87); the share
   elsewhere is 17.8 % (29 of 163), Wilson [12.7, 24.4] %, cluster [10.9, 26.0] %. Both are at or
   above T, so the decision is not mix-dependent and the deciding share is the primary. The share
   elsewhere's own cluster interval also holds 15 %.
2. **Coder model bias.** Every G and L form was recomputed by script from the node data (§5.5); the
   failures per coder are in the agreement section. The coders against the gate: coder 1 and coder
   2 each claimed G on 63.2 % of the G-caught lines they were given. The false-positive audit: 515 blocks over 60
   clean twins. The cross-model audit: weighted κ₅ 0.626 [0.472, 0.784] and κ_L 0.683
   [0.455, 0.910] against the final codes. On its 146 real lines it codes L 27.4 % of the time,
   against 19.2 % by the final codes.
3. **The checks as implemented against as described.** Of the 50 L flaws, 8 are an existing gate
   relation the gate did not form, all 8 unformed by name; 42 are new relations. tally.json does
   not split L by the family field. Computed after the run: family 4 (power balance) 18, family 5
   (energy and mass conservation) 12, family 3 (static equilibrium) 11, family 7 (propagation) 4,
   and none 5.
4. **Only what reviewers found.** The run cannot measure flaws no reviewer found. By reviewer kind
   the L share is 19.8 % for the paired reviewers (48 of 242) and 35.1 % for the generalist (13 of
   37).
5. **The unit rule.** S1 19.9 %, S2 19.2 % and S6 19.6 %: all three at or above T.
6. **The reality verdicts.** The rejection control came back `not_a_flaw` on 32 of 34 lines and the
   calibration control held on 52 of 53 versions. S4 (every line real) gives 17.2 % (51 of 297).
7. **Non-independence.** The primary's cluster interval, [13.9, 27.3] %, is wider than its Wilson
   interval, [15.5, 25.4] %. It is the one that decides "not resolved". κ is weighted per flaw.
8. **Exposure before the freeze.** As disclosed in §9 item 8. During the run the operators saw
   counts only: the launch log holds counts of sessions, tries, tokens, failures and blind-check
   hits, and no code, verdict or share. Every packet set passed the blind check before its
   sessions: `blind: true`, with no hit in the template, none in the sheet and no rubric item id in
   the findings. The words counted inside the findings and the coders' forms are the reviewers'
   and coders' own (README reading 10).
9. **Practice runs carry tuning.** By set, the L share is 26.5 % on the fresh set (35 of 132,
   Wilson [19.7, 34.6] %, cluster [16.8, 37.4] %) and 12.7 % on the practice set (15 of 118, Wilson
   [7.9, 19.9] %, cluster [6.8, 21.1] %).
10. **Findings made against an incomplete parts sheet.** Reality, which saw the full sheet, ruled 65
    injected-side and 41 twin-side lines `not_a_flaw`. 34 flaws are not real and 13 undecided, and
    neither enters the denominator. Against the prior adjudication, which saw the lossy copy, 43 of
    51 verdicts agree (κ 0.407); the 8 that differ all go to `not_a_flaw` here. The defect itself:
    disclosure 5, below.

---

## The run (§12)

**Run order,** as §12 lists it: the freeze; the scripts, tested on a synthetic fixture; "Inputs
filled"; extraction and grouping (993 lines, 348 flaws); "Slice filled"; the re-gate (no model),
which equals the `a-fresh` gate lines on all 80 fresh versions (`data/regate_check.json`: 80
compared, 0 differ, 0 missing); calibration; "Prompt filled"; the measured sessions; the tally.

**Sessions, tries and tokens per step** (`data/launch.log` for the counts and tokens; the ledger
lines' times, UTC, 23.10.2026). A try is invalid if its output lacks a valid form for a finding of
its packet; it then gets §5.5's one retry.

| Step | Model | Packets | Tries | Invalid tries | Failed calls | Tokens | Ledger lines |
|---|---|--:|--:|--:|--:|--:|---|
| Round 1 (v0), coder 1 | opus | 17 | 18 | 1 | 0 | 668,619 | 11:50:39–11:56:44 |
| Round 1, coder 2 | opus | 17 | 17 | 0 | 0 | 629,675 | 11:50:48–11:56:12 |
| Round 1, adjudicator | opus | 6 | 6 | 0 | 0 | 227,116 | 11:57:00–11:58:13 |
| Round 2 (v1), coder 1 | opus | 17 | 18 | 2 | 0 | 673,662 | 11:59:04–12:05:09 |
| Round 2, coder 2 | opus | 17 | 19 | 2 | 0 | 721,471 | 11:58:57–12:06:49 |
| Round 2, adjudicator | opus | 6 | 6 | 0 | 0 | 233,776 | 12:07:16–12:08:30 |
| Reality, injected versions | opus | 77 | 77 | 0 | 0 | 2,516,045 | 12:12:28–12:32:31 |
| Rejection controls | opus | 34 | 34 | 0 | 0 | 977,515 | 12:32:43–12:39:02 |
| Reality, twin versions | opus | 39 | 39 | 0 | 0 | 1,281,237 | 12:33:26–12:52:41 |
| Measured, coder 1 | opus | 123 | 125 | 2 | 0 | 4,889,207 | 12:12:45–13:39:59 |
| Measured, coder 2 | opus | 123 | 131 | 11 | 0 | 5,257,570 | 12:13:20–13:46:03 |
| Measured, adjudicator | opus | 40 | 40 | 0 | 0 | 1,629,245 | 13:46:33–13:55:52 |
| Cross-model audit | fable | 25 | 25 | 0 | 0 | 1,026,302 | 14:00:32–14:11:13 |

- The ledger has 555 lines, one per try. Every one exits 0 and records no infrastructure failure.
- Calibration used 3,154,319 tokens. **The whole run spent 20,731,440 tokens** (tally.json
  `tokens.spent`, the ledger's sum), against **the 60,000,000 guard**.
- **The projection check after round 1** (§12 step 6): 1,525,410 tokens spent over 40 sessions,
  38,135 per session, 550 sessions remaining, **22,499,798 projected**, at most 60,000,000: it
  held (`ledger/projection.json`, exit 0).
- **No token estimate was used:** 0 ledger rows carry `tokens_estimated` (README reading 12).
- Reality gave every one of the 864 measured lines a verdict, with no retry. 854 measured lines
  have a deciding form; the other 10 are the lines coder 2 left without a form.
- Every packet carried the full parts sheet at its digest: the driver refused no session for it.

---

## Disclosures

**1. Interruptions.** None: **0 stops, 0 failed calls, 0 resumes, 0 repairs** (tally.json
`interruptions`). No event was ever logged, so `ledger/interruptions.jsonl` was never written. No
token estimate was used.

**2. Tokens.** Spent **20,731,440**; guard **60,000,000**; projection after round 1
**22,499,798**. §12's table expected about 30 to 32 M.

**3. Calibration (§6).** Two rounds.
- **Round 1** ran version 0 (Appendices A and B) on the 129 slice lines: 17 packets per coder and
  6 adjudicator packets, 40 sessions, 1,525,410 tokens.
- **Its disagreements** per unordered pair of codes after §5.5 (`bank.json`): D–N 15, L–N 3,
  D–G 2, D–L 2, G–L 1, G–N 1.
- **Taken** (2 or more on the item's pair): W1, W2, W8, X1, X5, X7, X8 (L–N, 3); W5, W6, X4 (L–D,
  2); W7, X6 (D–N, 15). **Not taken:** W3 and X3 (G–L, 1); W4 and X2 (L–L-if-data, 0). The D–G and
  G–N pairs have no bank item.
- Appendix D disclosed that five of the seven L–N items lean toward L (W1, W8, X1, X7, X8) and two
  away from it (W2, X5). All seven were taken.
- **Round 2 ran version 1**, version 0 with the twelve items applied as README reading 3 says. The
  final prompt is v1. Sha256: coder prompt v0 `2a01ad79…`, v1 `e6380ca9…`; adjudicator prompt v0
  `0d9b0d2b…`, v1 `3d2aae2f…`; coder schema `a79889a6…` and adjudicator schema `f689ef64…` in both
  versions; reality prompt `41438ab7…` and schema `57c3852f…`, the frozen digests (`prompts/`,
  each version's `prompts.json`).
- §6 also asks for the slice's κ and L share under each version. No frozen script computes them.
  They were computed after the run and are in "Figures added after the run".
- **The bank's lean toward L, answered.** Under v1 the slice's L share was 13.5 % (7 of 52 flaws),
  against 11.5 % (6 of 52) under v0. Per line it was 20.2 % (26 of 129) against 17.1 % (22 of 129).
  So v1 coded one more slice flaw and four more slice lines L. The two rounds are separate
  sessions, so the difference mixes the prompt change with session-to-session variation, and the
  slice has only 7 clusters.

**4. The account.**
- Every session ran on the **development account**. The owner confirmed on 22.10.2026 that the
  laptop is on it.
- §12 says the sessions never run in the same weekly window as an evaluation run on that account.
  The orchestrator's record of 22.10.2026: no evaluation run used the account that week. GR2 and
  the transfer ran on the Oracle server's run account. The prior (H2) adjudication and an IMU
  adjudication ran on the development account, and neither is an evaluation run.
- **One R-PG-01b trial session** used the same account on 23.10.2026 from **07:33:16Z to
  07:38:08Z**: 1 session, 17 turns, **336,445 tokens**. It read one file and scored nothing. It was
  a check, not an evaluation run, and it ended before R-LAW-01's first session (11:50:39Z).
  R-PG-01b's own run then moved to the run account (23.10.2026), so this trial was its only use of
  the development account.
- So **§12's rule holds.**

**5. §2.5's parts-sheet defect.** §2.5 says a code-level verification was running at the freeze.
Its outcome (`.docs/specs/spec_GR2/parts_sheet_defect.md`, a read-only check of 22.10.2026): **the
defect is as §2.5 states it.**
- **No code drops a value.** The corpus format lets a sheet row hold one number or nothing, and no
  other field. So `sources.json` itself holds none of the 62 values and no note.
- **The instrument hands reviewers that file byte for byte.** The authors' `parts_sheet.md`, with
  every value and 130 notes, is in the corpus but is never put in a packet.
- **Counts on the fresh set,** from a real review packet built with the instrument's own code: 62 of
  163 rows have no value (44 with two or more numbers, 11 with one qualified number, 7 text only),
  and none of the 130 notes arrives. The practice set carries the identical files.
- **Where:** the same mechanism at `8bc03fc`, `0936f1f`, `eae78c0`, `8c51f48` and `1a7bb0d`, the
  commits the check read. It entered with PR #26 (`f2048da`, 17.10.2026).
- **The gate never reads the sheet.**
- **The prior (H2) adjudication's packets** showed the same 62 rows as "(no value)", with no notes.
- **The fix** is PR #69, merged as `31b90aa` at 23:53Z on 22.10.2026 (maintenance item M-143,
  closed 23.10.2026). A sheet row may now carry `given` (its value as the authors wrote it) and `note`,
  and a converter writes `sources.json` from `parts_sheet.md`. No committed corpus changed, and the
  gate tree is unchanged.
- **R-LAW-01 does not depend on the fix.** Every one of its packets carries `parts_sheet.md`
  verbatim at its digest (§2.5).

**6. README reading 16: the parts sheet's own words, a disclosed threat.** The sheet carries text
of its own. Its line 1 reads "Stand-in design, not the reference solution. Kit: …", its line 5 is
the author's "Kit choice: I chose …", and the note of row R6.05 contains "answered". It was kept
because §2.5 freezes the sheet verbatim at its digest. It is identical in every packet of every
step, arm and control, and the blind check found none of its forbidden words in it (0 sheet hits on
every packet set). Its one plausible effect is on the reality judge's prior that a finding is real.
The figures the tally gives beside it:
- the calibration control: 52 of 53 versions calibrated;
- the rejection control: 32 of 34 controls `not_a_flaw`;
- agreement with the prior adjudication, whose packets did not carry these lines: 43 of 51, κ
  0.407. The 8 that differ went from the prior's `true_flaw` (7) or `undecidable` (1) to
  `not_a_flaw` here.

**7. Pre-launch checks, not part of the experiment.** None was an experiment session. All ran on
the pinned binary, on the development account, on synthetic packets that hold no finding line, and
none wrote a ledger line. **The binary reported 12,107 tokens in all**, for five calls: smokes of
1,572, 1,579 and 1,500, the unsatisfiable-schema probe at 6,281 and the clean-environment probe at
1,175. Two more calls, the retry-exhaustion probes, ran tokens the binary does not report.
- **The smoke session** (22.10.2026, at `d642c06`; 1,572 tokens). Why: to confirm that the run's
  flags work before the first session. It held: `--json-schema` works with `--tools ""` (the only
  tool the session reports is `StructuredOutput`); `--setting-sources ""` keeps every CLAUDE.md out;
  the result's usage equals the sum over `modelUsage`, which names only `claude-opus-5-5`; and
  `terminal_reason` is present. It was re-run after the fixes that changed how the binary is
  called: at `ad87e7d` (23.10.2026, 1,579 tokens) and at `958b46c` under the clean environment
  (23.10.2026, 1,500 tokens). It held each time. Output: `testdata/smoke_out.json`.
- **Probe 1, an unsatisfiable schema** (22.10.2026). Why: to see how the binary reports a model
  that cannot fit the schema. The binary returned a success with no structured output, which is a
  try. 6,281 tokens. Output: `testdata/schema_fail_probe_out.json`.
- **Probe 2, the structured-output retry exhaustion** (23.10.2026), run twice, once with
  `--verbose`. Why: the binary's own strings, and the ultrareview, showed a second path. Run with
  one allowed retry, it gave exit 1, `error_max_structured_output_retries` and
  `structured_output_retry_exhausted`. Both runs reported 0 tokens although two turns ran, as the
  binary's exhaustion path does. It confirmed the path that README reading 5 counts as a try with
  no form, and its missing usage led to reading 12 (a call that reports no usage is charged an
  estimate). Output: `testdata/retry_exhausted_probe_out.json`.
- **Probe 3, the clean environment** (23.10.2026). Why: to confirm the pinned binary
  authenticates under the `env -i` allowlist before making that the rule (README reading 15). It
  did: exit 0, success. 1,175 tokens.

**8. The tooling's review history.** Before any session, the scripts went through six review rounds,
each finding fixed test-first: a first review, an ultrareview, three independent delta reviews and a
final check. The experiment's gate stood at 222 passing tests when PR #70 merged as `7c1ca73`. What
changed, by README reading: a failed call (a usage or rate limit, a refused credential, a server or
network failure) stops the run and re-runs the same try on resume, rather than using up §5.5's one
retry; the binary's structured-output exhaustion is a try with no form; and the 60 M guard fails
closed and is read again after the last session settles (reading 5). The tally sums the ledger
itself, and each coder's G-claim share is read from its own rows (reading 11). A call that reports
no usage is charged an estimate toward the guard (reading 12). The projection check is computed
once, and only a projection over the guard on a ledger read in full is the deviation (reading 13).
A torn ledger line has a fixed repair (reading 14). The binary sees only an allowlisted
environment, one launcher holds a kernel lock per work dir, and the stand-in dry run is confined to
the synthetic fixture (reading 15). The parts sheet's own words are disclosed (reading 16). A packet
that fails on every resume is the owner's to declare (reading 17). Readings 7 to 10 came from the
first review. **None of these readings changes a frozen number, seed or threshold**, as each of them
says.

**9. Reading 17's history.** An automatic stuck-packet trigger was built and then removed before any
session. In fix round 5 (`40219dc` on the tooling branch) the driver would itself declare §12's
deviation on a packet's third identical failed call in a row, with other packets' tries between. The
final check before any session found that it could fire on an outage (an overload or a flaky
network hitting the packet first in flight after each resume) and could never fire for a driver
running alone. The owner ruled on 23.10.2026 that it be removed (`0fea01b` and `4150b42` on the
tooling branch, both in `7c1ca73`). Now a packet that fails on every resume stops the run each time,
and declaring the deviation is the owner's call. **In the run no call failed, so no packet stalled
and nothing was declared.**

**10. "Prompt filled" was merged while the measured phase ran.** The measured phase launched from
`672618e` at 12:11:28Z. PR #75 merged at 12:35:38Z with the merge commit `579ac99`, which keeps
`672618e` on master unchanged. `672618e` differs from `7c1ca73` only in `prompts/` and `bank.json`.

**11. The false-positive audit blocks every clean twin.** The 56 relations block 60 distinct clean
twins, and the two sets hold 60 clean twins between them (§2.1). Seven fresh-set relations each
block all 40 fresh twins: `I_d == I_st * V_s / V_r`, `I_d == V_p * I_s / V_r`,
`I_draw == V_pack * I_stall / V_rated`, `I_draw >= V_pack * I_stall / V_rated`,
`I_out == I_s * V_p / V_r`, `I_pk == 2 * V_p * I_s / V_r` and `R_ch == 2 * r * tau_s`. Three
practice-set relations each block all 20 practice twins: `T_out <= r * T_in`,
`tau_bl <= 2 * r_ext * tau_m` and `w_g == w_m / r_ext`. Nine more block 19 of the 20 (Appendix C).
Clean twins can carry real flaws, so a block is not proven false. §8.2 item 5 reports it only.

**12. The kind split and S5.** Four L flaws have a `limit` representative line: W0080, W0146,
W0260 and W0261. S5 drops three of them. W0260 stays L, because its line L0794 is coded L by a
`law` relation (`I_nl <= I_stall`). W0264 has a `limit` line (L0795) but a `law` representative,
and stays L too. So S5 gives 47 L flaws, not 46. This follows README reading 6.

**13. The two relation lists cover different lines.** Appendix B, the literals, lists 60 relations
from every measured line whose final code is L, real or not (README reading 9). Appendix C, the
false-positive audit, lists 56 relation signatures from the `true_flaw` lines of real L flaws. Five
relations are only in Appendix B: `I_motors >= 2 * V_pack * I_stall / V_rated`,
`T_gb <= r_ext * T_m`, `r_gb == r_m * r_ext`, `tau_g <= r_ext * tau_m` and `w_gb == w_m / r_ext`.
`M == r * tau_s` appears twice in Appendix C, as two signatures with different inputs.

**14. Fewer real flaws than planned.** §10's resolution estimate assumed about 310 real flaws in the
measured set. There are 250: of the 297 measured flaws, 34 are not real and 13 undecided.

## Figures added after the run

**Reported, never a result.** `CRITERIA.md` asks for these figures, and the frozen tally does not
compute them. They were computed on 23.10.2026, after the run and after the tally, by
`law_report.py`, **code added after the run**.
- It reuses the tally's own classes and functions.
- It reads only the published data: `data/`, the committed `slice.json` and the frozen corpora the
  tally reads too.
- It first re-runs the tally on the same files, and refuses unless that reproduces `tally.json`
  byte for byte. It did.
- Its full output is `data/report_extra.json`. Its test, on the synthetic fixture, is
  `test_report.py`.
- None of these figures changes a code, a share, a label or the decision.

### §6: the slice under each prompt version

The slice has no reality verdicts, so every slice line is taken as real. Its lines are coded by
§5.7 rule 1 from that round's forms. §5.6 then turns them into G, with that round's deciding forms
and the published re-gate records; 14 slice lines matched in each round. Its flaws are the flaws of
`flaws.jsonl` cut to their slice lines: 52 flaws in 7 clusters, aggregated by §5.7 rule 2.

| | v0 (round 1) | v1 (round 2) |
|---|---|---|
| Lines; flaws | 129; 52 | 129; 52 |
| κ₅, weighted [95 % cluster interval] | 0.713 [0.543, 0.960] | 0.751 [0.598, 0.821] |
| κ₅, unweighted | 0.709 | 0.736 |
| κ_L, weighted [95 % cluster interval] | 0.860 [0.612, 0.981] | 0.881 [0.668, 0.990] |
| κ_L, unweighted | 0.813 | 0.857 |
| Disagreements after §5.5 | D–N 15, L–N 3, D–G 2, D–L 2, G–L 1, G–N 1 | D–N 14, L–N 4, G–L 2, D–L 1, G–N 1 |
| **L share, flaws** | **11.5 %** (6 of 52); Wilson [5.4, 23.0] %; cluster [1.0, 53.6] % | **13.5 %** (7 of 52); Wilson [6.7, 25.3] %; cluster [1.0, 64.7] % |
| L share, lines | 17.1 % (22 of 129) | 20.2 % (26 of 129) |
| Final line codes | D 64, N 36, L 22, G 7 | D 55, N 40, L 26, G 7, uncoded 1 |

Round 1's disagreement counts equal `bank.json`'s. **The bank's lean toward L** (Appendix D, and
disclosure 3): v1 coded one more slice flaw L than v0 (7 against 6 of 52) and four more slice lines
(26 against 22 of 129). The two rounds are separate sessions, so this mixes the prompt change with
session-to-session variation.

### §8.2 item 1: G's parts and the kinds of D and N, as shares

Of the 250 real flaws.

| Part or kind | Share | Flaws |
|---|--:|--:|
| G, caught where the coders also claimed G | 5.2 % | 13 |
| G, caught where they coded L or L-if-data | 3.6 % | 9 |
| D, record | 21.6 % | 54 |
| D, source | 12.4 % | 31 |
| D, table | 1.2 % | 3 |
| D, `fallback` | 10.0 % | 25 |
| N, traceability | 18.0 % | 45 |
| N, judgement | 1.2 % | 3 |
| N, process | 0.8 % | 2 |
| N, `fallback` | 0.8 % | 2 |

### §8.2 item 4: every code's share by role, class, set, reviewer kind and origin

Each cell gives the share, the flaws in brackets, and its own 95 % cluster-bootstrap interval in
per cent (`random.Random(13)`, 10,000 draws, as §8.1). The Wilson intervals are in
`data/report_extra.json`. The L column equals tally.json's breakdowns.

| By role (flaws) | G | L | L-if-data | D | N | uncoded |
|---|---|---|---|---|---|---|
| base (15) | 0.0 % (0) [0.0, 0.0] | 46.7 % (7) [20.0, 73.3] | 20.0 % (3) [0.0, 40.0] | 26.7 % (4) [6.7, 53.3] | 6.7 % (1) [0.0, 20.0] | 0.0 % (0) [0.0, 0.0] |
| control (79) | 2.5 % (2) [0.0, 7.5] | 11.4 % (9) [3.1, 25.9] | 0.0 % (0) [0.0, 0.0] | 55.7 % (44) [41.5, 72.4] | 29.1 % (23) [12.2, 41.1] | 1.3 % (1) [0.0, 4.9] |
| electrical (80) | 5.0 % (4) [0.0, 10.5] | 23.8 % (19) [13.3, 37.1] | 10.0 % (8) [3.5, 16.3] | 42.5 % (34) [32.5, 54.0] | 18.8 % (15) [10.2, 25.0] | 0.0 % (0) [0.0, 0.0] |
| firmware (27) | 7.4 % (2) [0.0, 20.7] | 18.5 % (5) [5.0, 30.0] | 0.0 % (0) [0.0, 0.0] | 59.3 % (16) [33.3, 85.0] | 14.8 % (4) [2.9, 33.3] | 0.0 % (0) [0.0, 0.0] |
| mechanical (49) | 28.6 % (14) [13.7, 44.4] | 20.4 % (10) [6.1, 37.3] | 2.0 % (1) [0.0, 6.8] | 30.6 % (15) [14.0, 47.8] | 18.4 % (9) [9.3, 27.5] | 0.0 % (0) [0.0, 0.0] |

| By error class (flaws) | G | L | L-if-data | D | N | uncoded |
|---|---|---|---|---|---|---|
| base (15) | 0.0 % (0) [0.0, 0.0] | 46.7 % (7) [20.0, 73.3] | 20.0 % (3) [0.0, 40.0] | 26.7 % (4) [6.7, 53.3] | 6.7 % (1) [0.0, 20.0] | 0.0 % (0) [0.0, 0.0] |
| equilibrium (65) | 29.2 % (19) [17.9, 43.4] | 23.1 % (15) [10.0, 40.0] | 9.2 % (6) [0.0, 16.7] | 21.5 % (14) [13.0, 30.6] | 16.9 % (11) [8.6, 23.7] | 0.0 % (0) [0.0, 0.0] |
| magnitude (45) | 0.0 % (0) [0.0, 0.0] | 8.9 % (4) [0.0, 20.0] | 0.0 % (0) [0.0, 0.0] | 73.3 % (33) [55.6, 87.9] | 17.8 % (8) [3.8, 35.6] | 0.0 % (0) [0.0, 0.0] |
| propagation (60) | 5.0 % (3) [0.0, 11.1] | 18.3 % (11) [8.2, 27.9] | 3.3 % (2) [0.0, 6.1] | 48.3 % (29) [33.9, 64.9] | 23.3 % (14) [14.3, 30.8] | 1.7 % (1) [0.0, 6.3] |
| unit (65) | 0.0 % (0) [0.0, 0.0] | 20.0 % (13) [7.5, 42.1] | 1.5 % (1) [0.0, 5.9] | 50.8 % (33) [39.6, 64.1] | 27.7 % (18) [8.1, 40.0] | 0.0 % (0) [0.0, 0.0] |

| By set (flaws) | G | L | L-if-data | D | N | uncoded |
|---|---|---|---|---|---|---|
| fresh (132) | 7.6 % (10) [2.3, 14.1] | 26.5 % (35) [16.8, 37.4] | 4.5 % (6) [1.0, 8.3] | 42.4 % (56) [32.1, 52.5] | 18.2 % (24) [11.6, 24.5] | 0.8 % (1) [0.0, 2.5] |
| practice (118) | 10.2 % (12) [3.5, 19.4] | 12.7 % (15) [6.8, 21.1] | 5.1 % (6) [0.8, 11.1] | 48.3 % (57) [36.1, 62.0] | 23.7 % (28) [11.3, 33.8] | 0.0 % (0) [0.0, 0.0] |

| By reviewer kind (flaws) | G | L | L-if-data | D | N | uncoded |
|---|---|---|---|---|---|---|
| paired (242) | 8.7 % (21) [4.4, 13.9] | 19.8 % (48) [13.7, 27.3] | 5.0 % (12) [2.0, 8.5] | 45.0 % (109) [37.1, 53.1] | 21.1 % (51) [14.2, 27.6] | 0.4 % (1) [0.0, 1.4] |
| generalist (37) | 13.5 % (5) [2.8, 25.7] | 35.1 % (13) [19.4, 51.4] | 0.0 % (0) [0.0, 0.0] | 40.5 % (15) [25.7, 55.6] | 10.8 % (4) [2.7, 21.1] | 0.0 % (0) [0.0, 0.0] |

| By origin (flaws) | G | L | L-if-data | D | N | uncoded |
|---|---|---|---|---|---|---|
| on the injection (87) | 18.4 % (16) [9.2, 28.0] | 24.1 % (21) [12.9, 36.0] | 1.1 % (1) [0.0, 3.7] | 43.7 % (38) [30.5, 57.3] | 12.6 % (11) [6.0, 19.8] | 0.0 % (0) [0.0, 0.0] |
| elsewhere (163) | 3.7 % (6) [0.8, 7.8] | 17.8 % (29) [10.9, 26.0] | 6.7 % (11) [2.5, 11.9] | 46.0 % (75) [37.3, 54.8] | 25.2 % (41) [16.2, 33.3] | 0.6 % (1) [0.0, 2.2] |

### §8.2 item 6: the flaw verdicts by side

A measured flaw's side is the side of its measured lines. Its verdict is §2.3's: real if any line is
`true_flaw`, not real if every line is `not_a_flaw`, otherwise undecided.

| The flaw's measured lines | Real | Not real | Undecided |
|---|--:|--:|--:|
| injected side only | 135 | 23 | 9 |
| twin side only | 33 | 10 | 4 |
| both sides | 82 | 1 | 0 |

### §9 threat 3: L by family

§9 names "the family field". §5.1 defines it: the ARCH-080 check whose purpose the relation falls
under, or none. It is read from each L flaw's representative line, as the tally reads the other L
fields.

| Family | L flaws | Existing relation the gate did not form | New relation |
|---|--:|--:|--:|
| 3, static equilibrium and load path | 11 | 4 | 7 |
| 4, power balance | 18 | 0 | 18 |
| 5, energy and mass conservation | 12 | 4 | 8 |
| 7, cross-domain propagation | 4 | 0 | 4 |
| none | 5 | 0 | 5 |

No L flaw falls under family 1 (units), 2 (magnitude) or 6 (thermal).

## Deviations

**None.** The extraction and grouping counts held exactly, the re-gate equals the `a-fresh` gate
lines, the token guard was never reached, the projection check held, and nothing else was impossible
as specified. No `deviations.json` was written, and tally.json's `decision.deviations` is empty. The
decision is taken.

---

## Published under §11

Everything is in `data/` unless the row says otherwise. Each data file is a byte-for-byte copy of
the run's work dir file of the same name (the ledger from `ledger/`), except `regate.jsonl.gz`.
`data/SHA256SUMS` covers every file below; check it with `shasum -a 256 -c SHA256SUMS` from `data/`.

| What §11 names | File | Bytes |
|---|---|--:|
| The finding lines, with their ids and loci (and set, pair, side, run, reviewer kind, role, section, item and stripped text) | `lines.jsonl` | 920,337 |
| Their flaw ids (steps A to D) | `flaws.jsonl` | 95,399 |
| The units of readings S1 and S6 | `units_s1.jsonl`, `units_s6.jsonl` | 99,703; 92,701 |
| The extraction and grouping counts | `extract_counts.json`, `group_counts.json` | 1,784; 309 |
| Every coder, adjudicator and audit form, with §5.5's outcome: the code claimed (`code_raw`), the code after §5.5 (`code`), the failure, the relation's facts, and the adjudicator's A/B labels | `codes.jsonl` | 2,573,547 |
| Every reality verdict and origin, per measured line | `reality.jsonl` | 104,309 |
| The 34 control verdicts, each flaw's reality, both bars and the prior agreement | `reality_summary.json` | 10,902 |
| Every reality and control form: the schema's four fields (`id`, `verdict`, `origin`, `reason`) of the form the scoring used, with the line, packet, finding id and try | `reality_forms.jsonl` | 368,019 |
| The re-gate records, 120 design versions (gzip) | `regate.jsonl.gz` | 290,793 |
| The re-gate's check against `a-fresh` | `regate_check.json` | 168 |
| Each line's gate match (§5.6) | `matches.jsonl` | 73,369 |
| The tally's full output, sha256 `79190e7b…0f71d350` | `tally.json` | 31,824 |
| The figures added after the run (`law_report.py`) | `report_extra.json` | 27,693 |
| The ledger, one line per try (exit, model asked and used, packet, step, tokens, try, time, validity) | `ledger.jsonl` | 132,937 |
| The launch log (both phases; every line of the two launch outputs is in it) | `launch.log` | 9,142 |
| The slice | `../slice.json` (committed at "Slice filled") | 312 |
| The bank items chosen, with round 1's counts | `../bank.json` (committed at "Prompt filled") | 982 |
| Each prompt version | `../prompts/v0/`, `../prompts/v1/`, `../prompts/final/` (committed at "Prompt filled") | |
| The deviations | none | |

- **The re-gate records are compressed.** The work dir's `regate.jsonl` is 4,973,516 bytes, sha256
  `2477300bbc9078c2f2c66a37ed7d7da08eead35b85cad88de044445ae036bea1`. That is larger than any file
  the repository tracks, and neither R-PG-01 nor R-PG-02 published raw gate records. So it is
  published compressed with `gzip -n -9` (no name, no time stamp, so the same bytes every time):
  `regate.jsonl.gz`, sha256 `f26cd2cd2eb3f07adedc61c4e97e815f5ee1ca063f01fac7aa1b7377f08a0a21`.
  `gunzip -c regate.jsonl.gz` gives the work dir's file byte for byte.
- **The reality forms** (`reality_forms.jsonl`, 898 rows: 864 reality lines and 34 controls) were
  extracted after the run from each reality and control session's structured output. They take the
  form the scoring used (the first try's valid form, else the retry's, as `law_reality.py` reads
  it), and only the schema's four fields. Never the transcript, the result text or the usage. Every
  row's verdict and origin equal those in `reality.jsonl` or `reality_summary.json`. No form held a
  field beyond the schema.
- **The ledger** carries no field that identifies the account.
- **Not published:** the session transcripts and raw outputs, and the account files (§11); the
  packets, which the scripts build from committed inputs; and the prior adjudication's output,
  which was read only for the agreement and whose digest is in `inputs/digests.json`.
- Before commit, every published file was scanned for the token prefixes `sk-ant-` and `oat01`,
  for session ids, API keys, credentials and e-mail addresses: none was found. The only local
  paths are in two lines of `launch.log`, and they name the run's work dir.

## Reproducing it

- **The tally from the published data.** Make a work dir from `data/`: every file except
  `tally.json`, `launch.log` and `regate.jsonl.gz`, with `ledger.jsonl` placed at
  `ledger/ledger.jsonl`, and `../slice.json` beside them. Then, from a checkout of `672618e`:
  `uv run python -I experiments/R-LAW-01/law_tally.py <work dir>`. This was done on 23.10.2026,
  from master at `fc28f32`, whose R-LAW-01 scripts, `src/`, `knowledge/` and two corpora are
  identical to `672618e`'s. It gave a `tally.json` byte-identical to the published one (sha256
  `79190e7b…0f71d350`) in about 16 seconds.
- **The figures added after the run.** `uv run python -I experiments/R-LAW-01/law_report.py
  experiments/R-LAW-01/data` re-runs the tally on the published files, refuses unless it reproduces
  `tally.json`, and writes `data/report_extra.json`. It takes about 18 seconds.
- **The run.** `law_launch.sh preflight`, `calibrate` and `measure` on a work dir made by
  `law_extract.py`, `law_group.py`, `law_slice.py` and `law_regate.py`, at the commits above, with the
  pinned binary and `RLAW_PRIOR` set to the prior adjudication's output at its digest (header of
  `law_launch.sh`). The sessions are model calls, so a re-run gives new forms.

---

## Appendix A. The law frequency table (§8.2 item 3)

Each L flaw's representative line, by the law its deciding form names, word for word.

| Law, as the deciding form names it | L flaws |
|---|--:|
| Conservation of mass: the balanced plant's mass equals the sum of the masses of its parts | 2 |
| DC motor current is highest at stall: no-load current <= stall current | 2 |
| Electrical energy of a cell = voltage x charge | 2 |
| Moment balance on the chassis: the total reaction equals the sum of the per-side motor reactions. | 2 |
| Operating current <= rated current limit of the same part | 2 |
| Torque bound of a gear train (output torque <= ratio x input torque, efficiency <= 1) | 2 |
| A consumer updated once per delivered sample cannot exceed the producer's rate (rate <= throughput) | 1 |
| A filter updated on every delivered sample cannot update faster than the samples arrive (rate <= throughput) | 1 |
| A voltage margin is the rating minus the operating value: dV = Vmax - Vs. This is the node's own derived-quantity arithmetic, a Kirchhoff-type difference of voltages. | 1 |
| Conservation of mass: the mass of the balancing plant is the total mass of the assembled robot | 1 |
| Conservation of mass: the whole robot's mass equals the sum of its parts (robot without battery plus battery pack); control.balance_loop.mass is defined by the same derivation as the robot's total mass | 1 |
| Electrical power P = V * I | 1 |
| Energy conservation at stall (no mechanical output), so the heat dissipated equals the electrical input power P = V*I | 1 |
| Energy over time: t = E / P_avg; since the average draw is at most the stall draw P, t >= E / P | 1 |
| Gear train kinematics (output speed = input speed / ratio) | 1 |
| Gear train kinematics: counts per output revolution = counts per input revolution x gear ratio | 1 |
| Gear train kinematics: overall ratio equals the product of the stage ratios | 1 |
| Gear-train torque multiplication summed over two drive sides (moment balance on the chassis) | 1 |
| Moment balance on the gearmotor mount: at stall the housing reacts the motor's output torque (the stall torque). | 1 |
| Moment balance on the gearmotor mount: the reaction equals the motor's output torque at stall. | 1 |
| Moment balance: chassis reaction moment equals the sum of the drive motors' torques reacting on it | 1 |
| Moment sum: the torques of two motors acting on the same body add | 1 |
| Ohm's law at stall (I = V/R, R = V_rated/I_stall) | 1 |
| Ohm's law at stall (current proportional to applied voltage through the winding resistance) | 1 |
| Ohm's law at stall (zero back-EMF): I_stall(V) = V * I_stall,rated / V_rated, summed over two motors | 1 |
| Ohm's law at stall summed over two motors (Kirchhoff's current law) | 1 |
| Ohm's law at stall: I_stall = V / R, with R = V_rated / I_stall_rated, summed over two motors (Kirchhoff's current law) | 1 |
| Ohm's law for a stalled DC motor (winding resistance R = V_rated / I_stall) | 1 |
| Ohm's law for a stalled DC motor (winding resistance R = V_rated / I_stall, so stall current scales with applied voltage) | 1 |
| Ohm's law for a stalled DC motor (zero back-EMF): I = V/R, with R = V_rated / I_stall | 1 |
| Ohm's law for a stalled DC motor winding (I = V/R, R = V_rated/I_stall_rated), summed over two motors | 1 |
| Ohm's law: stall current = V / R_winding, so it scales linearly with the applied voltage (two motors in parallel on the branch) | 1 |
| Ohm's law: stall current scales with applied voltage through a fixed winding resistance (R = V_rated / I_stall) | 1 |
| Operating voltage limit must not exceed the part's voltage rating | 1 |
| Torque sum of two parallel drives bounded by each drive's peak output torque (gear-train torque bound) | 1 |
| conservation of mass (the balanced plant is the whole robot, so its mass is the sum of its parts) | 1 |
| conservation of mass (the plant mass is the assembled robot's total mass) | 1 |
| conservation of mass: the balance-loop plant mass is the mass of the assembled robot | 1 |
| electrical energy of a cell = nominal voltage x charge capacity | 1 |
| electrical power P = V*I | 1 |
| gear train kinematics: output speed = input speed / gear ratio | 1 |
| operating voltage limit not above the motor's rated voltage | 1 |
| torque bound of a gear train (output torque <= ratio x input torque, efficiency <= 1), summed over two drivetrains | 1 |
| voltage margin = rating minus operating value (difference of two voltages on the same node) | 1 |

## Appendix B. Every L relation and its literals (§5.2, §8.2 item 8)

Every distinct relation of every measured line whose final code is L, with the lines that state it.

| Relation | Kind | Literals | Lines |
|---|---|---|---|
| `C_w == C_m * N_g` | law | none | L0024, L0301 |
| `E == V * Q` | law | none | L0798 |
| `E_cell == V_cell * Q_cell` | law | none | L0590, L0591, L0679, L0796, L0952, L0954 |
| `E_pack == (V_pack / V_cell) * E_cell` | law | none | L0799 |
| `E_pack == 6 * E_cell` | law | 6.0 | L0593, L0955 |
| `I_br == 2 * I_s * V_p / V_r` | law | 2.0 | L0454 |
| `I_br == 2 * V_s * I_st / V_r` | law | 2.0 | L0359, L0449, L0452 |
| `I_branch == 2 * I_stall * V_pack / V_rated` | law | 2.0 | L0012 |
| `I_d == 2 * I_s * V_s / V_r` | law | 2.0 | L0442 |
| `I_d == I_st * V_s / V_r` | law | none | L0513 |
| `I_d == V_p * I_s / V_r` | law | none | L0974, L0978 |
| `I_draw == 2 * I_s * V_pack / V_r` | law | 2.0 | L0165, L0170, L0443 |
| `I_draw == 2 * I_s * V_s / V_r` | law | 2.0 | L0455 |
| `I_draw == V_pack * I_stall / V_rated` | law | none | L0509 |
| `I_draw >= V_pack * I_stall / V_rated` | law | none | L0822, L0827 |
| `I_m == 2 * I_s * V_s / V_r` | law | 2.0 | L0288, L0385 |
| `I_m >= 2 * V_s * I_st / V_r` | law | 2.0 | L0160, L0445, L0447 |
| `I_motors >= 2 * V_pack * I_stall / V_rated` | law | 2.0 | L0825 |
| `I_nl <= I_lim` | limit | none | L0584, L0587, L0795 |
| `I_nl <= I_st` | law | none | L0588, L0589, L0678, L0951 |
| `I_nl <= I_stall` | law | none | L0794 |
| `I_out == I_s * V_p / V_r` | law | none | L0610, L0611, L0613 |
| `I_pk == 2 * V_p * I_s / V_r` | law | 2.0 | L0818 |
| `I_tot >= 2 * V_s * I_st / V_r` | law | 2.0 | L0006 |
| `M == r * tau_s` | law | none | L0988, L0989 |
| `M_ch == M_l + M_r` | law | none | L0563, L0565, L0568, L0775 |
| `M_l == T_s` | law | none | L0564, L0671, L0774, L0778 |
| `M_r == tau_L + tau_R` | law | none | L0476, L0477, L0633, L0695, L0850 |
| `N_o == N_m * N_e` | law | none | L0704, L0706 |
| `N_overall == N_motor * N_ext` | law | none | L0492, L0857, L0859 |
| `N_w == N_m * r` | law | none | L0023 |
| `P == V * I` | law | none | L0539, L0540, L0659, L0748, L0749, L0908, L0909 |
| `P_s == V_imu * I_imu` | law | none | L0515, L0516, L0645, L0719, L0880, L0881 |
| `Q == V * I` | law | none | L0690, L0691, L0813, L0814 |
| `Q_stall == V * I_stall` | law | none | L0967 |
| `R_ch == 2 * r * tau_s` | law | 2.0 | L0990 |
| `R_ch == M_L + M_R` | law | none | L0933 |
| `T_bl <= 2 * T_gb` | law | 2.0 | L0438, L0440 |
| `T_gb <= r_ext * T_m` | law | none | L0456, L0457, L0458 |
| `T_out <= r * T_in` | law | none | L0462, L0463, L0464 |
| `T_pk == tau_L + tau_R` | law | none | L0734 |
| `V_lim <= V_rated` | limit | none | L0103, L0241, L0243, L0365, L0367, L0422, L0468 |
| `dV == Vmax - Vop` | law | none | L0783 |
| `dV == Vmax - Vs` | law | none | L0674 |
| `f_est <= f_drv` | law | none | L0554, L0921 |
| `m_bl == m_ch + m_fp + m_bat` | law | none | L0337, L0424 |
| `m_bl == m_nb + m_b` | law | none | L0336 |
| `m_loop == m_nobatt + m_batt` | law | none | L0104, L0423 |
| `m_plant == m_asm` | law | none | L0642, L0714, L0715, L0870, L0960 |
| `m_plant == m_assembly` | law | none | L0806 |
| `m_plant == m_assy` | law | none | L0500, L0501 |
| `m_plant == m_unladen + m_batt` | law | none | L0601, L0684 |
| `p == m_ch + m_bat` | law | none | L0598, L0599, L0683, L0804 |
| `r_gb == r_m * r_ext` | law | none | L0001 |
| `t_run >= E / P` | law | none | L0946 |
| `tau_bl <= 2 * r_ext * tau_m` | law | 2.0 | L0373, L0374 |
| `tau_g <= r_ext * tau_m` | law | none | L0354, L0357 |
| `w_g == w_m / r_ext` | law | none | L0172, L0383 |
| `w_gb == w_m / r_ext` | law | none | L0285, L0294 |
| `w_sl == w_m / r` | law | none | L0132, L0136, L0338, L0339, L0425, L0426 |

## Appendix C. The false-positive audit, per relation (§8.2 item 5)

Each relation as the tally evaluated it (one per signature of set, relation, inputs, tolerance and
kind; the line is the first that states it), with the clean twins of its set it would block.

| Relation | Line | Clean twins it would block |
|---|---|--:|
| `E == V * Q` | L0798 | 0 |
| `E_cell == V_cell * Q_cell` | L0590 | 0 |
| `E_pack == (V_pack / V_cell) * E_cell` | L0799 | 0 |
| `E_pack == 6 * E_cell` | L0593 | 0 |
| `I_d == I_st * V_s / V_r` | L0513 | 40 |
| `I_d == V_p * I_s / V_r` | L0974 | 40 |
| `I_draw == V_pack * I_stall / V_rated` | L0509 | 40 |
| `I_draw >= V_pack * I_stall / V_rated` | L0822 | 40 |
| `I_nl <= I_lim` | L0587 | 0 |
| `I_nl <= I_st` | L0588 | 0 |
| `I_nl <= I_stall` | L0794 | 0 |
| `I_out == I_s * V_p / V_r` | L0610 | 40 |
| `I_pk == 2 * V_p * I_s / V_r` | L0818 | 40 |
| `M == r * tau_s` | L0988 | 1 |
| `M == r * tau_s` | L0989 | 1 |
| `M_ch == M_l + M_r` | L0563 | 0 |
| `M_l == T_s` | L0778 | 0 |
| `M_r == tau_L + tau_R` | L0476 | 0 |
| `N_o == N_m * N_e` | L0704 | 0 |
| `N_overall == N_motor * N_ext` | L0492 | 0 |
| `P == V * I` | L0539 | 0 |
| `P_s == V_imu * I_imu` | L0515 | 0 |
| `Q == V * I` | L0690 | 0 |
| `Q_stall == V * I_stall` | L0967 | 0 |
| `R_ch == 2 * r * tau_s` | L0990 | 40 |
| `R_ch == M_L + M_R` | L0933 | 0 |
| `T_pk == tau_L + tau_R` | L0734 | 0 |
| `dV == Vmax - Vop` | L0783 | 0 |
| `dV == Vmax - Vs` | L0674 | 0 |
| `f_est <= f_drv` | L0554 | 0 |
| `m_plant == m_asm` | L0714 | 0 |
| `m_plant == m_assembly` | L0806 | 0 |
| `m_plant == m_assy` | L0500 | 0 |
| `m_plant == m_unladen + m_batt` | L0601 | 0 |
| `p == m_ch + m_bat` | L0598 | 0 |
| `t_run >= E / P` | L0946 | 0 |
| `C_w == C_m * N_g` | L0024 | 0 |
| `I_br == 2 * I_s * V_p / V_r` | L0454 | 19 |
| `I_br == 2 * V_s * I_st / V_r` | L0359 | 19 |
| `I_branch == 2 * I_stall * V_pack / V_rated` | L0012 | 19 |
| `I_d == 2 * I_s * V_s / V_r` | L0442 | 19 |
| `I_draw == 2 * I_s * V_pack / V_r` | L0170 | 19 |
| `I_draw == 2 * I_s * V_s / V_r` | L0455 | 19 |
| `I_m == 2 * I_s * V_s / V_r` | L0385 | 19 |
| `I_m >= 2 * V_s * I_st / V_r` | L0160 | 19 |
| `I_tot >= 2 * V_s * I_st / V_r` | L0006 | 19 |
| `N_w == N_m * r` | L0023 | 0 |
| `T_bl <= 2 * T_gb` | L0438 | 0 |
| `T_out <= r * T_in` | L0464 | 20 |
| `V_lim <= V_rated` | L0103 | 1 |
| `m_bl == m_ch + m_fp + m_bat` | L0337 | 1 |
| `m_bl == m_nb + m_b` | L0336 | 0 |
| `m_loop == m_nobatt + m_batt` | L0104 | 0 |
| `tau_bl <= 2 * r_ext * tau_m` | L0373 | 20 |
| `w_g == w_m / r_ext` | L0172 | 20 |
| `w_sl == w_m / r` | L0132 | 0 |
| **All 56** | | **515 blocks; 60 distinct twins** |

## Appendix D. The records of §2.2 that are not finding lines, per run (§8.2 item 7)

Counted, never coded.

| Run | `criteria` | `spec_defects` | `indicators` | `finding` | `subject` |
|---|--:|--:|--:|--:|--:|
| `practice-0` | 39 | 321 | 108 | 39 | 39 |
| `practice-1` | 40 | 485 | 116 | 40 | 39 |
| `practice-2` | 38 | 439 | 109 | 38 | 38 |
| `a-fresh` | 78 | 805 | 212 | 78 | 78 |
| `b-fresh` | 80 | 7 | 201 | 80 | 80 |
| `repeat-K` | 79 | 861 | 229 | 79 | 79 |
| `round-1` | 80 | 900 | 225 | 80 | 80 |
