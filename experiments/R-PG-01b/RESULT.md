# R-PG-01b — result: R-PG-01's reviewer side, re-run with the complete parts sheet

> Git-tracked and public. `ARCH-nnn` and experiment IDs only.

**Status: "numbers final"** (`CRITERIA.md` §8, step 2). This file holds the sections on R-PG-01b
alone, computed by the blind analyst on 01.11.2026 from the run tag's clone and `~/runs/rpg01b/`.
Nothing of R-PG-01's results was read to write it. The comparison with R-PG-01 (§8, step 3: the
replication, the share of R-PG-01's advantage, the gate across time and D1's sentence) is **not**
here. `compare_r_pg_01.py` adds it as the last section, in a commit of its own.

**Complete, 01.11.2026.** The comparison is now the last section, added in a commit of its own
after "numbers final" was pushed. §10 items 6 to 13 and §1's citations were added after it. The
sections the analyst wrote are otherwise as committed at "numbers final".

**The tally's output:** `numbers/tally.json`, sha256
**`719602a055ebf2fdb40b2af3bcc17563da541ee47d41dba3dbda0f4d5837d832`**, written by `contrast.py`
and given in full in Appendix A.
**The reason reading's output:** `numbers/reasons.json`, sha256
`750a0655ea84587b969aa0133c25a8bd03b0ed8d3e7579f2d38f9811c6e0f139`, written by `reasons_tally.py`.

## 1. Provenance

| What | Value |
|---|---|
| Run tag | `r-pg-01b-run`, at `2341e651930d1afa36a843581be4e22778f3be22` |
| Run commit, round 1 | `4c98383f96a020abc60bd75a060f38028ceb4849` (L1's HEAD) |
| Run commit, round 2 (attempt 2) | `2341e651930d1afa36a843581be4e22778f3be22` (L1's HEAD): the round-1 commit plus the owner's waiver at L1, as `master` held it (§7 below) |
| R-PG-01's run commit | `8bc03fc` |
| The frozen `CRITERIA.md` (L2) | blob `a0dd1dcc4420ef246d9c260c9cc6cd09a338d6ab` |
| "scripts" commit (L2) | round 1: `91efa69ac2287d77b0e63bccc648ae4a60bdcbec`; round 2: `c0310f301860acbb52cdf20c33c5bb7c0c23b049` |
| "sheet" commit (L2) | `bab905c3eb748dbf9d697fbaaf2b8f8a5a0bfe59`; arm F's corpus tree `22ef52d4c1b26dc4782745d5cde5130ba5b71081` |
| Arm I's manifest (L4) | `41553301d5b036f84df289ee6d8c87ecce4504d5a09969e05291e23c9ebc026a` |
| Arm F's manifest (L4) | `8c9ceb11ffe91afd28b79dd1d206507b463bb1bf8bb8bb8f33a0a27b84e3ba57`; sheet `2efbb6a8ab889ceac54d8ebdba15c8530274d8524c9eaf6181d22abf5ccbef90` |
| Binary (L3) | 2.1.301, sha256 `1e119036a802d359ba5f9886428e031586e8796f7a858d5a8ee179ac7b8604f0` (the Linux build) |
| Machine (L1) | Oracle, Ubuntu 24.04.5 LTS, aarch64, git 2.43.0 |

The freeze commit, the "sheet filled" and "run commit filled" commits, and the digests of §2.5 are
`master`'s; they are cited when these files are copied to `master` (Appendix A of `CRITERIA.md`).
The analyst's clone holds the run tag alone and does not carry them.

**Cited at the copy to `master` (added 01.11.2026, §13):**

| What | Commit |
|---|---|
| The freeze | `e1262da3a85f659ff600036eaf68e8c57ea5c47b` (PR #72) |
| "scripts" | `1f097e36`, fixed before round 1 up to `91efa69ac2287d77b0e63bccc648ae4a60bdcbec` (PR #74); for round 2, `c0310f301860acbb52cdf20c33c5bb7c0c23b049` (PR #80, §10 item 8) |
| "sheet" | `bab905c3eb748dbf9d697fbaaf2b8f8a5a0bfe59` |
| "sheet filled" | `530724f5d370b7ead08a2c3091ae63a3051fbad5` |
| "run commit filled" | `3ecacc225d1b40579e27cff187cf425dc6284a01`; filled again before round 1 by `8a6d8df3`, `be74c532` and `80e948cb` (23.10.2026), and after round 1 by `622c670f` (30.10.2026, §10 item 8) |
| Run commit and tag, round 1 | `4c98383f96a020abc60bd75a060f38028ceb4849`, tag `r-pg-01b-run-round-1` |
| Run commit and tag, round 2 | `2341e651930d1afa36a843581be4e22778f3be22`, tag `r-pg-01b-run` |
| "numbers final" | `a73a7892110d2b335073ba813f44e6d6b63c7e82` on `exp/r-pg-01b-numbers` |

**The pins of §2.2 and the digests of §2.5 (added 01.11.2026, after "numbers final", §13).**
- L3 checked every pin of `CRITERIA.md` §2.2 at each of the three launches, and L4 held both arms'
  manifests and arm F's sheet to §2.5. `launch.sh` stops before any review when a check fails
  (§14), and reviews ran at all three launches, so both checks passed each time.
- The checks' own records (`L3.json`, `L4.json`) stay on Oracle and are not published. Each value
  below is therefore given again as git gives it, recomputed on 01.11.2026 at both run commits:
  `4c98383` (round 1) and `2341e651` (round 2, both attempts). At both commits every value equals
  the pin.
- `<c>` stands for either run commit, and `sha256sum` takes the sha256 of the blob's bytes.

| Pin | Value at `4c98383` and at `2341e651` | Checked at launch by | How it is got from git |
|---|---|---|---|
| Gate tree | `29e7c8061e4f5e54b815afd41bf98f9e6455a7c3` | L3 | `git rev-parse <c>:src/physgate/gate` |
| Bounds blob | `cdeb9736d93362120f8f08f0244ab449b7bd5f90`; sha256 `b75d14d541243108d02f0afc1414a8cd61493f694325c9c2e4f09e30cfa27071` | L3 | `git rev-parse <c>:knowledge/electrical/bounds.toml`; `git cat-file blob <c>:knowledge/electrical/bounds.toml \| sha256sum` |
| Spelling blob | `eaa4ce697092d27545a19c87c6d92fc6f1e966fc` | L3 | `git rev-parse <c>:src/physgate/unit_spelling.py` |
| Catalogue digest | `171b054b61f703fee2aaf750b4ff107754bbf0726882e18531cb92db0028d69f` | L3 | **Not a git value.** L3 computes it with `catalogue_digest()` over the catalogue's content, and its record is not published. Its source, `src/physgate/gate/catalogue.py` (blob `b2ff867a2d2fd2f1ea95b03c9dea2881631d9df1` at both commits), lies inside the gate tree above. |
| Reviewers tree | `7df979eecb5b9acba572c5687747ea33586a87e1` | L3 | `git rev-parse <c>:src/physgate/reviewers` |
| Rubrics tree | `dd203340de8cee2f42878bb09ee72e64dfe1465b` | L3 | `git rev-parse <c>:knowledge/reviewers` |
| Rubric, control | `18be8569a3743d6f9f5ff554ac6fd7e7c86b082ffaad4c08d0a40a00bac111f5` | L3 | `git cat-file blob <c>:knowledge/reviewers/control/rubric.md \| sha256sum` |
| Rubric, electrical | `a1b78302cf116ce471bf24a484de24a1e98e8679256e41d5f36b3dd4f48219b3` | L3 | the same, for `electrical/rubric.md` |
| Rubric, firmware | `e265ef4733443d1af8a8152a8831fa97f999c3fcae0acc8f12f48fe1faed5f8a` | L3 | the same, for `firmware/rubric.md` |
| Rubric, mechanical | `3ca83fe1099481ff4c32681b7e63a594e907dd01bcd6a56a8160ed0a8e0783fa` | L3 | the same, for `mechanical/rubric.md` |
| Instrument tree (§2.4) | `dcb84fdbcc036de47e3f8aa96afc5b789ae1dd42` | L3 | `git rev-parse <c>:src/physgate/evaluation/inject` |
| Run parameters | `experiments/R-PG-01/params.json`, blob `f32da7e47303ee168cc9671edb2a8b40e72b024e` | L3 | `git rev-parse <c>:experiments/R-PG-01/params.json` |
| Scoring scripts | `tally_rows.py` `0f138e7fa353e545cfab749ce73c7ca2e063f0f4`, `read_catches.py` `d311b76e7492f81a54cba5e51dccdbc103505fad`, `regate_r6.py` `39c33c98e0f6da328383020d14cbcbe1d08b44b3`, `r4_twins.py` `a30afd3d4fecb742085c6d5d569710a528a1f58a`, `r3_scan.py` `dfcddf2c34da27337cd956b9548c0d0c3aa706e8` | L3 | `git rev-parse <c>:experiments/R-PG-01/<script>` |
| The rest of the repository | `8bc03fc` plus §2.4's paths. `git diff --name-only 8bc03fc <c>` lists 82 files, all under those paths: the 4 named source and test files, 45 under `corpora/injected-errors/v1-fullsheet/` and 33 under `experiments/R-PG-01b/`. `uv.lock` is blob `df5c97af2fd3dd851846b841d9f9f232751780c2`, the same as at `8bc03fc`. | L2 | `git diff --name-only 8bc03fc <c>`; `git rev-parse <c>:uv.lock` |
| The invocation | R-PG-01's, as its `launch.sh` (blob `63efe5ac3f182d9b99c5870ae318caf871bc9c8e`) runs it, without the keep-awake wrapper | — | Not a digest. The diff of this experiment's `launch.sh` against that file is published as `diffs/launch.sh.diff`. |
| Binary | 2.1.301, sha256 `1e119036a802d359ba5f9886428e031586e8796f7a858d5a8ee179ac7b8604f0` | L3 | **Not in git.** L3 read the binary at `~/pinned/claude-2.1.301` on Oracle, and its record is not published. The version is also in each published smoke record (`records/launch-<r>-<a>/smoke/smoke.json`, `binary_version`). |
| Arm I's manifest | `41553301d5b036f84df289ee6d8c87ecce4504d5a09969e05291e23c9ebc026a` | L4 | `git cat-file blob <c>:corpora/injected-errors/v1/MANIFEST.json \| sha256sum` |
| Arm I's `sources.json` | `bc1e5ec15c6f1df823f5a39207b0656b6a2b388eca4d3414db007b4d7999ca91` | through arm I's manifest (L4) | `git cat-file blob <c>:corpora/injected-errors/v1/sources.json \| sha256sum` |
| Arm F's manifest (§2.5) | `8c9ceb11ffe91afd28b79dd1d206507b463bb1bf8bb8bb8f33a0a27b84e3ba57` | L4 | `git cat-file blob <c>:corpora/injected-errors/v1-fullsheet/MANIFEST.json \| sha256sum` |
| Arm F's sheet (§2.5) | `2efbb6a8ab889ceac54d8ebdba15c8530274d8524c9eaf6181d22abf5ccbef90` | L4; each published smoke record also gives it (`sheet_sha256`) | `git cat-file blob <c>:corpora/injected-errors/v1-fullsheet/sources.json \| sha256sum` |
| The table, unedited (§2.5) | `29f9568ce8465112ef0b0b164f05f3ba76f9702e3ccbc7a1dea96fbc3d057b3f`, 30,998 bytes; blob `9d597b8d988a226b186e7b38ae734607210d062e` | through arm F's manifest (L4) | `git cat-file blob <c>:corpora/injected-errors/v1-fullsheet/parts_sheet.md \| sha256sum` (`v1`'s copy is the same) |

The R6.05 edit's digests are not launch checks. They are `make_sheet.sh`'s output at the "sheet"
commit, and the edited copy lives on `master` only (§2.4), so they are computed from that copy:

| §2.5 digest | Before | After | How it is got from git |
|---|---|---|---|
| The table | `29f9568ce8465112ef0b0b164f05f3ba76f9702e3ccbc7a1dea96fbc3d057b3f` (30,998 bytes) | `0573ef044ebdcee9ff184eec2789e1a10b31fef6f32947735f9005ea8b0daedc` (30,999 bytes) | After: `git cat-file blob bab905c3:experiments/R-PG-01b/sheet/parts_sheet.md \| sha256sum` (blob `c7a5b003bd58db26353877836dbbd23c17c7091f`, the same on `master` now). Before: that copy with its one "responded" put back as "answered". The result has git blob `9d597b8d…`, arm F's `parts_sheet.md` at both run commits. |
| Row R6.05's table line | `e2a58b268972a03fbd710be37df6ce3992209f336c03238efd3c405089bb0368` | `9976c090b279fa6d74c3a49dac455bed9d25cea40d3a3d59adc49a26b39e13de` | The row's one line in each table, without its newline, cut as `fullsheet.py`'s `edit_table` cuts it |
| Row R6.05's note | `7aa9c88bbf959fb64e136e8abe9e6007e6d4faf365d7eb1f1671d85820612af2` | `46a0698bb1dc51349623245a2f01a4af34995b21e5b1147d6f6e7e119d16c56d` | That line's seventh cell, split as `edit_table` splits it |

**The run records §13 publishes** are in `records/`, copied byte for byte from `~/runs/rpg01b/` on
Oracle, with their sha256 in `records/SHA256SUMS`:
- each valid run's results file, `run-<k>/results.jsonl` (slots 3 to 6). Each run's
  `physgate catches` output is in `numbers/tally.json` under `checks`, held to the rows;
- each attempt's smoke record and stream-check verdict (`launch-<r>-<a>/smoke/smoke.json`,
  `L10.json`), and its end record with counts and void causes (`after.json`);
- the slot draw (`slots.json`), the owner's launch statements (`owner-*.json`) and the quota
  ledger (`ledger-round-*`). `launch.sh` reads only `owner-<r>.json`, so attempt 1's
  `owner-2.json` was renamed `owner-2.attempt-1.json` before attempt 2, and kept under that name.
  The orchestrator wrote both of round 2's owner files on the owner's word.

## 2. Runs, attempts and slots

Slot draw (`random.Random(29)`, 29.10.2026 13:03:42Z): I1 → 4, F1 → 3, I2 → 2, F2 → 1.

| Round | Attempt | Slots (I, F) | UTC | Valid | Void causes |
|---|---|---|---|---|---|
| 1 | 1 | 4, 3 | 29.10.2026 13:12:22Z – 30.10.2026 04:29:34Z | yes | — |
| 2 | 1 | 2, 1 | 30.10.2026 20:49:48Z – 31.10.2026 07:43:06Z | **no** | usage limit; a crashed or killed process |
| 2 | 2 | 6, 5 | 31.10.2026 11:49:51Z – 01.11.2026 04:01:55Z | yes | — |

Both rounds are valid, so the analysis is the R = 2 form. Nothing of the void attempt was read but
its causes and counts.

**Launch checks, both valid attempts:** L1 to L11 passed. L2: 0 paths outside §2.4, 0 blobs that
differ. L3: every pin held. L4: 0 of 41 base and artefact files differ. L5: arm I's 80 packets
identical to `8bc03fc`'s. L6: arm F 0 of 80 refused. L7: 80 of 80 differ only as allowed. L8: R4
40/40, records `ea3d581a…`. L9: R3 with 0 problems for each arm. L10: one smoke each, a whole read
and no cut (1,225 numbered lines). L11: T = 454,435 (round 1) and 605,584 (round 2).

## 3. Did the treatment reach the reviewers? (§5.5)

No cut read in any review of either valid round. Per arm, round and side (from each round's end
record):

| Run | Side | Reviews | Read the sheet | Never read it | Read calls | Whole | Part | Cut | Covered every line | Stream missing |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| I, round 1 | injected | 40 | 30 | 10 | 30 | 30 | 0 | 0 | 30 | 0 |
| I, round 1 | twin | 40 | 33 | 7 | 33 | 33 | 0 | 0 | 33 | 0 |
| F, round 1 | injected | 40 | 31 | 9 | 31 | 31 | 0 | 0 | 31 | 0 |
| F, round 1 | twin | 40 | 34 | 6 | 34 | 34 | 0 | 0 | 34 | 0 |
| I, round 2 | injected | 40 | 33 | 7 | 33 | 33 | 0 | 0 | 33 | 0 |
| I, round 2 | twin | 40 | 36 | 4 | 36 | 35 | 1 | 0 | 35 | 0 |
| F, round 2 | injected | 40 | 31 | 9 | 33 | 30 | 3 | 0 | 30 | 0 |
| F, round 2 | twin | 40 | 33 | 7 | 33 | 33 | 0 | 0 | 33 | 0 |

`unchanged`, `error` and `no_result` reads: 0 in every cell. `rubric_sha256`: 0 mismatches in
every run. Infrastructure `review_unavailable`: 0 in every run, so no cascade.

## 4. Per run and per arm (§5.1)

| Run | A | C | Kill reading | Twins approved | Without a verdict (injected) |
|---|--:|--:|---|--:|---|
| I, round 1 | 0 | 0 | fires | 3 of 40 | a19 (`invalid_verdict`) |
| F, round 1 | 0 | 0 | fires | 1 of 40 | — |
| I, round 2 | 0 | 0 | fires | 5 of 40 | — |
| F, round 2 | 1 | 0 | fires | 1 of 40 | — |

| Arm | Ā (95 % bootstrap) | C̄ (95 % bootstrap) | Kill reading on the means | Rounds agree |
|---|---|---|---|---|
| I | 0.0 (0.0 to 0.0) | 0.0 (0.0 to 0.0) | fires | yes |
| F | 0.5 (0.0 to 1.5) | 0.0 (0.0 to 0.0) | fires | yes |

The gate caught 17 of 40 artefacts, the same 17 in every run. Results 2, 3, 4 and 6 are identical
in every run and printed once in the output. Results 1 to 10 per run are in Appendix A.

**R6:** holds. Gate records identical across the four runs, gate catches the same artefacts,
`regate_r6.py` reports 0 records that differ, and results 2, 3, 4 and 6 are identical.

## 5. The primary contrast (§5.2) and D2

**The floor of §7 holds:** C̄(I) = 0.0 < 3 and C̄(F) = 0.0 < 3. The gate's added catches are
**not measurable at this approval rate**. ΔC is printed under that label, and the share is not
printed.

| Contrast | Value | 95 % bootstrap | Newcombe, round 1 | Newcombe, round 2 | Discordant (F not I / I not F) | Pairs | Exact p | Shown |
|---|--:|---|---|---|---|--:|--:|---|
| ΔC (floor) | 0.0 | 0.0 to 0.0 | −3.50 to 3.50 | −3.50 to 3.50 | 0 / 0 | 34 | 1.0 | no |

**D2:** "not measurable at this approval rate".

## 6. Secondary contrasts (§5.3)

Arm F minus arm I, paired per (artefact, round), pooled over both rounds.

| Contrast | Value | 95 % bootstrap | Newcombe, round 1 | Newcombe, round 2 | Discordant (F not I / I not F) | Pairs | Exact p | Shown |
|---|--:|---|---|---|---|--:|--:|---|
| ΔA | 0.5 | 0.0 to 1.5 | 0.0 (−3.50 to 3.50) | 1.0 (−2.60 to 5.15) | 1 / 0 | 80 | 1.0 | no |
| ΔT | −3.0 | −5.5 to −1.0 | −2.0 (−6.53 to 1.45) | −4.0 (−9.15 to −0.09) | 0 / 6 | 80 | 0.03125 | **yes** |
| Δnamed (twin condition) | 0.0 | −4.0 to 4.0 | | | 6 / 6 | 80 | 1.0 | no |
| Δcited (no twin condition) | −1.5 | −5.0 to 1.5 | | | 3 / 6 | 80 | 0.508 | no |
| ΔCNN | −1.0 | −3.0 to 1.0 | | | 1 / 3 | 34 | 0.625 | no |
| ΔC among rejected | 0.5 | 0.0 to 1.5 | | | 1 / 0 | 80 | 1.0 | no |

Where a contrast is not shown, the bootstrap interval's bounds are the largest effects not
excluded. Newcombe's intervals for the rows left blank above are in Appendix A.

- **Per class (counts):** ΔA is 0.5 for magnitude and 0.0 for equilibrium, propagation and unit.
  ΔC is 0.0 in every class.
- **Per role (counts):** ΔA is 0.5 for control and 0.0 for electrical, firmware and mechanical.
  ΔC is 0.0 in every role.
- **Sensitivity** (every pair holding a `blocked` or `review_unavailable` review excluded): ΔA 0.5
  (0.0 to 1.5, p = 1.0, 79 pairs); ΔC 0.0 (0.0 to 0.0, p = 1.0, 33 pairs). Neither is shown.
- **`blocked` and `review_unavailable`:** no injected artefact was `blocked`. One injected review
  ended `review_unavailable`, in arm I, round 1 (a19, control, `invalid_verdict`). The twins'
  `blocked` reviews are all `blocking_spec_defect`, on the control role: arm I 4 and 3, arm F 5
  and 5, in rounds 1 and 2. Twins' `review_unavailable`, all `invalid_verdict`: arm I round 1, 3;
  arm F round 1, 2; round 2, none. Per-role lists, turns and wall clock are in Appendix A.
- **Noise floor** (disagreements; Cohen's κ):

  | | Injected approval | Twin approval |
  |---|---|---|
  | Arm I, round 1 against round 2 | 0 (κ undefined) | 6 (0.17) |
  | Arm F, round 1 against round 2 | 1 (0.00) | 2 (−0.03) |
  | Round 1, arm F against arm I | 0 (κ undefined) | 2 (0.48) |
  | Round 2, arm F against arm I | 1 (0.00) | 4 (0.30) |

- **Lag, arm F minus arm I (§9 threat 6):** each review's start, per artefact. Injected side:
  median 573 s in round 1, 1,292 s in round 2. Per side and artefact in Appendix A.

## 7. Every rejection read for its reason (§6)

**Run of the reading:** 266 reality packets (2,807 finding lines, 145 injected-version packets and
121 twin-version packets) and 28 rejection-control packets. 294 sessions on `claude-opus-5-5`,
294 valid first tries, 0 retries, 0 failed calls. The 30 M guard was not reached, and the reading
is not void. The packets passed the blind check after the fix of §9 below: 266 of 266, and 28 of
28 control packets.

**Line verdicts:** `true_flaw` 2,573, `not_a_flaw` 180, `undecidable` 54, `missing` 0.

**Controls:**
- Calibration: 78 of 82 P reviews calibrated (95 %). Bar 70 %: **met**.
- Rejection control: 25 of 28 control lines `not_a_flaw` (89 %). Bar 70 %: **met**.
- **The O/N split is reliable.**

**Classes, per arm and round:**

| Run | Side | B | P | O-introduced | O-base | O-unsplit | N | U |
|---|---|--:|--:|--:|--:|--:|--:|--:|
| I, round 1 | injected | 0 | 17 | 21 | 1 | 0 | 0 | 0 |
| F, round 1 | injected | 0 | 20 | 20 | 0 | 0 | 0 | 0 |
| I, round 2 | injected | 0 | 24 | 16 | 0 | 0 | 0 | 0 |
| F, round 2 | injected | 0 | 21 | 18 | 0 | 0 | 0 | 0 |
| I, round 1 | twin | 4 | 0 | 19 | 10 | 0 | 1 | 0 |
| F, round 1 | twin | 5 | 0 | 17 | 13 | 0 | 2 | 0 |
| I, round 2 | twin | 3 | 0 | 21 | 9 | 0 | 2 | 0 |
| F, round 2 | twin | 5 | 0 | 23 | 10 | 0 | 1 | 0 |

**The paired change in N:** injected side, 0 in each direction in both rounds. Twins: in round 1,
one twin is N in F and not in I. In round 2, one is N in I and not in F.

**The twins' corrected refusal rate** (N over 40; upper bound N + U over 40):

| Run | Rate | Upper bound |
|---|--:|--:|
| I, round 1 | 2.5 % | 2.5 % |
| F, round 1 | 5.0 % | 5.0 % |
| I, round 2 | 5.0 % | 5.0 % |
| F, round 2 | 2.5 % | 2.5 % |

**D4:** arm F's corrected refusal rate, as the mean over its rounds, is **3.75 %**, with arm I's,
**3.75 %**, beside it. The split is reliable, so the figure carries no label.

**Descriptive:** finding lines that cite by row id one of the 62 rows R-PG-01's sheet left
without a value: arm F 67 of 1,451 (4.6 %), arm I 13 of 1,356 (1.0 %), a lower bound. P reviews'
error-item lines judged `not_a_flaw`: 4.

Every review's class and every finding line's verdict are in `numbers/reasons.json`.

## 8. Decisions that need no comparison with R-PG-01 (§7)

- **D1:** arm F's reading is the corrected headline. Its kill reading on the means **fires**, and
  its two rounds agree, so it is not labelled "not stable at this size". Arm I's two rounds also
  agree, so row 1 of D1's table does not hold. D1's sentence needs R-PG-01's reading, and
  `compare_r_pg_01.py` takes it at the last step.
- **D2:** "not measurable at this approval rate" (the floor).
- **D3:** stands unconditionally. R-PG-02's reviewer arms are re-run with the complete sheet as a
  new experiment.
- **D4:** 3.75 % (arm F), with 3.75 % (arm I) beside it. The split is reliable.

## 9. A fixed analysis script, with both outputs (§8)

**01.11.2026, `reasons_packets.py` `blind()`** (commit `2ae5cac` on this branch). The check
rebuilds each packet from `key.json`, which is written with sorted keys. A packet of ten or more
findings was therefore rebuilt in the order F1, F10, F11, F12, F2, … and never matched its file.
The packets themselves are built in label order and did not change. A test of a packet with
twelve findings was added.

- Before the fix: `{"blind": false, "files": 266, "hits_in_the_fixed_words": {}, "not_their_template": 216, "packets": 266}`
  (`numbers/blind-before-fix.json`). The 216 packets are exactly those with ten or more findings.
- After the fix: `{"blind": true, "files": 266, "hits_in_the_fixed_words": {}, "not_their_template": 0, "packets": 266}`
  (`numbers/blind-after-fix.json`).

The bug was found before any reality session ran, and no session saw a packet the check had not
passed. The fix changes no rule and no number of §5. The tally (`contrast.py`) was run once and
was not changed.

## 10. Deviations and disclosures

1. **Round 2's first attempt is void** (usage limit; a crashed or killed process). It was
   re-attempted into slots 6 and 5 (§12).
2. **§11's idle-account rule was waived by the owner for round 2's first attempt** (decided
   30.10.2026, recorded at L1): "the orchestrator session and its agents keep working on this same
   account during round 2, as during round 1". That attempt is void. **The waiver's text says
   that the orchestrator also worked on the account during round 1**, while round 1's L1 records
   the owner's confirmation that no other session would run (`owner-1.json`). That is recorded
   here as a deviation of §11 for round 1. No rule of §12 voids a round for it, and nothing in the
   round-1 records (0 HTTP 429s, 0 usage-limit files, 0 infrastructure `review_unavailable`)
   shows an effect. Arm F and arm I shared the account and the time, so the I-against-F contrast
   is not exposed to it.
3. **Round 2's valid attempt ran on another account than round 1:** "fresh run account
   (31.10.2026)", token digest prefix `4389780d`, where round 1's was `af24827d`. The owner
   confirmed it idle at L1. Both arms of each round shared their account, so the pairing within a
   round holds. The contrast pools rounds run on two accounts. §2.3 row 5 names one run account,
   so this is recorded as a deviation. The reason reading's sessions ran with whichever credential
   `~/.config/physgate-run.env` held on 01.11.2026, which the analyst never read.
4. **The scripts commit differs between the rounds** (`91efa69` against `c0310f3`): the round-2
   run commit carries the L1 waiver handling, as `master` held it. L2 passed against `master` at
   each launch. The analysis scripts run here are those of the run tag, plus §9's fix.
5. **The review roots** (`~/review-scratch/rpb-<k>`, §2.6 and §10) lie outside `~/runs/rpg01b/`.
   The analyst passed them to `contrast.py` for the sessions' process records (turns, wall clock
   and lag), as §5.3 and §14 require, and did not open them otherwise.

**Added 01.11.2026, after the comparison.** Items 1 to 5 are the analyst's, as committed at
"numbers final". Items 6 to 13 complete them with what the analyst could not know from its
clone: what happened on the account during the run, the owner's decisions, and the steps after
"numbers final". None of them changes a number.

6. **Round 1 did not run on an idle account, and the owner waived the rule after the fact.**
   - The run account was also the account of the orchestrator session that ran the project. From
     round 1's launch checks (about 13:04Z on 29.10.2026), that session and four of its agents,
     working on other tasks on the laptop, used the same account while round 1's reviews ran.
   - `owner-1.json` records "no other session during the round" as true. It was written at launch,
     before this was noticed, and is a launch record, so it is published as written.
   - When it was noticed (about 15:40Z), the agents were stopped. The same afternoon the owner
     decided to keep round 1 and to waive §11's idle-account rule for it. Work then went on at a
     modest load for the rest of the round.
   - No rule of §12 voids a round for this. The round's records show no effect: 0 HTTP 429s, 0
     usage-limit files, 0 infrastructure `review_unavailable`. Both arms shared the account and
     the time, so the I-against-F contrast is not exposed to it.
7. **Round 2's first attempt was void because the account's weekly usage limit ran out, and our own
   sessions had used most of it.**
   - The attempt ran under the owner's recorded waiver (item 2), so the orchestrator and its agents
     kept working on the same account.
   - At 07:42:51Z on 31.10.2026 the watcher stopped both arms on the usage limit, so they ended
     killed (exit 143). That is why both causes are listed.
   - The two sources give different usage-limit counts, and both are given as they stand. The
     run's log at the watcher's stop, which is not published, gives 4 sessions ended on a usage
     limit and 4 HTTP 429 responses. The attempt's end record, `records/launch-2-1/after.json`,
     written by the `after` check once the watcher had stopped the arms, gives
     `"usage_limit_files": 2` and `"status_429s": 4`. No published record explains the difference.
   - The limit was the account's weekly allowance. The attempt itself had used 67,239,573 review
     tokens in 118 sessions, plus 376,252 in its smoke. The rest of the week's use was other work on
     the same account: during that week the account was shared by this project and four other
     projects of the owner, as the owner states. The owner's waiver covered only the orchestrator
     and its agents.
   - The waiver did not raise the limit. §11 has no weekly gate, since the owner set no weekly cap,
     but the account still had one.
   - It counts as attempt 1 of 3 for round 2. Nothing of it was read but its causes and counts.
8. **The run code was pinned again between the rounds, and its fill came after round 1.**
   - Round 1 ran at the run commit `4c98383f96a020abc60bd75a060f38028ceb4849`, kept by the tag
     `r-pg-01b-run-round-1`.
   - For round 2 the owner chose to let work go on during the round under a recorded waiver,
     instead of keeping the account idle for about 15 hours. L1 refused to start without the
     owner's confirmation, so L1 was changed to accept a recorded waiver.
   - The change landed on `master` as a new "scripts" commit,
     `c0310f301860acbb52cdf20c33c5bb7c0c23b049` (PR #80, merge `c457975f`). The run commit became `2341e651930d1afa36a843581be4e22778f3be22`:
     `4c98383` plus that change, in 5 files under `experiments/R-PG-01b/`. The owner moved the tag
     `r-pg-01b-run` to it on 30.10.2026.
   - The instrument tree (`dcb84fdb…`) and every gate, reviewer and rubric pin are unchanged, so
     both rounds' reviews were made by the same code.
   - `CRITERIA.md`'s run-commit fact was filled again for `2341e651` by the dated commit
     `622c670f` on 30.10.2026. R1 places every fill before the first review, and this one came
     after round 1, so it is a deviation of R1. No rule, threshold or other value changed with it.
   - Round 2's valid attempt ran at `2341e651` with no waiver (item 9).
9. **Round 2's valid attempt ran on a different, fresh account.**
   - It was a Team premium seat, label "fresh run account (31.10.2026)", token digest prefix
     `4389780d`. Round 1 ran on the original run account, prefix `af24827d`.
   - The owner moved the run to it because the shared account's weekly limit had voided attempt 1.
     On the owner's word nothing else used the new account until the run was done, and
     `owner-2.json` records that.
   - The model, the binary, the instrument, gate, reviewer and rubric code (every pin) and the
     machine were the same as in round 1. The run commit differed only in L1's owner check (item 8).
     An account carries quota, not a model.
   - The analyst's session and the reason reading's 294 sessions also ran on the fresh account. It
     was the only credential the run's scripts read from 31.10.2026 on.
   - Round 2's ledger line (`records/ledger-round-2.*`) gives the fresh account's label and prefix
     for both attempts. Attempt 1's 118 sessions in fact ran on the original account (item 7). The
     record is published as written.
10. **The analyst was started by the orchestrator, on the owner's behalf.**
    - Appendix A has the owner start the analyst. Instead, the owner asked the orchestrator to run
      the analysis itself. The orchestrator declined: it has read R-PG-01's results, and §8's
      protection is an analyst who has not.
    - With the owner's approval, the orchestrator started a fresh headless session on Oracle at
      09:10:14Z on 01.11.2026: the pinned binary 2.1.301, `claude-opus-5-5`, in the §8 clone
      `~/rpg01b-analysis` at the run tag. It was the session's own, not a subagent. Its first and
      only message was Appendix A's prompt verbatim (23 lines, sha256 prefix `99f1457ccc10`).
    - It ended at 11:15:50Z with exit 0. Its push failed, because Oracle has no git login.
    - The orchestrator fetched its branch from Oracle and pushed it to GitHub unchanged, without
      opening its files. Origin's `exp/r-pg-01b-numbers` is `a73a7892`, the commit the analyst
      made.
11. **An analysis script was fixed after it ran (§9, commit `2ae5cac`); both outputs are kept.**
    - The fault was in the blind check of the reason reading's packets, not in the packets. The
      check rebuilt each packet's findings from a key file stored in sorted order. So any packet
      of ten or more findings came back as F1, F10, F11, F12, F2, … and never matched its file.
    - The check therefore refused 216 of 266 packets: exactly those with ten or more findings.
    - The analyst found it before any reality session ran. The fix makes the check rebuild in
      label order, and a test with a twelve-finding packet was added. The corrected check passed
      266 of 266.
    - As §8 requires, both outputs are published (`numbers/blind-before-fix.json`,
      `numbers/blind-after-fix.json`), and the corrected one decides. No session saw a packet the
      corrected check had not passed, the packets did not change, and no rule changed.
12. **The comparison (the last section) did not run in the run checkout.**
    - §14 says every script runs in `~/physgate-r-pg-01b-run` on Oracle. That checkout was left
      untouched. `compare_r_pg_01.py` ran on Oracle in a fresh clone of `exp/r-pg-01b-numbers`,
      which holds the same script blob.
    - R-PG-01's run directory exists only on the laptop, so it was copied to Oracle for this step.
      Its digest was the same before and after the copy.
    - The script reads only the committed tally output and the run directories, so where it ran
      does not change what it computes.
13. **§2.3 row 5's comparison of accounts with R-PG-01 rests on the owner's statement, not on
    records.**
    - R-PG-01's records hold no account label and no token digest prefix. Its launch script read
      its credential from the laptop's local environment file (`.env`).
    - The owner states that R-PG-01 ran on the credential in the laptop's `.env`, the Team account
      (stated 01.11.2026).
    - For reference, the token now in that `.env` has sha256 prefix `4389780d`, the same as round 2's
      valid attempt (item 9). The orchestrator computed that prefix by digest alone on 31.10.2026,
      without reading the token.
    - Whether R-PG-01 used that same token cannot be checked from its records. Under the rule of `CRITERIA.md`'s
      preamble and §12's last bullet, the comparison is impossible as specified, and only the owner's statement stands in for it. No
      step of §8 and no decision of §7 rests on it.

---

## Appendix A. The tally's full output

`contrast.py --run I1=~/runs/rpg01b/run-4,~/review-scratch/rpb-4 --run F1=~/runs/rpg01b/run-3,~/review-scratch/rpb-3 --run I2=~/runs/rpg01b/run-6,~/review-scratch/rpb-6 --run F2=~/runs/rpg01b/run-5,~/review-scratch/rpb-5`,
run once on 01.11.2026 at the run tag `2341e65`, as `uv run --frozen python -I`. sha256
`719602a055ebf2fdb40b2af3bcc17563da541ee47d41dba3dbda0f4d5837d832` over the bytes below, which are
`numbers/tally.json`.

```json
{
 "D1": {
  "arm_F_kill_on_means": true,
  "arm_F_rounds_agree": true,
  "arm_I_rounds_agree": true,
  "label": null,
  "sentence": "the last step's (compare_r_pg_01.py): it reads R-PG-01's reading"
 },
 "D2_sentence": "not measurable at this approval rate",
 "R": 2,
 "R6": {
  "gate_catches_identical_across_runs": true,
  "gate_records_identical_across_runs": true,
  "holds": true,
  "regate_differ_total": 0,
  "results_2_3_4_6_identical": true
 },
 "arms": {
  "F": {
   "A_mean": {
    "bootstrap": {
     "high": 1.5,
     "low": 0.0,
     "undefined_draws": 0
    },
    "value": 0.5
   },
   "C_mean": {
    "bootstrap": {
     "high": 0.0,
     "low": 0.0,
     "undefined_draws": 0
    },
    "value": 0.0
   },
   "kill_on_means": true,
   "kill_per_round": {
    "1": true,
    "2": true
   },
   "rounds_agree_on_kill": true
  },
  "I": {
   "A_mean": {
    "bootstrap": {
     "high": 0.0,
     "low": 0.0,
     "undefined_draws": 0
    },
    "value": 0.0
   },
   "C_mean": {
    "bootstrap": {
     "high": 0.0,
     "low": 0.0,
     "undefined_draws": 0
    },
    "value": 0.0
   },
   "kill_on_means": true,
   "kill_per_round": {
    "1": true,
    "2": true
   },
   "rounds_agree_on_kill": true
  }
 },
 "artefacts": 40,
 "checks": {
  "F1": {
   "read_catches": {
    "C_from_rows": 0,
    "caught_from_rows": 17,
    "holds": true,
    "rows": [
     "injected {\"artefacts_caught\": 4, \"blocking_failures\": 8, \"caught_after_reviewer_passed\": 0, \"check\": 1, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"units\", \"no_review\": 0, \"reviewer_had_failed\": 8, \"reviewer_had_passed\": 0}",
     "injected {\"artefacts_caught\": 1, \"blocking_failures\": 2, \"caught_after_reviewer_passed\": 0, \"check\": 2, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"magnitude\", \"no_review\": 0, \"reviewer_had_failed\": 2, \"reviewer_had_passed\": 0}",
     "injected {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 3, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"equilibrium\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "injected {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 4, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"power\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "injected {\"artefacts_caught\": 2, \"blocking_failures\": 4, \"caught_after_reviewer_passed\": 0, \"check\": 5, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"conservation\", \"no_review\": 0, \"reviewer_had_failed\": 4, \"reviewer_had_passed\": 0}",
     "injected {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 6, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"thermal\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "injected {\"artefacts_caught\": 11, \"blocking_failures\": 12, \"caught_after_reviewer_passed\": 0, \"check\": 7, \"checks_run\": 40, \"gate_mode\": \"observe\", \"name\": \"propagation\", \"no_review\": 0, \"reviewer_had_failed\": 12, \"reviewer_had_passed\": 0}",
     "injected {\"artefacts_caught\": 17, \"blocking_failures\": 26, \"caught_after_reviewer_passed\": 0, \"check\": null, \"checks_run\": 520, \"gate_mode\": \"observe\", \"name\": \"all\", \"no_review\": 0, \"reviewer_had_failed\": 26, \"reviewer_had_passed\": 0}",
     "controls {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 1, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"units\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "controls {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 2, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"magnitude\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "controls {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 3, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"equilibrium\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "controls {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 4, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"power\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "controls {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 5, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"conservation\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "controls {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 6, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"thermal\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "controls {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 7, \"checks_run\": 40, \"gate_mode\": \"observe\", \"name\": \"propagation\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "controls {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": null, \"checks_run\": 520, \"gate_mode\": \"observe\", \"name\": \"all\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}"
    ]
   },
   "regate_differ": 0,
   "rubric_lines": 78,
   "sessions": [
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 14,
     "wall_s": 440.66
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 12,
     "wall_s": 434.589
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 25,
     "wall_s": 412.259
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 18,
     "wall_s": 1628.268
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 17,
     "wall_s": 887.438
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 18,
     "wall_s": 794.558
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 35,
     "wall_s": 721.46
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 18,
     "wall_s": 659.18
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 38,
     "wall_s": 716.233
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 19,
     "wall_s": 681.124
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 36,
     "wall_s": 825.323
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 13,
     "wall_s": 524.5
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 25,
     "wall_s": 596.178
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 19,
     "wall_s": 806.93
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 33,
     "wall_s": 597.884
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 16,
     "wall_s": 666.725
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 15,
     "wall_s": 1262.937
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 20,
     "wall_s": 730.491
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 13,
     "wall_s": 580.394
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 13,
     "wall_s": 496.351
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 17,
     "wall_s": 524.205
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 12,
     "wall_s": 365.158
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 30,
     "wall_s": 563.153
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 23,
     "wall_s": 694.136
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 20,
     "wall_s": 767.427
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 22,
     "wall_s": 788.583
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 18,
     "wall_s": 664.977
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 18,
     "wall_s": 1334.36
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 12,
     "wall_s": 479.883
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 16,
     "wall_s": 816.675
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 39,
     "wall_s": 606.282
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 25,
     "wall_s": 719.81
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 16,
     "wall_s": 734.755
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 12,
     "wall_s": 503.932
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 16,
     "wall_s": 250.711
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 33,
     "wall_s": 623.319
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 17,
     "wall_s": 565.61
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 13,
     "wall_s": 693.793
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 14,
     "wall_s": 662.033
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 17,
     "wall_s": 662.125
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 31,
     "wall_s": 509.723
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 18,
     "wall_s": 745.57
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 16,
     "wall_s": 729.551
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 34,
     "wall_s": 684.594
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 16,
     "wall_s": 487.67
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 32,
     "wall_s": 810.154
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 13,
     "wall_s": 455.161
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 16,
     "wall_s": 553.458
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 12,
     "wall_s": 598.405
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 20,
     "wall_s": 654.775
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 16,
     "wall_s": 629.295
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 14,
     "wall_s": 505.544
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 21,
     "wall_s": 741.097
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 15,
     "wall_s": 797.256
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 23,
     "wall_s": 546.852
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 13,
     "wall_s": 749.226
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 12,
     "wall_s": 583.582
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 28,
     "wall_s": 767.637
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 13,
     "wall_s": 643.179
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 21,
     "wall_s": 1236.951
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 17,
     "wall_s": 362.62
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 25,
     "wall_s": 567.979
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 42,
     "wall_s": 701.105
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 14,
     "wall_s": 757.456
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 11,
     "wall_s": 691.062
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 11,
     "wall_s": 570.989
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 17,
     "wall_s": 1045.519
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 23,
     "wall_s": 787.392
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 25,
     "wall_s": 524.742
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 12,
     "wall_s": 799.683
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 13,
     "wall_s": 466.719
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 25,
     "wall_s": 796.272
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 20,
     "wall_s": 526.264
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 42,
     "wall_s": 669.316
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 20,
     "wall_s": 864.458
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 23,
     "wall_s": 723.394
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 12,
     "wall_s": 512.105
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 43,
     "wall_s": 693.509
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 19,
     "wall_s": 537.766
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 40,
     "wall_s": 691.671
    }
   ]
  },
  "F2": {
   "read_catches": {
    "C_from_rows": 0,
    "caught_from_rows": 17,
    "holds": true,
    "rows": [
     "injected {\"artefacts_caught\": 4, \"blocking_failures\": 8, \"caught_after_reviewer_passed\": 0, \"check\": 1, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"units\", \"no_review\": 0, \"reviewer_had_failed\": 8, \"reviewer_had_passed\": 0}",
     "injected {\"artefacts_caught\": 1, \"blocking_failures\": 2, \"caught_after_reviewer_passed\": 0, \"check\": 2, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"magnitude\", \"no_review\": 0, \"reviewer_had_failed\": 2, \"reviewer_had_passed\": 0}",
     "injected {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 3, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"equilibrium\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "injected {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 4, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"power\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "injected {\"artefacts_caught\": 2, \"blocking_failures\": 4, \"caught_after_reviewer_passed\": 0, \"check\": 5, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"conservation\", \"no_review\": 0, \"reviewer_had_failed\": 4, \"reviewer_had_passed\": 0}",
     "injected {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 6, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"thermal\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "injected {\"artefacts_caught\": 11, \"blocking_failures\": 12, \"caught_after_reviewer_passed\": 0, \"check\": 7, \"checks_run\": 40, \"gate_mode\": \"observe\", \"name\": \"propagation\", \"no_review\": 0, \"reviewer_had_failed\": 12, \"reviewer_had_passed\": 0}",
     "injected {\"artefacts_caught\": 17, \"blocking_failures\": 26, \"caught_after_reviewer_passed\": 0, \"check\": null, \"checks_run\": 520, \"gate_mode\": \"observe\", \"name\": \"all\", \"no_review\": 0, \"reviewer_had_failed\": 26, \"reviewer_had_passed\": 0}",
     "controls {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 1, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"units\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "controls {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 2, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"magnitude\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "controls {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 3, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"equilibrium\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "controls {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 4, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"power\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "controls {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 5, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"conservation\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "controls {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 6, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"thermal\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "controls {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 7, \"checks_run\": 40, \"gate_mode\": \"observe\", \"name\": \"propagation\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "controls {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": null, \"checks_run\": 520, \"gate_mode\": \"observe\", \"name\": \"all\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}"
    ]
   },
   "regate_differ": 0,
   "rubric_lines": 80,
   "sessions": [
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 19,
     "wall_s": 758.018
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 15,
     "wall_s": 669.039
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 27,
     "wall_s": 550.162
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 13,
     "wall_s": 814.189
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 21,
     "wall_s": 796.954
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 14,
     "wall_s": 1397.789
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 21,
     "wall_s": 621.7
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 22,
     "wall_s": 1535.527
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 12,
     "wall_s": 575.77
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 11,
     "wall_s": 573.613
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 33,
     "wall_s": 1549.98
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 14,
     "wall_s": 712.671
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 17,
     "wall_s": 710.377
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 14,
     "wall_s": 864.509
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 26,
     "wall_s": 988.246
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 14,
     "wall_s": 673.499
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 15,
     "wall_s": 585.753
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 12,
     "wall_s": 725.542
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 12,
     "wall_s": 701.909
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 18,
     "wall_s": 575.425
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 13,
     "wall_s": 461.103
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 13,
     "wall_s": 541.78
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 14,
     "wall_s": 626.165
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 13,
     "wall_s": 737.016
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 25,
     "wall_s": 939.342
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 20,
     "wall_s": 566.614
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 17,
     "wall_s": 526.329
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 22,
     "wall_s": 769.094
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 10,
     "wall_s": 375.96
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 16,
     "wall_s": 651.467
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 27,
     "wall_s": 626.61
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 25,
     "wall_s": 1444.92
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 14,
     "wall_s": 703.189
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 13,
     "wall_s": 558.326
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 12,
     "wall_s": 345.908
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 17,
     "wall_s": 564.95
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 12,
     "wall_s": 475.347
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 26,
     "wall_s": 715.273
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 12,
     "wall_s": 477.918
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 19,
     "wall_s": 509.545
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 11,
     "wall_s": 361.533
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 18,
     "wall_s": 623.52
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 14,
     "wall_s": 644.225
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 16,
     "wall_s": 641.05
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 33,
     "wall_s": 615.632
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 43,
     "wall_s": 1462.244
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 22,
     "wall_s": 575.406
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 16,
     "wall_s": 536.489
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 22,
     "wall_s": 627.792
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 17,
     "wall_s": 672.167
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 17,
     "wall_s": 651.476
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 13,
     "wall_s": 501.253
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 39,
     "wall_s": 762.663
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 18,
     "wall_s": 695.778
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 29,
     "wall_s": 683.399
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 16,
     "wall_s": 741.368
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 28,
     "wall_s": 561.312
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 32,
     "wall_s": 707.115
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 17,
     "wall_s": 744.72
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 35,
     "wall_s": 818.591
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 18,
     "wall_s": 517.695
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 41,
     "wall_s": 656.018
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 43,
     "wall_s": 764.143
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 39,
     "wall_s": 801.237
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 18,
     "wall_s": 601.758
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 32,
     "wall_s": 646.135
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 27,
     "wall_s": 843.378
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 39,
     "wall_s": 693.167
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 14,
     "wall_s": 510.01
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 15,
     "wall_s": 1406.739
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 18,
     "wall_s": 642.959
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 19,
     "wall_s": 1572.156
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 25,
     "wall_s": 488.308
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 19,
     "wall_s": 702.9
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 25,
     "wall_s": 771.821
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 31,
     "wall_s": 703.237
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 25,
     "wall_s": 550.692
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 13,
     "wall_s": 759.359
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 20,
     "wall_s": 728.802
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 42,
     "wall_s": 721.285
    }
   ]
  },
  "I1": {
   "read_catches": {
    "C_from_rows": 0,
    "caught_from_rows": 17,
    "holds": true,
    "rows": [
     "injected {\"artefacts_caught\": 4, \"blocking_failures\": 8, \"caught_after_reviewer_passed\": 0, \"check\": 1, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"units\", \"no_review\": 0, \"reviewer_had_failed\": 8, \"reviewer_had_passed\": 0}",
     "injected {\"artefacts_caught\": 1, \"blocking_failures\": 2, \"caught_after_reviewer_passed\": 0, \"check\": 2, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"magnitude\", \"no_review\": 0, \"reviewer_had_failed\": 2, \"reviewer_had_passed\": 0}",
     "injected {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 3, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"equilibrium\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "injected {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 4, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"power\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "injected {\"artefacts_caught\": 2, \"blocking_failures\": 4, \"caught_after_reviewer_passed\": 0, \"check\": 5, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"conservation\", \"no_review\": 0, \"reviewer_had_failed\": 4, \"reviewer_had_passed\": 0}",
     "injected {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 6, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"thermal\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "injected {\"artefacts_caught\": 11, \"blocking_failures\": 12, \"caught_after_reviewer_passed\": 0, \"check\": 7, \"checks_run\": 40, \"gate_mode\": \"observe\", \"name\": \"propagation\", \"no_review\": 1, \"reviewer_had_failed\": 11, \"reviewer_had_passed\": 0}",
     "injected {\"artefacts_caught\": 17, \"blocking_failures\": 26, \"caught_after_reviewer_passed\": 0, \"check\": null, \"checks_run\": 520, \"gate_mode\": \"observe\", \"name\": \"all\", \"no_review\": 1, \"reviewer_had_failed\": 25, \"reviewer_had_passed\": 0}",
     "controls {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 1, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"units\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "controls {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 2, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"magnitude\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "controls {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 3, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"equilibrium\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "controls {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 4, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"power\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "controls {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 5, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"conservation\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "controls {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 6, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"thermal\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "controls {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 7, \"checks_run\": 40, \"gate_mode\": \"observe\", \"name\": \"propagation\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "controls {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": null, \"checks_run\": 520, \"gate_mode\": \"observe\", \"name\": \"all\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}"
    ]
   },
   "regate_differ": 0,
   "rubric_lines": 76,
   "sessions": [
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 45,
     "wall_s": 899.078
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 17,
     "wall_s": 570.038
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 27,
     "wall_s": 432.875
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 18,
     "wall_s": 914.473
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 14,
     "wall_s": 575.511
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 31,
     "wall_s": 683.401
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 42,
     "wall_s": 705.343
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 19,
     "wall_s": 796.37
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 16,
     "wall_s": 606.951
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 11,
     "wall_s": 483.973
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 18,
     "wall_s": 686.977
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 12,
     "wall_s": 630.116
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 30,
     "wall_s": 680.885
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 16,
     "wall_s": 638.183
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 19,
     "wall_s": 566.075
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 19,
     "wall_s": 1234.929
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 17,
     "wall_s": 723.515
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 19,
     "wall_s": 1324.818
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 14,
     "wall_s": 799.035
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 13,
     "wall_s": 608.345
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 19,
     "wall_s": 436.755
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 12,
     "wall_s": 453.411
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 18,
     "wall_s": 558.515
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 20,
     "wall_s": 724.882
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 18,
     "wall_s": 836.779
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 12,
     "wall_s": 706.318
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 15,
     "wall_s": 1437.34
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 42,
     "wall_s": 681.619
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 13,
     "wall_s": 353.696
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 17,
     "wall_s": 715.953
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 42,
     "wall_s": 661.969
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 14,
     "wall_s": 717.994
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 17,
     "wall_s": 741.935
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 13,
     "wall_s": 543.428
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 20,
     "wall_s": 347.433
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 17,
     "wall_s": 653.632
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 14,
     "wall_s": 506.646
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 14,
     "wall_s": 597.198
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 13,
     "wall_s": 636.167
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 23,
     "wall_s": 862.094
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 12,
     "wall_s": 517.878
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 20,
     "wall_s": 824.911
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 13,
     "wall_s": 624.974
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 33,
     "wall_s": 648.309
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 12,
     "wall_s": 395.933
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 35,
     "wall_s": 656.525
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 13,
     "wall_s": 419.887
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 9,
     "wall_s": 444.575
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 13,
     "wall_s": 604.641
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 17,
     "wall_s": 578.129
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 18,
     "wall_s": 637.055
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 13,
     "wall_s": 598.316
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 15,
     "wall_s": 726.738
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 17,
     "wall_s": 558.152
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 21,
     "wall_s": 979.375
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 12,
     "wall_s": 545.564
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 14,
     "wall_s": 1279.325
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 11,
     "wall_s": 517.421
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 20,
     "wall_s": 802.548
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 16,
     "wall_s": 652.038
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 14,
     "wall_s": 330.515
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 37,
     "wall_s": 607.299
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 39,
     "wall_s": 505.236
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 13,
     "wall_s": 1264.568
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 24,
     "wall_s": 540.578
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 28,
     "wall_s": 667.623
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 14,
     "wall_s": 678.844
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 16,
     "wall_s": 593.173
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 13,
     "wall_s": 551.546
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 13,
     "wall_s": 653.889
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 33,
     "wall_s": 501.259
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 14,
     "wall_s": 704.574
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 13,
     "wall_s": 548.203
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 30,
     "wall_s": 811.452
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 21,
     "wall_s": 912.742
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 23,
     "wall_s": 852.248
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 30,
     "wall_s": 843.196
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 12,
     "wall_s": 617.375
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 22,
     "wall_s": 682.819
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 46,
     "wall_s": 805.286
    }
   ]
  },
  "I2": {
   "read_catches": {
    "C_from_rows": 0,
    "caught_from_rows": 17,
    "holds": true,
    "rows": [
     "injected {\"artefacts_caught\": 4, \"blocking_failures\": 8, \"caught_after_reviewer_passed\": 0, \"check\": 1, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"units\", \"no_review\": 0, \"reviewer_had_failed\": 8, \"reviewer_had_passed\": 0}",
     "injected {\"artefacts_caught\": 1, \"blocking_failures\": 2, \"caught_after_reviewer_passed\": 0, \"check\": 2, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"magnitude\", \"no_review\": 0, \"reviewer_had_failed\": 2, \"reviewer_had_passed\": 0}",
     "injected {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 3, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"equilibrium\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "injected {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 4, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"power\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "injected {\"artefacts_caught\": 2, \"blocking_failures\": 4, \"caught_after_reviewer_passed\": 0, \"check\": 5, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"conservation\", \"no_review\": 0, \"reviewer_had_failed\": 4, \"reviewer_had_passed\": 0}",
     "injected {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 6, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"thermal\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "injected {\"artefacts_caught\": 11, \"blocking_failures\": 12, \"caught_after_reviewer_passed\": 0, \"check\": 7, \"checks_run\": 40, \"gate_mode\": \"observe\", \"name\": \"propagation\", \"no_review\": 0, \"reviewer_had_failed\": 12, \"reviewer_had_passed\": 0}",
     "injected {\"artefacts_caught\": 17, \"blocking_failures\": 26, \"caught_after_reviewer_passed\": 0, \"check\": null, \"checks_run\": 520, \"gate_mode\": \"observe\", \"name\": \"all\", \"no_review\": 0, \"reviewer_had_failed\": 26, \"reviewer_had_passed\": 0}",
     "controls {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 1, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"units\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "controls {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 2, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"magnitude\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "controls {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 3, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"equilibrium\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "controls {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 4, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"power\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "controls {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 5, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"conservation\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "controls {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 6, \"checks_run\": 80, \"gate_mode\": \"observe\", \"name\": \"thermal\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "controls {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": 7, \"checks_run\": 40, \"gate_mode\": \"observe\", \"name\": \"propagation\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}",
     "controls {\"artefacts_caught\": 0, \"blocking_failures\": 0, \"caught_after_reviewer_passed\": 0, \"check\": null, \"checks_run\": 520, \"gate_mode\": \"observe\", \"name\": \"all\", \"no_review\": 0, \"reviewer_had_failed\": 0, \"reviewer_had_passed\": 0}"
    ]
   },
   "regate_differ": 0,
   "rubric_lines": 80,
   "sessions": [
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 11,
     "wall_s": 555.375
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 14,
     "wall_s": 581.87
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 16,
     "wall_s": 568.93
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 15,
     "wall_s": 900.762
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 14,
     "wall_s": 735.218
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 23,
     "wall_s": 1356.174
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 12,
     "wall_s": 551.544
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 13,
     "wall_s": 593.795
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 21,
     "wall_s": 525.44
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 20,
     "wall_s": 631.706
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 33,
     "wall_s": 1307.076
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 18,
     "wall_s": 701.933
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 16,
     "wall_s": 530.075
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 13,
     "wall_s": 658.146
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 21,
     "wall_s": 608.011
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 19,
     "wall_s": 619.741
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 15,
     "wall_s": 749.777
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 18,
     "wall_s": 1363.831
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 14,
     "wall_s": 792.266
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 13,
     "wall_s": 578.37
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 27,
     "wall_s": 700.497
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 20,
     "wall_s": 475.19
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 15,
     "wall_s": 489.165
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 20,
     "wall_s": 727.101
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 15,
     "wall_s": 1390.749
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 11,
     "wall_s": 560.443
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 34,
     "wall_s": 716.406
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 22,
     "wall_s": 800.179
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 23,
     "wall_s": 574.437
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 13,
     "wall_s": 634.831
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 16,
     "wall_s": 570.495
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 25,
     "wall_s": 692.3
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 24,
     "wall_s": 554.443
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 19,
     "wall_s": 734.036
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 19,
     "wall_s": 363.131
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 17,
     "wall_s": 718.802
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 17,
     "wall_s": 515.426
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 14,
     "wall_s": 593.551
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 14,
     "wall_s": 587.471
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 21,
     "wall_s": 694.233
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 13,
     "wall_s": 478.828
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 17,
     "wall_s": 627.399
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 19,
     "wall_s": 692.449
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 35,
     "wall_s": 881.246
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 17,
     "wall_s": 483.87
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 20,
     "wall_s": 705.835
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 10,
     "wall_s": 461.849
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 22,
     "wall_s": 504.82
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 14,
     "wall_s": 548.096
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 16,
     "wall_s": 555.516
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 17,
     "wall_s": 810.165
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 14,
     "wall_s": 595.873
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 16,
     "wall_s": 656.468
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 14,
     "wall_s": 720.504
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 22,
     "wall_s": 934.92
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 13,
     "wall_s": 616.109
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 23,
     "wall_s": 820.116
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 12,
     "wall_s": 560.225
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 17,
     "wall_s": 635.934
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 43,
     "wall_s": 676.513
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 18,
     "wall_s": 409.029
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 42,
     "wall_s": 668.582
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 29,
     "wall_s": 840.845
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 22,
     "wall_s": 1271.12
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 23,
     "wall_s": 651.62
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 13,
     "wall_s": 591.552
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 19,
     "wall_s": 780.587
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 22,
     "wall_s": 998.323
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 12,
     "wall_s": 649.686
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 19,
     "wall_s": 1557.303
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 19,
     "wall_s": 506.423
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 14,
     "wall_s": 730.324
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 12,
     "wall_s": 477.95
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 13,
     "wall_s": 785.456
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 35,
     "wall_s": 778.017
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 22,
     "wall_s": 688.987
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 12,
     "wall_s": 615.918
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 28,
     "wall_s": 735.56
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 16,
     "wall_s": 498.166
    },
    {
     "at_turn_bound": false,
     "at_wall_bound": false,
     "stream": true,
     "turns": 40,
     "wall_s": 697.145
    }
   ]
  }
 },
 "floor": true,
 "one_round_form": false,
 "per_run": {
  "F1": {
   "A": 0,
   "C": 0,
   "kill": true,
   "listed_not_approved_without_a_verdict": [],
   "per_artefact": [
    {
     "approved": false,
     "artefact": "a01",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "EA-9",
      "EH-6",
      "EP-4",
      "EP-5",
      "ES-14",
      "ES-34"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "EH-1",
      "EH-6",
      "EP-4",
      "EP-5",
      "ES-1",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21"
     ],
     "class": "propagation",
     "deciding": [
      "ES-34"
     ],
     "error_items": [
      "ES-34"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 115,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 102
    },
    {
     "approved": false,
     "artefact": "a02",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "EA-9",
      "EP-5",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21",
      "ES-34"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "EP-5",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-5"
     ],
     "class": "propagation",
     "deciding": [
      "ES-34"
     ],
     "error_items": [
      "ES-34"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 114,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 101
    },
    {
     "approved": false,
     "artefact": "a03",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "MA-10",
      "MS-28",
      "MS-3",
      "MS-5"
     ],
     "cited_by_twin_review": [
      "MA-10",
      "MS-28"
     ],
     "class": "propagation",
     "deciding": [
      "MS-5"
     ],
     "error_items": [
      "MS-5"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 96,
     "review": "fail",
     "review_cause": null,
     "role": "mechanical",
     "twin_gate_failing_records": 0,
     "twin_records": 97,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 83
    },
    {
     "approved": false,
     "artefact": "a04",
     "caught": false,
     "cited_at_all": true,
     "cited_by_review": [
      "MA-10",
      "MS-1",
      "MS-2",
      "MS-28",
      "MS-3"
     ],
     "cited_by_twin_review": [
      "MA-10",
      "MS-28"
     ],
     "class": "unit",
     "deciding": [
      "MS-2"
     ],
     "error_items": [
      "MS-2"
     ],
     "expected_check": "units",
     "gate_blocking": [],
     "named": true,
     "records": 97,
     "review": "fail",
     "review_cause": null,
     "role": "mechanical",
     "twin_gate_failing_records": 0,
     "twin_records": 97,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 84
    },
    {
     "approved": false,
     "artefact": "a05",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "MA-10",
      "MH-2",
      "MH-5",
      "MP-10",
      "MS-26",
      "MS-28",
      "MS-3",
      "MS-5"
     ],
     "cited_by_twin_review": [
      "MA-10",
      "MS-28"
     ],
     "class": "equilibrium",
     "deciding": [],
     "error_items": [
      "MS-4"
     ],
     "expected_check": "equilibrium",
     "gate_blocking": [],
     "named": false,
     "records": 97,
     "review": "fail",
     "review_cause": null,
     "role": "mechanical",
     "twin_gate_failing_records": 0,
     "twin_records": 97,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": false,
     "unchecked_records": 84
    },
    {
     "approved": false,
     "artefact": "a06",
     "caught": false,
     "cited_at_all": true,
     "cited_by_review": [
      "MA-10",
      "MH-5",
      "MS-1",
      "MS-2",
      "MS-28",
      "MS-3"
     ],
     "cited_by_twin_review": [
      "MA-10",
      "MS-28",
      "MS-6"
     ],
     "class": "unit",
     "deciding": [
      "MS-2"
     ],
     "error_items": [
      "MS-2"
     ],
     "expected_check": "units",
     "gate_blocking": [],
     "named": true,
     "records": 97,
     "review": "fail",
     "review_cause": null,
     "role": "mechanical",
     "twin_gate_failing_records": 0,
     "twin_records": 97,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 84
    },
    {
     "approved": false,
     "artefact": "a07",
     "caught": false,
     "cited_at_all": true,
     "cited_by_review": [
      "MA-10",
      "MH-2",
      "MH-5",
      "MS-1",
      "MS-28",
      "MS-3",
      "MS-4"
     ],
     "cited_by_twin_review": [
      "MA-10",
      "MS-28"
     ],
     "class": "equilibrium",
     "deciding": [
      "MS-4"
     ],
     "error_items": [
      "MS-4"
     ],
     "expected_check": "equilibrium",
     "gate_blocking": [],
     "named": true,
     "records": 116,
     "review": "fail",
     "review_cause": null,
     "role": "mechanical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": false,
     "unchecked_records": 103
    },
    {
     "approved": false,
     "artefact": "a08",
     "caught": false,
     "cited_at_all": null,
     "cited_by_review": [
      "EA-9",
      "EH-6",
      "EP-4",
      "EP-5",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-32"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "EH-1",
      "EP-4",
      "EP-5",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21"
     ],
     "class": "equilibrium",
     "deciding": [],
     "error_items": [],
     "expected_check": "equilibrium",
     "gate_blocking": [],
     "named": null,
     "records": 116,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": false,
     "unchecked_records": 103
    },
    {
     "approved": false,
     "artefact": "a09",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "MA-10",
      "MH-2",
      "MS-1",
      "MS-28",
      "MS-3",
      "MS-5"
     ],
     "cited_by_twin_review": [
      "MA-10",
      "MH-1",
      "MS-28"
     ],
     "class": "equilibrium",
     "deciding": [],
     "error_items": [
      "MS-4"
     ],
     "expected_check": "equilibrium",
     "gate_blocking": [],
     "named": false,
     "records": 116,
     "review": "fail",
     "review_cause": null,
     "role": "mechanical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": false,
     "unchecked_records": 103
    },
    {
     "approved": false,
     "artefact": "a10",
     "caught": true,
     "cited_at_all": false,
     "cited_by_review": [
      "EA-9",
      "ES-14",
      "ES-15",
      "ES-16"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "EH-1",
      "EP-4",
      "EP-5",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21"
     ],
     "class": "equilibrium",
     "deciding": [],
     "error_items": [
      "ES-7",
      "ES-9",
      "ES-33"
     ],
     "expected_check": "conservation",
     "gate_blocking": [
      "conservation"
     ],
     "named": false,
     "records": 112,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 99
    },
    {
     "approved": false,
     "artefact": "a11",
     "caught": false,
     "cited_at_all": true,
     "cited_by_review": [
      "MA-10",
      "MH-2",
      "MS-1",
      "MS-3",
      "MS-4",
      "MS-5"
     ],
     "cited_by_twin_review": [
      "MA-10",
      "MS-28"
     ],
     "class": "equilibrium",
     "deciding": [
      "MS-4"
     ],
     "error_items": [
      "MS-4"
     ],
     "expected_check": "equilibrium",
     "gate_blocking": [],
     "named": true,
     "records": 116,
     "review": "fail",
     "review_cause": null,
     "role": "mechanical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": false,
     "unchecked_records": 103
    },
    {
     "approved": false,
     "artefact": "a12",
     "caught": false,
     "cited_at_all": null,
     "cited_by_review": [
      "EA-9",
      "EH-1",
      "EP-4",
      "EP-5",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21",
      "ES-31"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "EH-1",
      "EH-6",
      "EP-4",
      "EP-5",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21"
     ],
     "class": "equilibrium",
     "deciding": [],
     "error_items": [],
     "expected_check": "equilibrium",
     "gate_blocking": [],
     "named": null,
     "records": 116,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": false,
     "unchecked_records": 103
    },
    {
     "approved": false,
     "artefact": "a13",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "MA-10",
      "MS-1",
      "MS-2",
      "MS-26",
      "MS-28",
      "MS-3",
      "MS-5",
      "MS-6"
     ],
     "cited_by_twin_review": [
      "MA-10",
      "MS-28"
     ],
     "class": "equilibrium",
     "deciding": [
      "MS-26",
      "MS-3"
     ],
     "error_items": [
      "MS-3",
      "MS-26"
     ],
     "expected_check": "conservation",
     "gate_blocking": [
      "conservation"
     ],
     "named": true,
     "records": 112,
     "review": "fail",
     "review_cause": null,
     "role": "mechanical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 99
    },
    {
     "approved": false,
     "artefact": "a14",
     "caught": false,
     "cited_at_all": null,
     "cited_by_review": [
      "EA-9",
      "EH-6",
      "EP-4",
      "EP-5",
      "ES-1",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "EH-1",
      "EH-6",
      "EP-4",
      "EP-5",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21"
     ],
     "class": "equilibrium",
     "deciding": [],
     "error_items": [],
     "expected_check": "equilibrium",
     "gate_blocking": [],
     "named": null,
     "records": 116,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": false,
     "unchecked_records": 103
    },
    {
     "approved": false,
     "artefact": "a15",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "EA-9",
      "EH-5",
      "EP-4",
      "EP-5",
      "ES-10",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-19",
      "ES-21",
      "ES-27",
      "ES-28",
      "ES-33",
      "ES-34",
      "ES-35",
      "ES-5",
      "ES-6",
      "ES-7"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "EH-6",
      "EP-4",
      "EP-5",
      "ES-10",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-17",
      "ES-21",
      "ES-27",
      "ES-28",
      "ES-5",
      "ES-6",
      "ES-7"
     ],
     "class": "propagation",
     "deciding": [
      "ES-34"
     ],
     "error_items": [
      "ES-34"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 90,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 92,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 76
    },
    {
     "approved": false,
     "artefact": "a16",
     "caught": false,
     "cited_at_all": null,
     "cited_by_review": [
      "EA-9",
      "EH-6",
      "EP-4",
      "EP-5",
      "ES-10",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21",
      "ES-27",
      "ES-28",
      "ES-32",
      "ES-7"
     ],
     "cited_by_twin_review": [],
     "class": "equilibrium",
     "deciding": [],
     "error_items": [],
     "expected_check": "equilibrium",
     "gate_blocking": [],
     "named": null,
     "records": 118,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 118,
     "twin_review": "review_unavailable",
     "twin_review_cause": "invalid_verdict",
     "unchecked_on_expected_check": false,
     "unchecked_records": 105
    },
    {
     "approved": false,
     "artefact": "a17",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "EA-9",
      "ES-1",
      "ES-34"
     ],
     "cited_by_twin_review": [],
     "class": "propagation",
     "deciding": [
      "ES-34"
     ],
     "error_items": [
      "ES-34"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 83,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 84,
     "twin_review": "pass",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 70
    },
    {
     "approved": false,
     "artefact": "a18",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "AC-9",
      "DS-30",
      "DS-4"
     ],
     "cited_by_twin_review": [
      "AC-1",
      "AC-9",
      "DS-4"
     ],
     "class": "propagation",
     "deciding": [
      "DS-30"
     ],
     "error_items": [
      "DS-30"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 82,
     "review": "fail",
     "review_cause": null,
     "role": "firmware",
     "twin_gate_failing_records": 0,
     "twin_records": 84,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 69
    },
    {
     "approved": false,
     "artefact": "a19",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "A7",
      "D28"
     ],
     "cited_by_twin_review": [],
     "class": "propagation",
     "deciding": [
      "D28"
     ],
     "error_items": [
      "D28"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 72,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 78,
     "twin_review": "blocked",
     "twin_review_cause": "blocking_spec_defect",
     "unchecked_on_expected_check": true,
     "unchecked_records": 59
    },
    {
     "approved": false,
     "artefact": "a20",
     "caught": true,
     "cited_at_all": false,
     "cited_by_review": [
      "DS-1",
      "DS-29",
      "DS-4",
      "DS-5"
     ],
     "cited_by_twin_review": [
      "DS-1",
      "DS-4",
      "DS-5"
     ],
     "class": "unit",
     "deciding": [],
     "error_items": [
      "DS-27"
     ],
     "expected_check": "units",
     "gate_blocking": [
      "units"
     ],
     "named": false,
     "records": 86,
     "review": "fail",
     "review_cause": null,
     "role": "firmware",
     "twin_gate_failing_records": 0,
     "twin_records": 86,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 73
    },
    {
     "approved": false,
     "artefact": "a21",
     "caught": false,
     "cited_at_all": true,
     "cited_by_review": [
      "A7",
      "D10",
      "D11",
      "D13",
      "D17",
      "D23",
      "D25",
      "D28",
      "D29",
      "D30",
      "D33",
      "D6",
      "D7",
      "D8",
      "R1",
      "S5"
     ],
     "cited_by_twin_review": [
      "D10",
      "D11",
      "D13",
      "D17",
      "D23",
      "D29",
      "D3",
      "D30",
      "D32",
      "D33",
      "D4",
      "D5",
      "D6",
      "D7",
      "D8",
      "D9",
      "R1",
      "S2",
      "S4",
      "S5"
     ],
     "class": "unit",
     "deciding": [
      "D25"
     ],
     "error_items": [
      "D25",
      "D26"
     ],
     "expected_check": "units",
     "gate_blocking": [],
     "named": true,
     "records": 86,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 86,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 73
    },
    {
     "approved": false,
     "artefact": "a22",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D1",
      "D10",
      "D11",
      "D13",
      "D14",
      "D17",
      "D22",
      "D23",
      "D24",
      "D29",
      "D3",
      "D30",
      "D33",
      "D4",
      "D5",
      "D6",
      "D7",
      "D8",
      "D9",
      "R1",
      "R9",
      "S2",
      "S4",
      "S5"
     ],
     "cited_by_twin_review": [
      "A7",
      "D13",
      "D17",
      "D21",
      "D22",
      "D23",
      "D29",
      "D30",
      "D33",
      "D6",
      "R1",
      "S2",
      "S5"
     ],
     "class": "magnitude",
     "deciding": [],
     "error_items": [
      "D25",
      "D27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [],
     "named": false,
     "records": 86,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 86,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 73
    },
    {
     "approved": false,
     "artefact": "a23",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D10",
      "D11",
      "D13",
      "D16",
      "D17",
      "D22",
      "D23",
      "D24",
      "D29",
      "D3",
      "D30",
      "D32",
      "D33",
      "D4",
      "D5",
      "D6",
      "D7",
      "D8",
      "D9",
      "R1",
      "R9",
      "S2",
      "S5"
     ],
     "cited_by_twin_review": [
      "S5"
     ],
     "class": "unit",
     "deciding": [],
     "error_items": [
      "D25",
      "D26"
     ],
     "expected_check": "units",
     "gate_blocking": [],
     "named": false,
     "records": 91,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 91,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 78
    },
    {
     "approved": false,
     "artefact": "a24",
     "caught": true,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D13",
      "D17",
      "D23",
      "D29",
      "D30",
      "D33",
      "D6",
      "R1",
      "R9",
      "S2",
      "S4",
      "S5"
     ],
     "cited_by_twin_review": [
      "A7",
      "D1",
      "D10",
      "D11",
      "D13",
      "D14",
      "D17",
      "D22",
      "D23",
      "D24",
      "D29",
      "D3",
      "D30",
      "D33",
      "D4",
      "D5",
      "D6",
      "D7",
      "D8",
      "D9",
      "R1",
      "S2",
      "S4",
      "S5"
     ],
     "class": "magnitude",
     "deciding": [],
     "error_items": [
      "D25",
      "D27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [
      "magnitude"
     ],
     "named": false,
     "records": 91,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 91,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 78
    },
    {
     "approved": false,
     "artefact": "a25",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "A7",
      "D17",
      "D22",
      "D23",
      "D25",
      "D29",
      "D30",
      "D33",
      "D6",
      "R1",
      "R9",
      "S4"
     ],
     "cited_by_twin_review": [
      "A7",
      "D10",
      "D11",
      "D13",
      "D14",
      "D17",
      "D21",
      "D22",
      "D23",
      "D24",
      "D29",
      "D3",
      "D30",
      "D32",
      "D33",
      "D4",
      "D5",
      "D6",
      "D7",
      "D8",
      "D9",
      "R1",
      "R2",
      "S2",
      "S4",
      "S5"
     ],
     "class": "unit",
     "deciding": [
      "D25"
     ],
     "error_items": [
      "D25",
      "D26"
     ],
     "expected_check": "units",
     "gate_blocking": [
      "units"
     ],
     "named": true,
     "records": 79,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 79,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 66
    },
    {
     "approved": false,
     "artefact": "a26",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "A7",
      "D10",
      "D11",
      "D13",
      "D14",
      "D17",
      "D23",
      "D24",
      "D28",
      "D29",
      "D3",
      "D30",
      "D33",
      "D4",
      "D5",
      "D6",
      "D7",
      "D8",
      "D9",
      "R1",
      "R2",
      "S2",
      "S4",
      "S5"
     ],
     "cited_by_twin_review": [
      "A7",
      "D10",
      "D11",
      "D13",
      "D14",
      "D17",
      "D21",
      "D23",
      "D24",
      "D29",
      "D3",
      "D30",
      "D33",
      "D4",
      "D5",
      "D6",
      "D7",
      "D8",
      "D9",
      "R1",
      "R2",
      "S2",
      "S4"
     ],
     "class": "propagation",
     "deciding": [
      "D28"
     ],
     "error_items": [
      "D28"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 76,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 79,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 63
    },
    {
     "approved": false,
     "artefact": "a27",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D1",
      "D10",
      "D11",
      "D12",
      "D13",
      "D14",
      "D17",
      "D18",
      "D21",
      "D22",
      "D23",
      "D24",
      "D29",
      "D3",
      "D30",
      "D32",
      "D33",
      "D4",
      "D5",
      "D6",
      "D7",
      "D8",
      "D9",
      "R1",
      "R2",
      "S2",
      "S4",
      "S5"
     ],
     "cited_by_twin_review": [
      "A7",
      "D1",
      "D10",
      "D11",
      "D12",
      "D14",
      "D16",
      "D17",
      "D2",
      "D22",
      "D23",
      "D24",
      "D29",
      "D3",
      "D30",
      "D33",
      "D4",
      "D5",
      "D6",
      "D7",
      "D8",
      "D9",
      "S2",
      "S4"
     ],
     "class": "magnitude",
     "deciding": [],
     "error_items": [
      "D25",
      "D27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [],
     "named": false,
     "records": 79,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 79,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 66
    },
    {
     "approved": false,
     "artefact": "a28",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D1",
      "D17",
      "D29",
      "D30",
      "D32",
      "D6",
      "D8",
      "D9",
      "R1",
      "R2",
      "S5"
     ],
     "cited_by_twin_review": [
      "A7",
      "D1",
      "D10",
      "D11",
      "D12",
      "D13",
      "D14",
      "D17",
      "D23",
      "D24",
      "D27",
      "D29",
      "D30",
      "D33",
      "D6",
      "D7",
      "D8",
      "D9",
      "R1",
      "S2",
      "S4",
      "S5"
     ],
     "class": "magnitude",
     "deciding": [],
     "error_items": [
      "D25",
      "D27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [],
     "named": false,
     "records": 79,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 79,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 66
    },
    {
     "approved": false,
     "artefact": "a29",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "EA-9",
      "EH-3",
      "EP-3",
      "ES-1",
      "ES-19",
      "ES-21",
      "ES-3",
      "ES-31",
      "ES-32",
      "ES-34",
      "ES-35",
      "ES-4",
      "ES-7",
      "ES-8"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "EH-3",
      "EP-3",
      "ES-1",
      "ES-3",
      "ES-4"
     ],
     "class": "unit",
     "deciding": [
      "ES-31",
      "ES-32"
     ],
     "error_items": [
      "ES-31",
      "ES-32"
     ],
     "expected_check": "units",
     "gate_blocking": [
      "units",
      "propagation"
     ],
     "named": true,
     "records": 78,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 79,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 65
    },
    {
     "approved": false,
     "artefact": "a30",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "MA-10",
      "MH-8",
      "MS-3",
      "MS-5"
     ],
     "cited_by_twin_review": [
      "MA-10",
      "MS-30"
     ],
     "class": "propagation",
     "deciding": [
      "MS-5"
     ],
     "error_items": [
      "MS-5"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 79,
     "review": "fail",
     "review_cause": null,
     "role": "mechanical",
     "twin_gate_failing_records": 0,
     "twin_records": 81,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": false,
     "unchecked_records": 66
    },
    {
     "approved": false,
     "artefact": "a31",
     "caught": false,
     "cited_at_all": true,
     "cited_by_review": [
      "AC-9",
      "DS-27",
      "RH-2"
     ],
     "cited_by_twin_review": [
      "AC-9"
     ],
     "class": "magnitude",
     "deciding": [
      "DS-27"
     ],
     "error_items": [
      "DS-27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [],
     "named": true,
     "records": 72,
     "review": "fail",
     "review_cause": null,
     "role": "firmware",
     "twin_gate_failing_records": 0,
     "twin_records": 72,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 59
    },
    {
     "approved": false,
     "artefact": "a32",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D28",
      "R9",
      "S5"
     ],
     "cited_by_twin_review": [],
     "class": "magnitude",
     "deciding": [],
     "error_items": [
      "D25",
      "D27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [],
     "named": false,
     "records": 75,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 75,
     "twin_review": "blocked",
     "twin_review_cause": "blocking_spec_defect",
     "unchecked_on_expected_check": true,
     "unchecked_records": 62
    },
    {
     "approved": false,
     "artefact": "a33",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D1",
      "D10",
      "D11",
      "D13",
      "D15",
      "D17",
      "D22",
      "D23",
      "D24",
      "D28",
      "D29",
      "D30",
      "D33",
      "D6",
      "D7",
      "D8",
      "D9",
      "R9",
      "S2",
      "S4",
      "S5"
     ],
     "cited_by_twin_review": [
      "A7",
      "D1",
      "D17",
      "D23",
      "D29",
      "D30",
      "D33",
      "D6",
      "D8",
      "D9",
      "S2",
      "S4",
      "S5"
     ],
     "class": "magnitude",
     "deciding": [],
     "error_items": [
      "D25",
      "D27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [],
     "named": false,
     "records": 86,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 86,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 73
    },
    {
     "approved": false,
     "artefact": "a34",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D13",
      "D14",
      "D15",
      "D17",
      "D23",
      "D28",
      "D30",
      "D33",
      "D6",
      "D9",
      "R1",
      "R9",
      "S2",
      "S4",
      "S5"
     ],
     "cited_by_twin_review": [
      "A7",
      "D17",
      "D22",
      "D23",
      "D29",
      "D30",
      "D33",
      "D6",
      "R1",
      "S2",
      "S4",
      "S5"
     ],
     "class": "magnitude",
     "deciding": [],
     "error_items": [
      "D25",
      "D27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [],
     "named": false,
     "records": 86,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 86,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 73
    },
    {
     "approved": false,
     "artefact": "a35",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "EA-9",
      "EP-4",
      "EP-5",
      "ES-10",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21",
      "ES-28",
      "ES-34",
      "ES-7"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "EH-1",
      "EP-4",
      "EP-5",
      "ES-10",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21",
      "ES-33",
      "ES-5",
      "ES-7"
     ],
     "class": "propagation",
     "deciding": [
      "ES-34"
     ],
     "error_items": [
      "ES-34"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 116,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 118,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 103
    },
    {
     "approved": false,
     "artefact": "a36",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "A7",
      "D25",
      "D30"
     ],
     "cited_by_twin_review": [],
     "class": "unit",
     "deciding": [
      "D25"
     ],
     "error_items": [
      "D25",
      "D26"
     ],
     "expected_check": "units",
     "gate_blocking": [
      "units"
     ],
     "named": true,
     "records": 86,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 86,
     "twin_review": "blocked",
     "twin_review_cause": "blocking_spec_defect",
     "unchecked_on_expected_check": true,
     "unchecked_records": 73
    },
    {
     "approved": false,
     "artefact": "a37",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D10",
      "D11",
      "D13",
      "D17",
      "D23",
      "D24",
      "D29",
      "D3",
      "D30",
      "D33",
      "D4",
      "D5",
      "D6",
      "D7",
      "D8",
      "D9",
      "R1",
      "R9",
      "S2",
      "S4",
      "S5"
     ],
     "cited_by_twin_review": [
      "A7",
      "D1",
      "D10",
      "D11",
      "D13",
      "D14",
      "D17",
      "D21",
      "D22",
      "D23",
      "D24",
      "D29",
      "D30",
      "D32",
      "D33",
      "D4",
      "D6",
      "D7",
      "D8",
      "D9",
      "S2",
      "S4",
      "S5"
     ],
     "class": "magnitude",
     "deciding": [],
     "error_items": [
      "D25",
      "D27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [],
     "named": false,
     "records": 79,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 79,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 66
    },
    {
     "approved": false,
     "artefact": "a38",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D28",
      "R7"
     ],
     "cited_by_twin_review": [],
     "class": "magnitude",
     "deciding": [],
     "error_items": [
      "D25",
      "D27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [],
     "named": false,
     "records": 75,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 75,
     "twin_review": "blocked",
     "twin_review_cause": "blocking_spec_defect",
     "unchecked_on_expected_check": true,
     "unchecked_records": 62
    },
    {
     "approved": false,
     "artefact": "a39",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "R9"
     ],
     "cited_by_twin_review": [],
     "class": "unit",
     "deciding": [],
     "error_items": [
      "D25",
      "D26"
     ],
     "expected_check": "units",
     "gate_blocking": [],
     "named": false,
     "records": 75,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 75,
     "twin_review": "blocked",
     "twin_review_cause": "blocking_spec_defect",
     "unchecked_on_expected_check": true,
     "unchecked_records": 62
    },
    {
     "approved": false,
     "artefact": "a40",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D1",
      "D8",
      "R1",
      "S2",
      "S4",
      "S5"
     ],
     "cited_by_twin_review": [],
     "class": "unit",
     "deciding": [],
     "error_items": [
      "D25",
      "D26"
     ],
     "expected_check": "units",
     "gate_blocking": [],
     "named": false,
     "records": 86,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 86,
     "twin_review": "review_unavailable",
     "twin_review_cause": "invalid_verdict",
     "unchecked_on_expected_check": true,
     "unchecked_records": 73
    }
   ],
   "secondary": {
    "s6_10_named_against_caught": {
     "cited_at_all": 20,
     "named": 20,
     "no_error_item": 4,
     "per_class": {
      "equilibrium": {
       "caught_not_named": 1,
       "named_and_caught": 1,
       "named_not_caught": 2,
       "neither": 2,
       "no_error_item": 4
      },
      "magnitude": {
       "caught_not_named": 1,
       "named_and_caught": 0,
       "named_not_caught": 1,
       "neither": 8,
       "no_error_item": 0
      },
      "propagation": {
       "caught_not_named": 0,
       "named_and_caught": 10,
       "named_not_caught": 0,
       "neither": 0,
       "no_error_item": 0
      },
      "unit": {
       "caught_not_named": 1,
       "named_and_caught": 3,
       "named_not_caught": 3,
       "neither": 3,
       "no_error_item": 0
      }
     },
     "per_role": {
      "control": {
       "caught_not_named": 1,
       "named_and_caught": 4,
       "named_not_caught": 1,
       "neither": 11,
       "no_error_item": 0
      },
      "electrical": {
       "caught_not_named": 1,
       "named_and_caught": 6,
       "named_not_caught": 0,
       "neither": 0,
       "no_error_item": 4
      },
      "firmware": {
       "caught_not_named": 1,
       "named_and_caught": 1,
       "named_not_caught": 1,
       "neither": 0,
       "no_error_item": 0
      },
      "mechanical": {
       "caught_not_named": 0,
       "named_and_caught": 3,
       "named_not_caught": 4,
       "neither": 2,
       "no_error_item": 0
      }
     },
     "without_twin_condition": {
      "per_class": {
       "equilibrium": {
        "caught_not_named": 1,
        "named_and_caught": 1,
        "named_not_caught": 2,
        "neither": 2,
        "no_error_item": 4
       },
       "magnitude": {
        "caught_not_named": 1,
        "named_and_caught": 0,
        "named_not_caught": 1,
        "neither": 8,
        "no_error_item": 0
       },
       "propagation": {
        "caught_not_named": 0,
        "named_and_caught": 10,
        "named_not_caught": 0,
        "neither": 0,
        "no_error_item": 0
       },
       "unit": {
        "caught_not_named": 1,
        "named_and_caught": 3,
        "named_not_caught": 3,
        "neither": 3,
        "no_error_item": 0
       }
      },
      "per_role": {
       "control": {
        "caught_not_named": 1,
        "named_and_caught": 4,
        "named_not_caught": 1,
        "neither": 11,
        "no_error_item": 0
       },
       "electrical": {
        "caught_not_named": 1,
        "named_and_caught": 6,
        "named_not_caught": 0,
        "neither": 0,
        "no_error_item": 4
       },
       "firmware": {
        "caught_not_named": 1,
        "named_and_caught": 1,
        "named_not_caught": 1,
        "neither": 0,
        "no_error_item": 0
       },
       "mechanical": {
        "caught_not_named": 0,
        "named_and_caught": 3,
        "named_not_caught": 4,
        "neither": 2,
        "no_error_item": 0
       }
      }
     }
    },
    "s6_1_per_class": {
     "equilibrium": {
      "A": 0,
      "C": 0,
      "artefacts": 10
     },
     "magnitude": {
      "A": 0,
      "C": 0,
      "artefacts": 10
     },
     "propagation": {
      "A": 0,
      "C": 0,
      "artefacts": 10
     },
     "unit": {
      "A": 0,
      "C": 0,
      "artefacts": 10
     }
    },
    "s6_5_gate_caught_by_review_outcome": {
     "blocked": {
      "artefacts": 0,
      "caught": 0
     },
     "fail": {
      "artefacts": 40,
      "caught": 17
     },
     "pass": {
      "artefacts": 0,
      "caught": 0
     },
     "review_unavailable": {
      "artefacts": 0,
      "caught": 0
     }
    },
    "s6_7_twin_reviews": {
     "of": 40,
     "outcomes": {
      "blocked": 5,
      "fail": 32,
      "pass": 1,
      "review_unavailable": 2
     },
     "refused": 32
    },
    "s6_8_per_role": {
     "control": {
      "A": 0,
      "C": 0,
      "artefacts": 17
     },
     "electrical": {
      "A": 0,
      "C": 0,
      "artefacts": 11
     },
     "firmware": {
      "A": 0,
      "C": 0,
      "artefacts": 3
     },
     "mechanical": {
      "A": 0,
      "C": 0,
      "artefacts": 9
     }
    },
    "s6_9_not_judged_per_role": {
     "control": {
      "artefacts": {
       "blocked": [],
       "review_unavailable": []
      },
      "twins": {
       "blocked": [
        [
         "a19",
         "blocking_spec_defect"
        ],
        [
         "a32",
         "blocking_spec_defect"
        ],
        [
         "a36",
         "blocking_spec_defect"
        ],
        [
         "a38",
         "blocking_spec_defect"
        ],
        [
         "a39",
         "blocking_spec_defect"
        ]
       ],
       "review_unavailable": [
        [
         "a40",
         "invalid_verdict"
        ]
       ]
      }
     },
     "electrical": {
      "artefacts": {
       "blocked": [],
       "review_unavailable": []
      },
      "twins": {
       "blocked": [],
       "review_unavailable": [
        [
         "a16",
         "invalid_verdict"
        ]
       ]
      }
     },
     "firmware": {
      "artefacts": {
       "blocked": [],
       "review_unavailable": []
      },
      "twins": {
       "blocked": [],
       "review_unavailable": []
      }
     },
     "mechanical": {
      "artefacts": {
       "blocked": [],
       "review_unavailable": []
      },
      "twins": {
       "blocked": [],
       "review_unavailable": []
      }
     }
    }
   }
  },
  "F2": {
   "A": 1,
   "C": 0,
   "kill": true,
   "listed_not_approved_without_a_verdict": [],
   "per_artefact": [
    {
     "approved": false,
     "artefact": "a01",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "EA-9",
      "EH-1",
      "EH-6",
      "EP-4",
      "EP-5",
      "ES-1",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21",
      "ES-34"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "EH-1",
      "EH-6",
      "EP-4",
      "EP-5",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21"
     ],
     "class": "propagation",
     "deciding": [
      "ES-34"
     ],
     "error_items": [
      "ES-34"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 115,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 102
    },
    {
     "approved": false,
     "artefact": "a02",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "EA-9",
      "EP-5",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21",
      "ES-34"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "EH-1",
      "EP-4",
      "EP-5",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21"
     ],
     "class": "propagation",
     "deciding": [
      "ES-34"
     ],
     "error_items": [
      "ES-34"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 114,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 101
    },
    {
     "approved": false,
     "artefact": "a03",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "MA-10",
      "MS-28",
      "MS-3",
      "MS-5"
     ],
     "cited_by_twin_review": [
      "MA-10",
      "MS-28"
     ],
     "class": "propagation",
     "deciding": [
      "MS-5"
     ],
     "error_items": [
      "MS-5"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 96,
     "review": "fail",
     "review_cause": null,
     "role": "mechanical",
     "twin_gate_failing_records": 0,
     "twin_records": 97,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 83
    },
    {
     "approved": false,
     "artefact": "a04",
     "caught": false,
     "cited_at_all": true,
     "cited_by_review": [
      "MA-10",
      "MP-8",
      "MS-1",
      "MS-2",
      "MS-24",
      "MS-28",
      "MS-3",
      "MS-5"
     ],
     "cited_by_twin_review": [
      "MA-10",
      "MS-28"
     ],
     "class": "unit",
     "deciding": [
      "MS-2"
     ],
     "error_items": [
      "MS-2"
     ],
     "expected_check": "units",
     "gate_blocking": [],
     "named": true,
     "records": 97,
     "review": "fail",
     "review_cause": null,
     "role": "mechanical",
     "twin_gate_failing_records": 0,
     "twin_records": 97,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 84
    },
    {
     "approved": false,
     "artefact": "a05",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "MA-10",
      "MP-10",
      "MS-26",
      "MS-28",
      "MS-3",
      "MS-5"
     ],
     "cited_by_twin_review": [
      "MA-10",
      "MS-28"
     ],
     "class": "equilibrium",
     "deciding": [],
     "error_items": [
      "MS-4"
     ],
     "expected_check": "equilibrium",
     "gate_blocking": [],
     "named": false,
     "records": 97,
     "review": "fail",
     "review_cause": null,
     "role": "mechanical",
     "twin_gate_failing_records": 0,
     "twin_records": 97,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": false,
     "unchecked_records": 84
    },
    {
     "approved": false,
     "artefact": "a06",
     "caught": false,
     "cited_at_all": true,
     "cited_by_review": [
      "MA-10",
      "MS-1",
      "MS-2",
      "MS-28",
      "MS-3"
     ],
     "cited_by_twin_review": [
      "MA-10",
      "MS-28"
     ],
     "class": "unit",
     "deciding": [
      "MS-2"
     ],
     "error_items": [
      "MS-2"
     ],
     "expected_check": "units",
     "gate_blocking": [],
     "named": true,
     "records": 97,
     "review": "fail",
     "review_cause": null,
     "role": "mechanical",
     "twin_gate_failing_records": 0,
     "twin_records": 97,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 84
    },
    {
     "approved": false,
     "artefact": "a07",
     "caught": false,
     "cited_at_all": true,
     "cited_by_review": [
      "MA-10",
      "MH-2",
      "MH-5",
      "MS-1",
      "MS-28",
      "MS-3",
      "MS-4",
      "MS-6"
     ],
     "cited_by_twin_review": [
      "MA-10",
      "MH-1",
      "MS-28"
     ],
     "class": "equilibrium",
     "deciding": [
      "MS-4"
     ],
     "error_items": [
      "MS-4"
     ],
     "expected_check": "equilibrium",
     "gate_blocking": [],
     "named": true,
     "records": 116,
     "review": "fail",
     "review_cause": null,
     "role": "mechanical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": false,
     "unchecked_records": 103
    },
    {
     "approved": false,
     "artefact": "a08",
     "caught": false,
     "cited_at_all": null,
     "cited_by_review": [
      "EA-9",
      "EH-1",
      "EH-6",
      "EP-4",
      "EP-5",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-32",
      "ES-5"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "EH-1",
      "EH-6",
      "EP-4",
      "EP-5",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21",
      "ES-6"
     ],
     "class": "equilibrium",
     "deciding": [],
     "error_items": [],
     "expected_check": "equilibrium",
     "gate_blocking": [],
     "named": null,
     "records": 116,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": false,
     "unchecked_records": 103
    },
    {
     "approved": false,
     "artefact": "a09",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "MA-10",
      "MH-2",
      "MS-1",
      "MS-28",
      "MS-3",
      "MS-6"
     ],
     "cited_by_twin_review": [
      "MA-10",
      "MS-28"
     ],
     "class": "equilibrium",
     "deciding": [],
     "error_items": [
      "MS-4"
     ],
     "expected_check": "equilibrium",
     "gate_blocking": [],
     "named": false,
     "records": 116,
     "review": "fail",
     "review_cause": null,
     "role": "mechanical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": false,
     "unchecked_records": 103
    },
    {
     "approved": false,
     "artefact": "a10",
     "caught": true,
     "cited_at_all": false,
     "cited_by_review": [
      "EA-9",
      "EH-1",
      "EP-5",
      "ES-1",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21",
      "ES-31",
      "ES-32"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "EH-1",
      "EH-6",
      "EP-4",
      "EP-5",
      "ES-14",
      "ES-15",
      "ES-16"
     ],
     "class": "equilibrium",
     "deciding": [],
     "error_items": [
      "ES-7",
      "ES-9",
      "ES-33"
     ],
     "expected_check": "conservation",
     "gate_blocking": [
      "conservation"
     ],
     "named": false,
     "records": 112,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 99
    },
    {
     "approved": false,
     "artefact": "a11",
     "caught": false,
     "cited_at_all": true,
     "cited_by_review": [
      "MA-10",
      "MH-2",
      "MS-1",
      "MS-28",
      "MS-3",
      "MS-4",
      "MS-6"
     ],
     "cited_by_twin_review": [
      "MA-10",
      "MS-28"
     ],
     "class": "equilibrium",
     "deciding": [
      "MS-4"
     ],
     "error_items": [
      "MS-4"
     ],
     "expected_check": "equilibrium",
     "gate_blocking": [],
     "named": true,
     "records": 116,
     "review": "fail",
     "review_cause": null,
     "role": "mechanical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": false,
     "unchecked_records": 103
    },
    {
     "approved": false,
     "artefact": "a12",
     "caught": false,
     "cited_at_all": null,
     "cited_by_review": [
      "EA-9",
      "EH-1",
      "EH-6",
      "EP-4",
      "EP-5",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "EH-1",
      "EH-6",
      "EP-4",
      "EP-5",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21",
      "ES-5"
     ],
     "class": "equilibrium",
     "deciding": [],
     "error_items": [],
     "expected_check": "equilibrium",
     "gate_blocking": [],
     "named": null,
     "records": 116,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": false,
     "unchecked_records": 103
    },
    {
     "approved": false,
     "artefact": "a13",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "MA-10",
      "MS-26",
      "MS-28",
      "MS-3",
      "MS-5",
      "MS-6"
     ],
     "cited_by_twin_review": [
      "MA-10",
      "MS-28"
     ],
     "class": "equilibrium",
     "deciding": [
      "MS-26",
      "MS-3"
     ],
     "error_items": [
      "MS-3",
      "MS-26"
     ],
     "expected_check": "conservation",
     "gate_blocking": [
      "conservation"
     ],
     "named": true,
     "records": 112,
     "review": "fail",
     "review_cause": null,
     "role": "mechanical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 99
    },
    {
     "approved": false,
     "artefact": "a14",
     "caught": false,
     "cited_at_all": null,
     "cited_by_review": [
      "EA-9",
      "EH-1",
      "EH-6",
      "EP-4",
      "EP-5",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21",
      "ES-32"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "EH-6",
      "EP-4",
      "EP-5",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21"
     ],
     "class": "equilibrium",
     "deciding": [],
     "error_items": [],
     "expected_check": "equilibrium",
     "gate_blocking": [],
     "named": null,
     "records": 116,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": false,
     "unchecked_records": 103
    },
    {
     "approved": false,
     "artefact": "a15",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "EA-9",
      "EH-1",
      "EH-2",
      "EH-3",
      "EH-5",
      "EP-4",
      "EP-5",
      "ES-10",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21",
      "ES-28",
      "ES-34",
      "ES-5",
      "ES-6",
      "ES-7",
      "ES-8",
      "consistency"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "EH-1",
      "EH-3",
      "EH-5",
      "EP-4",
      "EP-5",
      "ES-10",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21",
      "ES-33",
      "ES-5",
      "ES-7"
     ],
     "class": "propagation",
     "deciding": [
      "ES-34"
     ],
     "error_items": [
      "ES-34"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 90,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 92,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 76
    },
    {
     "approved": false,
     "artefact": "a16",
     "caught": false,
     "cited_at_all": null,
     "cited_by_review": [
      "EA-9",
      "EH-1",
      "EH-5",
      "EH-6",
      "EP-4",
      "EP-5",
      "ES-1",
      "ES-10",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-19",
      "ES-20",
      "ES-21",
      "ES-32",
      "ES-35",
      "ES-7"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "EH-5",
      "EH-6",
      "EP-4",
      "EP-5",
      "ES-10",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21",
      "ES-28",
      "ES-7"
     ],
     "class": "equilibrium",
     "deciding": [],
     "error_items": [],
     "expected_check": "equilibrium",
     "gate_blocking": [],
     "named": null,
     "records": 118,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 118,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": false,
     "unchecked_records": 105
    },
    {
     "approved": false,
     "artefact": "a17",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "EA-9",
      "ES-1",
      "ES-34"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "ES-1"
     ],
     "class": "propagation",
     "deciding": [
      "ES-34"
     ],
     "error_items": [
      "ES-34"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 83,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 84,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 70
    },
    {
     "approved": false,
     "artefact": "a18",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "AC-9",
      "DS-30",
      "DS-4"
     ],
     "cited_by_twin_review": [
      "AC-9",
      "DS-4"
     ],
     "class": "propagation",
     "deciding": [
      "DS-30"
     ],
     "error_items": [
      "DS-30"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 82,
     "review": "fail",
     "review_cause": null,
     "role": "firmware",
     "twin_gate_failing_records": 0,
     "twin_records": 84,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 69
    },
    {
     "approved": false,
     "artefact": "a19",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "A7",
      "D28"
     ],
     "cited_by_twin_review": [],
     "class": "propagation",
     "deciding": [
      "D28"
     ],
     "error_items": [
      "D28"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 72,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 78,
     "twin_review": "blocked",
     "twin_review_cause": "blocking_spec_defect",
     "unchecked_on_expected_check": true,
     "unchecked_records": 59
    },
    {
     "approved": false,
     "artefact": "a20",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "AC-9",
      "DS-1",
      "DS-27",
      "DS-29",
      "DS-4",
      "DS-5",
      "RH-2"
     ],
     "cited_by_twin_review": [
      "AC-9",
      "DS-1",
      "DS-4",
      "DS-5"
     ],
     "class": "unit",
     "deciding": [
      "DS-27"
     ],
     "error_items": [
      "DS-27"
     ],
     "expected_check": "units",
     "gate_blocking": [
      "units"
     ],
     "named": true,
     "records": 86,
     "review": "fail",
     "review_cause": null,
     "role": "firmware",
     "twin_gate_failing_records": 0,
     "twin_records": 86,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 73
    },
    {
     "approved": false,
     "artefact": "a21",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D27",
      "D30",
      "S5"
     ],
     "cited_by_twin_review": [
      "A7",
      "D13",
      "D17",
      "D23",
      "D30",
      "D33",
      "D6",
      "D9",
      "S5"
     ],
     "class": "unit",
     "deciding": [],
     "error_items": [
      "D25",
      "D26"
     ],
     "expected_check": "units",
     "gate_blocking": [],
     "named": false,
     "records": 86,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 86,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 73
    },
    {
     "approved": false,
     "artefact": "a22",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D13",
      "D15",
      "D17",
      "D6",
      "R9",
      "S5"
     ],
     "cited_by_twin_review": [
      "A7",
      "D13",
      "S5"
     ],
     "class": "magnitude",
     "deciding": [],
     "error_items": [
      "D25",
      "D27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [],
     "named": false,
     "records": 86,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 86,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 73
    },
    {
     "approved": false,
     "artefact": "a23",
     "caught": false,
     "cited_at_all": true,
     "cited_by_review": [
      "A7",
      "D13",
      "D17",
      "D25",
      "D30",
      "D6",
      "S5"
     ],
     "cited_by_twin_review": [
      "A7",
      "D1",
      "D10",
      "D11",
      "D17",
      "D22",
      "D23",
      "D29",
      "D30",
      "D33",
      "D6",
      "D7",
      "D8",
      "D9",
      "R1",
      "S2",
      "S4",
      "S5"
     ],
     "class": "unit",
     "deciding": [
      "D25"
     ],
     "error_items": [
      "D25",
      "D26"
     ],
     "expected_check": "units",
     "gate_blocking": [],
     "named": true,
     "records": 91,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 91,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 78
    },
    {
     "approved": false,
     "artefact": "a24",
     "caught": true,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D28",
      "S5"
     ],
     "cited_by_twin_review": [
      "A7",
      "D1",
      "D10",
      "D11",
      "D13",
      "D14",
      "D17",
      "D22",
      "D23",
      "D24",
      "D29",
      "D3",
      "D30",
      "D32",
      "D33",
      "D4",
      "D5",
      "D6",
      "D7",
      "D8",
      "D9",
      "R1",
      "S2",
      "S4",
      "S5"
     ],
     "class": "magnitude",
     "deciding": [],
     "error_items": [
      "D25",
      "D27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [
      "magnitude"
     ],
     "named": false,
     "records": 91,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 91,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 78
    },
    {
     "approved": false,
     "artefact": "a25",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "A7",
      "D17",
      "D23",
      "D24",
      "D25",
      "D29",
      "D30",
      "D33",
      "D6",
      "D9",
      "R1",
      "R2",
      "S2",
      "S4",
      "S5"
     ],
     "cited_by_twin_review": [
      "A7",
      "D1",
      "D10",
      "D11",
      "D12",
      "D13",
      "D14",
      "D17",
      "D18",
      "D23",
      "D24",
      "D29",
      "D3",
      "D30",
      "D32",
      "D33",
      "D4",
      "D5",
      "D6",
      "D7",
      "D8",
      "D9",
      "R1",
      "S2",
      "S4",
      "S5"
     ],
     "class": "unit",
     "deciding": [
      "D25"
     ],
     "error_items": [
      "D25",
      "D26"
     ],
     "expected_check": "units",
     "gate_blocking": [
      "units"
     ],
     "named": true,
     "records": 79,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 79,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 66
    },
    {
     "approved": false,
     "artefact": "a26",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "A7",
      "D10",
      "D11",
      "D13",
      "D17",
      "D23",
      "D24",
      "D28",
      "D29",
      "D3",
      "D30",
      "D33",
      "D4",
      "D5",
      "D6",
      "D7",
      "D8",
      "D9",
      "R1",
      "S2",
      "S4",
      "S5"
     ],
     "cited_by_twin_review": [
      "A7",
      "D1",
      "D10",
      "D11",
      "D12",
      "D14",
      "D17",
      "D22",
      "D23",
      "D24",
      "D29",
      "D3",
      "D30",
      "D32",
      "D33",
      "D4",
      "D5",
      "D6",
      "D7",
      "D8",
      "D9",
      "R1",
      "R2",
      "S2",
      "S4",
      "S5"
     ],
     "class": "propagation",
     "deciding": [
      "D28"
     ],
     "error_items": [
      "D28"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 76,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 79,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 63
    },
    {
     "approved": false,
     "artefact": "a27",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D1",
      "D10",
      "D11",
      "D12",
      "D13",
      "D14",
      "D17",
      "D23",
      "D24",
      "D29",
      "D3",
      "D30",
      "D33",
      "D4",
      "D5",
      "D6",
      "D7",
      "D8",
      "D9",
      "R1",
      "R2",
      "S2",
      "S4",
      "S5"
     ],
     "cited_by_twin_review": [
      "A7",
      "D1",
      "D10",
      "D11",
      "D13",
      "D17",
      "D21",
      "D22",
      "D23",
      "D24",
      "D29",
      "D3",
      "D30",
      "D33",
      "D4",
      "D5",
      "D6",
      "D7",
      "D8",
      "D9",
      "S2",
      "S4",
      "S5"
     ],
     "class": "magnitude",
     "deciding": [],
     "error_items": [
      "D25",
      "D27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [],
     "named": false,
     "records": 79,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 79,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 66
    },
    {
     "approved": false,
     "artefact": "a28",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D10",
      "D11",
      "D12",
      "D13",
      "D17",
      "D22",
      "D23",
      "D24",
      "D29",
      "D3",
      "D30",
      "D33",
      "D4",
      "D5",
      "D6",
      "D7",
      "D8",
      "D9",
      "R1",
      "R2",
      "S2",
      "S4",
      "S5"
     ],
     "cited_by_twin_review": [
      "A7",
      "D10",
      "D11",
      "D13",
      "D14",
      "D17",
      "D22",
      "D23",
      "D24",
      "D29",
      "D3",
      "D30",
      "D33",
      "D4",
      "D5",
      "D6",
      "D7",
      "D8",
      "D9",
      "R1",
      "R2",
      "S2",
      "S4",
      "S5"
     ],
     "class": "magnitude",
     "deciding": [],
     "error_items": [
      "D25",
      "D27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [],
     "named": false,
     "records": 79,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 79,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 66
    },
    {
     "approved": false,
     "artefact": "a29",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "EA-9",
      "EH-3",
      "EP-3",
      "ES-1",
      "ES-3",
      "ES-31",
      "ES-32",
      "ES-4"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "EH-3",
      "EP-3",
      "ES-1",
      "ES-21",
      "ES-3",
      "ES-4",
      "ES-8"
     ],
     "class": "unit",
     "deciding": [
      "ES-31",
      "ES-32"
     ],
     "error_items": [
      "ES-31",
      "ES-32"
     ],
     "expected_check": "units",
     "gate_blocking": [
      "units",
      "propagation"
     ],
     "named": true,
     "records": 78,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 79,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 65
    },
    {
     "approved": false,
     "artefact": "a30",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "MA-10",
      "MS-5"
     ],
     "cited_by_twin_review": [],
     "class": "propagation",
     "deciding": [
      "MS-5"
     ],
     "error_items": [
      "MS-5"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 79,
     "review": "fail",
     "review_cause": null,
     "role": "mechanical",
     "twin_gate_failing_records": 0,
     "twin_records": 81,
     "twin_review": "pass",
     "twin_review_cause": null,
     "unchecked_on_expected_check": false,
     "unchecked_records": 66
    },
    {
     "approved": false,
     "artefact": "a31",
     "caught": false,
     "cited_at_all": true,
     "cited_by_review": [
      "AC-9",
      "DS-27",
      "RH-2"
     ],
     "cited_by_twin_review": [
      "AC-9"
     ],
     "class": "magnitude",
     "deciding": [
      "DS-27"
     ],
     "error_items": [
      "DS-27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [],
     "named": true,
     "records": 72,
     "review": "fail",
     "review_cause": null,
     "role": "firmware",
     "twin_gate_failing_records": 0,
     "twin_records": 72,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 59
    },
    {
     "approved": false,
     "artefact": "a32",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D28",
      "R9"
     ],
     "cited_by_twin_review": [],
     "class": "magnitude",
     "deciding": [],
     "error_items": [
      "D25",
      "D27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [],
     "named": false,
     "records": 75,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 75,
     "twin_review": "blocked",
     "twin_review_cause": "blocking_spec_defect",
     "unchecked_on_expected_check": true,
     "unchecked_records": 62
    },
    {
     "approved": false,
     "artefact": "a33",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D10",
      "D11",
      "D12",
      "D13",
      "D14",
      "D15",
      "D17",
      "D23",
      "D24",
      "D28",
      "D29",
      "D3",
      "D30",
      "D33",
      "D4",
      "D5",
      "D6",
      "D7",
      "D8",
      "D9",
      "R1",
      "R10",
      "R9",
      "S2",
      "S4",
      "S5"
     ],
     "cited_by_twin_review": [
      "D13",
      "D17",
      "D23",
      "D29",
      "D30",
      "D33",
      "D6",
      "R1",
      "S2",
      "S4",
      "S5"
     ],
     "class": "magnitude",
     "deciding": [],
     "error_items": [
      "D25",
      "D27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [],
     "named": false,
     "records": 86,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 86,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 73
    },
    {
     "approved": true,
     "artefact": "a34",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [],
     "cited_by_twin_review": [
      "D10",
      "D11",
      "D13",
      "D14",
      "D17",
      "D23",
      "D24",
      "D29",
      "D3",
      "D30",
      "D33",
      "D4",
      "D5",
      "D6",
      "D7",
      "D8",
      "D9",
      "R11",
      "S2",
      "S4",
      "S5"
     ],
     "class": "magnitude",
     "deciding": [],
     "error_items": [
      "D25",
      "D27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [],
     "named": false,
     "records": 86,
     "review": "pass",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 86,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 73
    },
    {
     "approved": false,
     "artefact": "a35",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "EA-9",
      "EH-6",
      "EP-4",
      "EP-5",
      "ES-10",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-19",
      "ES-20",
      "ES-21",
      "ES-33",
      "ES-34",
      "ES-35",
      "ES-5",
      "ES-6",
      "ES-7"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "EH-1",
      "EH-2",
      "EP-4",
      "EP-5",
      "ES-10",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-19",
      "ES-20",
      "ES-21",
      "ES-28",
      "ES-35",
      "ES-5",
      "ES-6",
      "ES-7"
     ],
     "class": "propagation",
     "deciding": [
      "ES-34"
     ],
     "error_items": [
      "ES-34"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 116,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 118,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 103
    },
    {
     "approved": false,
     "artefact": "a36",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "A7",
      "D25",
      "D30"
     ],
     "cited_by_twin_review": [],
     "class": "unit",
     "deciding": [
      "D25"
     ],
     "error_items": [
      "D25",
      "D26"
     ],
     "expected_check": "units",
     "gate_blocking": [
      "units"
     ],
     "named": true,
     "records": 86,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 86,
     "twin_review": "blocked",
     "twin_review_cause": "blocking_spec_defect",
     "unchecked_on_expected_check": true,
     "unchecked_records": 73
    },
    {
     "approved": false,
     "artefact": "a37",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D1",
      "D10",
      "D11",
      "D12",
      "D13",
      "D14",
      "D16",
      "D17",
      "D21",
      "D22",
      "D23",
      "D24",
      "D29",
      "D3",
      "D30",
      "D32",
      "D33",
      "D4",
      "D6",
      "D7",
      "D8",
      "D9",
      "R1",
      "S2",
      "S4",
      "S5"
     ],
     "cited_by_twin_review": [
      "A7",
      "D1",
      "D10",
      "D11",
      "D12",
      "D13",
      "D14",
      "D17",
      "D21",
      "D22",
      "D23",
      "D24",
      "D29",
      "D30",
      "D33",
      "D4",
      "D6",
      "D7",
      "D8",
      "D9",
      "R1",
      "R2",
      "S2",
      "S4",
      "S5"
     ],
     "class": "magnitude",
     "deciding": [],
     "error_items": [
      "D25",
      "D27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [],
     "named": false,
     "records": 79,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 79,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 66
    },
    {
     "approved": false,
     "artefact": "a38",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D28",
      "R7",
      "R9"
     ],
     "cited_by_twin_review": [],
     "class": "magnitude",
     "deciding": [],
     "error_items": [
      "D25",
      "D27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [],
     "named": false,
     "records": 75,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 75,
     "twin_review": "blocked",
     "twin_review_cause": "blocking_spec_defect",
     "unchecked_on_expected_check": true,
     "unchecked_records": 62
    },
    {
     "approved": false,
     "artefact": "a39",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "R11"
     ],
     "cited_by_twin_review": [],
     "class": "unit",
     "deciding": [],
     "error_items": [
      "D25",
      "D26"
     ],
     "expected_check": "units",
     "gate_blocking": [],
     "named": false,
     "records": 75,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 75,
     "twin_review": "blocked",
     "twin_review_cause": "blocking_spec_defect",
     "unchecked_on_expected_check": true,
     "unchecked_records": 62
    },
    {
     "approved": false,
     "artefact": "a40",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D17",
      "D23",
      "D29",
      "D30",
      "D33",
      "D6",
      "R1",
      "S2",
      "S4",
      "S5"
     ],
     "cited_by_twin_review": [
      "A7",
      "D17",
      "D30",
      "S5"
     ],
     "class": "unit",
     "deciding": [],
     "error_items": [
      "D25",
      "D26"
     ],
     "expected_check": "units",
     "gate_blocking": [],
     "named": false,
     "records": 86,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 86,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 73
    }
   ],
   "secondary": {
    "s6_10_named_against_caught": {
     "cited_at_all": 21,
     "named": 21,
     "no_error_item": 4,
     "per_class": {
      "equilibrium": {
       "caught_not_named": 1,
       "named_and_caught": 1,
       "named_not_caught": 2,
       "neither": 2,
       "no_error_item": 4
      },
      "magnitude": {
       "caught_not_named": 1,
       "named_and_caught": 0,
       "named_not_caught": 1,
       "neither": 8,
       "no_error_item": 0
      },
      "propagation": {
       "caught_not_named": 0,
       "named_and_caught": 10,
       "named_not_caught": 0,
       "neither": 0,
       "no_error_item": 0
      },
      "unit": {
       "caught_not_named": 0,
       "named_and_caught": 4,
       "named_not_caught": 3,
       "neither": 3,
       "no_error_item": 0
      }
     },
     "per_role": {
      "control": {
       "caught_not_named": 1,
       "named_and_caught": 4,
       "named_not_caught": 1,
       "neither": 11,
       "no_error_item": 0
      },
      "electrical": {
       "caught_not_named": 1,
       "named_and_caught": 6,
       "named_not_caught": 0,
       "neither": 0,
       "no_error_item": 4
      },
      "firmware": {
       "caught_not_named": 0,
       "named_and_caught": 2,
       "named_not_caught": 1,
       "neither": 0,
       "no_error_item": 0
      },
      "mechanical": {
       "caught_not_named": 0,
       "named_and_caught": 3,
       "named_not_caught": 4,
       "neither": 2,
       "no_error_item": 0
      }
     },
     "without_twin_condition": {
      "per_class": {
       "equilibrium": {
        "caught_not_named": 1,
        "named_and_caught": 1,
        "named_not_caught": 2,
        "neither": 2,
        "no_error_item": 4
       },
       "magnitude": {
        "caught_not_named": 1,
        "named_and_caught": 0,
        "named_not_caught": 1,
        "neither": 8,
        "no_error_item": 0
       },
       "propagation": {
        "caught_not_named": 0,
        "named_and_caught": 10,
        "named_not_caught": 0,
        "neither": 0,
        "no_error_item": 0
       },
       "unit": {
        "caught_not_named": 0,
        "named_and_caught": 4,
        "named_not_caught": 3,
        "neither": 3,
        "no_error_item": 0
       }
      },
      "per_role": {
       "control": {
        "caught_not_named": 1,
        "named_and_caught": 4,
        "named_not_caught": 1,
        "neither": 11,
        "no_error_item": 0
       },
       "electrical": {
        "caught_not_named": 1,
        "named_and_caught": 6,
        "named_not_caught": 0,
        "neither": 0,
        "no_error_item": 4
       },
       "firmware": {
        "caught_not_named": 0,
        "named_and_caught": 2,
        "named_not_caught": 1,
        "neither": 0,
        "no_error_item": 0
       },
       "mechanical": {
        "caught_not_named": 0,
        "named_and_caught": 3,
        "named_not_caught": 4,
        "neither": 2,
        "no_error_item": 0
       }
      }
     }
    },
    "s6_1_per_class": {
     "equilibrium": {
      "A": 0,
      "C": 0,
      "artefacts": 10
     },
     "magnitude": {
      "A": 1,
      "C": 0,
      "artefacts": 10
     },
     "propagation": {
      "A": 0,
      "C": 0,
      "artefacts": 10
     },
     "unit": {
      "A": 0,
      "C": 0,
      "artefacts": 10
     }
    },
    "s6_5_gate_caught_by_review_outcome": {
     "blocked": {
      "artefacts": 0,
      "caught": 0
     },
     "fail": {
      "artefacts": 39,
      "caught": 17
     },
     "pass": {
      "artefacts": 1,
      "caught": 0
     },
     "review_unavailable": {
      "artefacts": 0,
      "caught": 0
     }
    },
    "s6_7_twin_reviews": {
     "of": 40,
     "outcomes": {
      "blocked": 5,
      "fail": 34,
      "pass": 1
     },
     "refused": 34
    },
    "s6_8_per_role": {
     "control": {
      "A": 1,
      "C": 0,
      "artefacts": 17
     },
     "electrical": {
      "A": 0,
      "C": 0,
      "artefacts": 11
     },
     "firmware": {
      "A": 0,
      "C": 0,
      "artefacts": 3
     },
     "mechanical": {
      "A": 0,
      "C": 0,
      "artefacts": 9
     }
    },
    "s6_9_not_judged_per_role": {
     "control": {
      "artefacts": {
       "blocked": [],
       "review_unavailable": []
      },
      "twins": {
       "blocked": [
        [
         "a19",
         "blocking_spec_defect"
        ],
        [
         "a32",
         "blocking_spec_defect"
        ],
        [
         "a36",
         "blocking_spec_defect"
        ],
        [
         "a38",
         "blocking_spec_defect"
        ],
        [
         "a39",
         "blocking_spec_defect"
        ]
       ],
       "review_unavailable": []
      }
     },
     "electrical": {
      "artefacts": {
       "blocked": [],
       "review_unavailable": []
      },
      "twins": {
       "blocked": [],
       "review_unavailable": []
      }
     },
     "firmware": {
      "artefacts": {
       "blocked": [],
       "review_unavailable": []
      },
      "twins": {
       "blocked": [],
       "review_unavailable": []
      }
     },
     "mechanical": {
      "artefacts": {
       "blocked": [],
       "review_unavailable": []
      },
      "twins": {
       "blocked": [],
       "review_unavailable": []
      }
     }
    }
   }
  },
  "I1": {
   "A": 0,
   "C": 0,
   "kill": true,
   "listed_not_approved_without_a_verdict": [
    [
     "a19",
     "review_unavailable",
     "invalid_verdict"
    ]
   ],
   "per_artefact": [
    {
     "approved": false,
     "artefact": "a01",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "EA-9",
      "EH-1",
      "EH-6",
      "EP-5",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21",
      "ES-34"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "EH-1",
      "EP-2",
      "EP-4",
      "EP-5",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21",
      "ES-6",
      "ES-7"
     ],
     "class": "propagation",
     "deciding": [
      "ES-34"
     ],
     "error_items": [
      "ES-34"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 115,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 102
    },
    {
     "approved": false,
     "artefact": "a02",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "EA-9",
      "EH-1",
      "EP-5",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21",
      "ES-34"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "EH-1",
      "EH-5",
      "EH-6",
      "EP-5",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-5"
     ],
     "class": "propagation",
     "deciding": [
      "ES-34"
     ],
     "error_items": [
      "ES-34"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 114,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 101
    },
    {
     "approved": false,
     "artefact": "a03",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "MA-10",
      "MS-28",
      "MS-5"
     ],
     "cited_by_twin_review": [
      "MA-10",
      "MH-1",
      "MS-28"
     ],
     "class": "propagation",
     "deciding": [
      "MS-5"
     ],
     "error_items": [
      "MS-5"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 96,
     "review": "fail",
     "review_cause": null,
     "role": "mechanical",
     "twin_gate_failing_records": 0,
     "twin_records": 97,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 83
    },
    {
     "approved": false,
     "artefact": "a04",
     "caught": false,
     "cited_at_all": true,
     "cited_by_review": [
      "MA-10",
      "MH-2",
      "MS-1",
      "MS-2",
      "MS-28",
      "MS-3"
     ],
     "cited_by_twin_review": [
      "MA-10",
      "MS-28"
     ],
     "class": "unit",
     "deciding": [
      "MS-2"
     ],
     "error_items": [
      "MS-2"
     ],
     "expected_check": "units",
     "gate_blocking": [],
     "named": true,
     "records": 97,
     "review": "fail",
     "review_cause": null,
     "role": "mechanical",
     "twin_gate_failing_records": 0,
     "twin_records": 97,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 84
    },
    {
     "approved": false,
     "artefact": "a05",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "MA-10",
      "MP-10",
      "MS-1",
      "MS-26",
      "MS-28",
      "MS-3"
     ],
     "cited_by_twin_review": [
      "MA-10",
      "MS-28"
     ],
     "class": "equilibrium",
     "deciding": [],
     "error_items": [
      "MS-4"
     ],
     "expected_check": "equilibrium",
     "gate_blocking": [],
     "named": false,
     "records": 97,
     "review": "fail",
     "review_cause": null,
     "role": "mechanical",
     "twin_gate_failing_records": 0,
     "twin_records": 97,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": false,
     "unchecked_records": 84
    },
    {
     "approved": false,
     "artefact": "a06",
     "caught": false,
     "cited_at_all": true,
     "cited_by_review": [
      "MA-10",
      "MS-1",
      "MS-2",
      "MS-28",
      "MS-3"
     ],
     "cited_by_twin_review": [
      "MA-10",
      "MS-28"
     ],
     "class": "unit",
     "deciding": [
      "MS-2"
     ],
     "error_items": [
      "MS-2"
     ],
     "expected_check": "units",
     "gate_blocking": [],
     "named": true,
     "records": 97,
     "review": "fail",
     "review_cause": null,
     "role": "mechanical",
     "twin_gate_failing_records": 0,
     "twin_records": 97,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 84
    },
    {
     "approved": false,
     "artefact": "a07",
     "caught": false,
     "cited_at_all": true,
     "cited_by_review": [
      "MA-10",
      "MH-2",
      "MP-3",
      "MS-1",
      "MS-28",
      "MS-3",
      "MS-4",
      "MS-5"
     ],
     "cited_by_twin_review": [
      "MA-10",
      "MH-1",
      "MS-28"
     ],
     "class": "equilibrium",
     "deciding": [
      "MS-4"
     ],
     "error_items": [
      "MS-4"
     ],
     "expected_check": "equilibrium",
     "gate_blocking": [],
     "named": true,
     "records": 116,
     "review": "fail",
     "review_cause": null,
     "role": "mechanical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": false,
     "unchecked_records": 103
    },
    {
     "approved": false,
     "artefact": "a08",
     "caught": false,
     "cited_at_all": null,
     "cited_by_review": [
      "EA-9",
      "EH-6",
      "EP-4",
      "EP-5",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21",
      "ES-32"
     ],
     "cited_by_twin_review": [],
     "class": "equilibrium",
     "deciding": [],
     "error_items": [],
     "expected_check": "equilibrium",
     "gate_blocking": [],
     "named": null,
     "records": 116,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "review_unavailable",
     "twin_review_cause": "invalid_verdict",
     "unchecked_on_expected_check": false,
     "unchecked_records": 103
    },
    {
     "approved": false,
     "artefact": "a09",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "MA-10",
      "MH-2",
      "MS-1",
      "MS-3"
     ],
     "cited_by_twin_review": [
      "MA-10",
      "MS-28"
     ],
     "class": "equilibrium",
     "deciding": [],
     "error_items": [
      "MS-4"
     ],
     "expected_check": "equilibrium",
     "gate_blocking": [],
     "named": false,
     "records": 116,
     "review": "fail",
     "review_cause": null,
     "role": "mechanical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": false,
     "unchecked_records": 103
    },
    {
     "approved": false,
     "artefact": "a10",
     "caught": true,
     "cited_at_all": false,
     "cited_by_review": [
      "EA-9",
      "EH-6",
      "EP-4",
      "EP-5",
      "ES-14",
      "ES-15"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "EH-1",
      "EH-6",
      "EP-5",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21",
      "ES-5"
     ],
     "class": "equilibrium",
     "deciding": [],
     "error_items": [
      "ES-7",
      "ES-9",
      "ES-33"
     ],
     "expected_check": "conservation",
     "gate_blocking": [
      "conservation"
     ],
     "named": false,
     "records": 112,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 99
    },
    {
     "approved": false,
     "artefact": "a11",
     "caught": false,
     "cited_at_all": true,
     "cited_by_review": [
      "MA-10",
      "MH-2",
      "MS-1",
      "MS-28",
      "MS-3",
      "MS-4"
     ],
     "cited_by_twin_review": [],
     "class": "equilibrium",
     "deciding": [
      "MS-4"
     ],
     "error_items": [
      "MS-4"
     ],
     "expected_check": "equilibrium",
     "gate_blocking": [],
     "named": true,
     "records": 116,
     "review": "fail",
     "review_cause": null,
     "role": "mechanical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "review_unavailable",
     "twin_review_cause": "invalid_verdict",
     "unchecked_on_expected_check": false,
     "unchecked_records": 103
    },
    {
     "approved": false,
     "artefact": "a12",
     "caught": false,
     "cited_at_all": null,
     "cited_by_review": [
      "EA-9",
      "EH-1",
      "EH-5",
      "EP-5",
      "ES-14",
      "ES-15"
     ],
     "cited_by_twin_review": [],
     "class": "equilibrium",
     "deciding": [],
     "error_items": [],
     "expected_check": "equilibrium",
     "gate_blocking": [],
     "named": null,
     "records": 116,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "pass",
     "twin_review_cause": null,
     "unchecked_on_expected_check": false,
     "unchecked_records": 103
    },
    {
     "approved": false,
     "artefact": "a13",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "MA-10",
      "MS-26",
      "MS-28",
      "MS-3"
     ],
     "cited_by_twin_review": [
      "MA-10",
      "MS-28",
      "MS-6"
     ],
     "class": "equilibrium",
     "deciding": [
      "MS-26",
      "MS-3"
     ],
     "error_items": [
      "MS-3",
      "MS-26"
     ],
     "expected_check": "conservation",
     "gate_blocking": [
      "conservation"
     ],
     "named": true,
     "records": 112,
     "review": "fail",
     "review_cause": null,
     "role": "mechanical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 99
    },
    {
     "approved": false,
     "artefact": "a14",
     "caught": false,
     "cited_at_all": null,
     "cited_by_review": [
      "EA-9",
      "EP-4",
      "EP-5",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21",
      "ES-32"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "EH-6",
      "EP-5",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21"
     ],
     "class": "equilibrium",
     "deciding": [],
     "error_items": [],
     "expected_check": "equilibrium",
     "gate_blocking": [],
     "named": null,
     "records": 116,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": false,
     "unchecked_records": 103
    },
    {
     "approved": false,
     "artefact": "a15",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "EA-9",
      "EH-1",
      "EH-3",
      "EH-5",
      "EP-4",
      "EP-5",
      "ES-10",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-19",
      "ES-20",
      "ES-21",
      "ES-27",
      "ES-28",
      "ES-34",
      "ES-35",
      "ES-5",
      "ES-7"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "EP-4",
      "EP-5",
      "ES-10",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-17",
      "ES-21",
      "ES-28",
      "ES-6",
      "ES-7"
     ],
     "class": "propagation",
     "deciding": [
      "ES-34"
     ],
     "error_items": [
      "ES-34"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 90,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 92,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 76
    },
    {
     "approved": false,
     "artefact": "a16",
     "caught": false,
     "cited_at_all": null,
     "cited_by_review": [
      "EA-9",
      "EH-1",
      "EH-5",
      "EH-6",
      "EP-4",
      "EP-5",
      "ES-10",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21",
      "ES-5",
      "ES-7"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "EH-1",
      "EH-3",
      "EP-4",
      "EP-5",
      "ES-1",
      "ES-10",
      "ES-11",
      "ES-13",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21",
      "ES-28",
      "ES-33",
      "ES-34",
      "ES-7"
     ],
     "class": "equilibrium",
     "deciding": [],
     "error_items": [],
     "expected_check": "equilibrium",
     "gate_blocking": [],
     "named": null,
     "records": 118,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 118,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": false,
     "unchecked_records": 105
    },
    {
     "approved": false,
     "artefact": "a17",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "EA-9",
      "ES-34"
     ],
     "cited_by_twin_review": [],
     "class": "propagation",
     "deciding": [
      "ES-34"
     ],
     "error_items": [
      "ES-34"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 83,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 84,
     "twin_review": "pass",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 70
    },
    {
     "approved": false,
     "artefact": "a18",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "AC-9",
      "DS-30"
     ],
     "cited_by_twin_review": [
      "AC-9",
      "DS-30",
      "DS-4"
     ],
     "class": "propagation",
     "deciding": [],
     "error_items": [
      "DS-30"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": false,
     "records": 82,
     "review": "fail",
     "review_cause": null,
     "role": "firmware",
     "twin_gate_failing_records": 0,
     "twin_records": 84,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 69
    },
    {
     "approved": false,
     "artefact": "a19",
     "caught": true,
     "cited_at_all": false,
     "cited_by_review": [],
     "cited_by_twin_review": [],
     "class": "propagation",
     "deciding": [],
     "error_items": [
      "D28"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": false,
     "records": 72,
     "review": "review_unavailable",
     "review_cause": "invalid_verdict",
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 78,
     "twin_review": "blocked",
     "twin_review_cause": "blocking_spec_defect",
     "unchecked_on_expected_check": true,
     "unchecked_records": 59
    },
    {
     "approved": false,
     "artefact": "a20",
     "caught": true,
     "cited_at_all": false,
     "cited_by_review": [
      "AC-9",
      "DS-1",
      "DS-2",
      "DS-29",
      "DS-4",
      "DS-5"
     ],
     "cited_by_twin_review": [
      "AC-9",
      "DS-30",
      "DS-4",
      "DS-5"
     ],
     "class": "unit",
     "deciding": [],
     "error_items": [
      "DS-27"
     ],
     "expected_check": "units",
     "gate_blocking": [
      "units"
     ],
     "named": false,
     "records": 86,
     "review": "fail",
     "review_cause": null,
     "role": "firmware",
     "twin_gate_failing_records": 0,
     "twin_records": 86,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 73
    },
    {
     "approved": false,
     "artefact": "a21",
     "caught": false,
     "cited_at_all": true,
     "cited_by_review": [
      "A7",
      "D25",
      "R9",
      "S5"
     ],
     "cited_by_twin_review": [
      "A7",
      "D13",
      "D17",
      "D30",
      "D6",
      "S5"
     ],
     "class": "unit",
     "deciding": [
      "D25"
     ],
     "error_items": [
      "D25",
      "D26"
     ],
     "expected_check": "units",
     "gate_blocking": [],
     "named": true,
     "records": 86,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 86,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 73
    },
    {
     "approved": false,
     "artefact": "a22",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D17",
      "D30",
      "D6",
      "R1",
      "R9",
      "S5"
     ],
     "cited_by_twin_review": [
      "A7",
      "D13",
      "D17",
      "D30",
      "D6",
      "S5"
     ],
     "class": "magnitude",
     "deciding": [],
     "error_items": [
      "D25",
      "D27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [],
     "named": false,
     "records": 86,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 86,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 73
    },
    {
     "approved": false,
     "artefact": "a23",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D13",
      "D17",
      "D21",
      "D30",
      "D6",
      "S5"
     ],
     "cited_by_twin_review": [
      "A7",
      "D1",
      "D10",
      "D11",
      "D12",
      "D13",
      "D17",
      "D23",
      "D29",
      "D30",
      "D33",
      "D4",
      "D6",
      "D7",
      "D8",
      "D9",
      "S2",
      "S5"
     ],
     "class": "unit",
     "deciding": [],
     "error_items": [
      "D25",
      "D26"
     ],
     "expected_check": "units",
     "gate_blocking": [],
     "named": false,
     "records": 91,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 91,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 78
    },
    {
     "approved": false,
     "artefact": "a24",
     "caught": true,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D1",
      "D10",
      "D11",
      "D12",
      "D13",
      "D14",
      "D17",
      "D22",
      "D23",
      "D24",
      "D29",
      "D30",
      "D32",
      "D33",
      "D4",
      "D6",
      "D7",
      "D8",
      "D9",
      "R1",
      "R9",
      "S2",
      "S4",
      "S5"
     ],
     "cited_by_twin_review": [
      "A7",
      "D13",
      "D17",
      "D29",
      "D30",
      "D6",
      "S5"
     ],
     "class": "magnitude",
     "deciding": [],
     "error_items": [
      "D25",
      "D27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [
      "magnitude"
     ],
     "named": false,
     "records": 91,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 91,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 78
    },
    {
     "approved": false,
     "artefact": "a25",
     "caught": true,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D1",
      "D10",
      "D11",
      "D13",
      "D17",
      "D2",
      "D21",
      "D22",
      "D23",
      "D24",
      "D29",
      "D3",
      "D30",
      "D32",
      "D33",
      "D4",
      "D5",
      "D6",
      "D7",
      "D8",
      "D9",
      "S2",
      "S4",
      "S5"
     ],
     "cited_by_twin_review": [
      "A7",
      "D1",
      "D10",
      "D11",
      "D13",
      "D14",
      "D17",
      "D23",
      "D24",
      "D29",
      "D3",
      "D30",
      "D32",
      "D33",
      "D4",
      "D5",
      "D6",
      "D7",
      "D8",
      "D9",
      "S2",
      "S4",
      "S5"
     ],
     "class": "unit",
     "deciding": [],
     "error_items": [
      "D25",
      "D26"
     ],
     "expected_check": "units",
     "gate_blocking": [
      "units"
     ],
     "named": false,
     "records": 79,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 79,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 66
    },
    {
     "approved": false,
     "artefact": "a26",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "A7",
      "D10",
      "D11",
      "D17",
      "D22",
      "D23",
      "D24",
      "D28",
      "D29",
      "D30",
      "D33",
      "D6",
      "D7",
      "D8",
      "D9",
      "R1",
      "R2",
      "S2",
      "S4"
     ],
     "cited_by_twin_review": [
      "A7",
      "D1",
      "D10",
      "D11",
      "D13",
      "D14",
      "D17",
      "D23",
      "D24",
      "D29",
      "D30",
      "D33",
      "D6",
      "D7",
      "D8",
      "D9",
      "R1",
      "S2",
      "S4",
      "S5"
     ],
     "class": "propagation",
     "deciding": [
      "D28"
     ],
     "error_items": [
      "D28"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 76,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 79,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 63
    },
    {
     "approved": false,
     "artefact": "a27",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D1",
      "D10",
      "D11",
      "D13",
      "D17",
      "D22",
      "D23",
      "D24",
      "D29",
      "D30",
      "D33",
      "D6",
      "D7",
      "D8",
      "D9",
      "R1",
      "S2",
      "S4",
      "S5"
     ],
     "cited_by_twin_review": [],
     "class": "magnitude",
     "deciding": [],
     "error_items": [
      "D25",
      "D27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [],
     "named": false,
     "records": 79,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 79,
     "twin_review": "review_unavailable",
     "twin_review_cause": "invalid_verdict",
     "unchecked_on_expected_check": true,
     "unchecked_records": 66
    },
    {
     "approved": false,
     "artefact": "a28",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D1",
      "D10",
      "D11",
      "D12",
      "D13",
      "D14",
      "D15",
      "D17",
      "D22",
      "D23",
      "D24",
      "D29",
      "D3",
      "D30",
      "D33",
      "D4",
      "D5",
      "D6",
      "D7",
      "D8",
      "D9",
      "R1",
      "R2",
      "S2",
      "S4",
      "S5"
     ],
     "cited_by_twin_review": [
      "A7",
      "D1",
      "D10",
      "D11",
      "D13",
      "D17",
      "D22",
      "D23",
      "D24",
      "D29",
      "D3",
      "D30",
      "D32",
      "D33",
      "D4",
      "D5",
      "D6",
      "D7",
      "D8",
      "D9",
      "R1",
      "S2",
      "S4",
      "S5"
     ],
     "class": "magnitude",
     "deciding": [],
     "error_items": [
      "D25",
      "D27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [],
     "named": false,
     "records": 79,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 79,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 66
    },
    {
     "approved": false,
     "artefact": "a29",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "EA-9",
      "EH-3",
      "EP-3",
      "ES-1",
      "ES-21",
      "ES-3",
      "ES-31",
      "ES-32",
      "ES-33",
      "ES-4",
      "ES-7",
      "ES-8"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "EH-3",
      "EP-3",
      "ES-1",
      "ES-21",
      "ES-3",
      "ES-4"
     ],
     "class": "unit",
     "deciding": [
      "ES-31",
      "ES-32"
     ],
     "error_items": [
      "ES-31",
      "ES-32"
     ],
     "expected_check": "units",
     "gate_blocking": [
      "units",
      "propagation"
     ],
     "named": true,
     "records": 78,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 79,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 65
    },
    {
     "approved": false,
     "artefact": "a30",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "MA-10",
      "MS-30",
      "MS-5"
     ],
     "cited_by_twin_review": [
      "MA-10",
      "MP-10",
      "MS-26",
      "MS-3"
     ],
     "class": "propagation",
     "deciding": [
      "MS-5"
     ],
     "error_items": [
      "MS-5"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 79,
     "review": "fail",
     "review_cause": null,
     "role": "mechanical",
     "twin_gate_failing_records": 0,
     "twin_records": 81,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": false,
     "unchecked_records": 66
    },
    {
     "approved": false,
     "artefact": "a31",
     "caught": false,
     "cited_at_all": true,
     "cited_by_review": [
      "AC-9",
      "DS-27"
     ],
     "cited_by_twin_review": [
      "AC-9",
      "DS-27",
      "RH-2"
     ],
     "class": "magnitude",
     "deciding": [],
     "error_items": [
      "DS-27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [],
     "named": false,
     "records": 72,
     "review": "fail",
     "review_cause": null,
     "role": "firmware",
     "twin_gate_failing_records": 0,
     "twin_records": 72,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 59
    },
    {
     "approved": false,
     "artefact": "a32",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D21",
      "D28",
      "R9"
     ],
     "cited_by_twin_review": [],
     "class": "magnitude",
     "deciding": [],
     "error_items": [
      "D25",
      "D27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [],
     "named": false,
     "records": 75,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 75,
     "twin_review": "blocked",
     "twin_review_cause": "blocking_spec_defect",
     "unchecked_on_expected_check": true,
     "unchecked_records": 62
    },
    {
     "approved": false,
     "artefact": "a33",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D10",
      "D11",
      "D13",
      "D15",
      "D17",
      "D23",
      "D24",
      "D28",
      "D29",
      "D30",
      "D33",
      "D6",
      "D7",
      "D8",
      "D9",
      "R1",
      "R9",
      "S2",
      "S4",
      "S5"
     ],
     "cited_by_twin_review": [
      "D13",
      "D14",
      "D17",
      "D30",
      "D33",
      "D6",
      "S2",
      "S4",
      "S5"
     ],
     "class": "magnitude",
     "deciding": [],
     "error_items": [
      "D25",
      "D27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [],
     "named": false,
     "records": 86,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 86,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 73
    },
    {
     "approved": false,
     "artefact": "a34",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D15",
      "D17",
      "D29",
      "D30",
      "D6"
     ],
     "cited_by_twin_review": [
      "A7",
      "D13",
      "D17",
      "D30",
      "D6",
      "S5"
     ],
     "class": "magnitude",
     "deciding": [],
     "error_items": [
      "D25",
      "D27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [],
     "named": false,
     "records": 86,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 86,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 73
    },
    {
     "approved": false,
     "artefact": "a35",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "EA-9",
      "EH-3",
      "EH-6",
      "EP-4",
      "EP-5",
      "ES-10",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21",
      "ES-33",
      "ES-34",
      "ES-6",
      "ES-7",
      "ES-9"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "EH-1",
      "EP-4",
      "EP-5",
      "ES-10",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21",
      "ES-27",
      "ES-33",
      "ES-6",
      "ES-7"
     ],
     "class": "propagation",
     "deciding": [
      "ES-34"
     ],
     "error_items": [
      "ES-34"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 116,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 118,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 103
    },
    {
     "approved": false,
     "artefact": "a36",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "A7",
      "D25",
      "D30",
      "S5"
     ],
     "cited_by_twin_review": [],
     "class": "unit",
     "deciding": [
      "D25"
     ],
     "error_items": [
      "D25",
      "D26"
     ],
     "expected_check": "units",
     "gate_blocking": [
      "units"
     ],
     "named": true,
     "records": 86,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 86,
     "twin_review": "pass",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 73
    },
    {
     "approved": false,
     "artefact": "a37",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D1",
      "D17",
      "D23",
      "D24",
      "D29",
      "D30",
      "D32",
      "D33",
      "D6",
      "D8",
      "D9",
      "R1",
      "R2",
      "S2",
      "S4",
      "S5"
     ],
     "cited_by_twin_review": [
      "A7",
      "D1",
      "D10",
      "D11",
      "D12",
      "D13",
      "D14",
      "D17",
      "D23",
      "D24",
      "D29",
      "D3",
      "D30",
      "D32",
      "D33",
      "D4",
      "D5",
      "D6",
      "D7",
      "D8",
      "D9",
      "R1",
      "R2",
      "S2",
      "S4",
      "S5"
     ],
     "class": "magnitude",
     "deciding": [],
     "error_items": [
      "D25",
      "D27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [],
     "named": false,
     "records": 79,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 79,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 66
    },
    {
     "approved": false,
     "artefact": "a38",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D28",
      "R7",
      "R9"
     ],
     "cited_by_twin_review": [],
     "class": "magnitude",
     "deciding": [],
     "error_items": [
      "D25",
      "D27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [],
     "named": false,
     "records": 75,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 75,
     "twin_review": "blocked",
     "twin_review_cause": "blocking_spec_defect",
     "unchecked_on_expected_check": true,
     "unchecked_records": 62
    },
    {
     "approved": false,
     "artefact": "a39",
     "caught": false,
     "cited_at_all": true,
     "cited_by_review": [
      "A7",
      "D25"
     ],
     "cited_by_twin_review": [],
     "class": "unit",
     "deciding": [
      "D25"
     ],
     "error_items": [
      "D25",
      "D26"
     ],
     "expected_check": "units",
     "gate_blocking": [],
     "named": true,
     "records": 75,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 75,
     "twin_review": "blocked",
     "twin_review_cause": "blocking_spec_defect",
     "unchecked_on_expected_check": true,
     "unchecked_records": 62
    },
    {
     "approved": false,
     "artefact": "a40",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7"
     ],
     "cited_by_twin_review": [
      "A7",
      "D30",
      "S5"
     ],
     "class": "unit",
     "deciding": [],
     "error_items": [
      "D25",
      "D26"
     ],
     "expected_check": "units",
     "gate_blocking": [],
     "named": false,
     "records": 86,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 86,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 73
    }
   ],
   "secondary": {
    "s6_10_named_against_caught": {
     "cited_at_all": 19,
     "named": 17,
     "no_error_item": 4,
     "per_class": {
      "equilibrium": {
       "caught_not_named": 1,
       "named_and_caught": 1,
       "named_not_caught": 2,
       "neither": 2,
       "no_error_item": 4
      },
      "magnitude": {
       "caught_not_named": 1,
       "named_and_caught": 0,
       "named_not_caught": 0,
       "neither": 9,
       "no_error_item": 0
      },
      "propagation": {
       "caught_not_named": 2,
       "named_and_caught": 8,
       "named_not_caught": 0,
       "neither": 0,
       "no_error_item": 0
      },
      "unit": {
       "caught_not_named": 2,
       "named_and_caught": 2,
       "named_not_caught": 4,
       "neither": 2,
       "no_error_item": 0
      }
     },
     "per_role": {
      "control": {
       "caught_not_named": 3,
       "named_and_caught": 2,
       "named_not_caught": 2,
       "neither": 10,
       "no_error_item": 0
      },
      "electrical": {
       "caught_not_named": 1,
       "named_and_caught": 6,
       "named_not_caught": 0,
       "neither": 0,
       "no_error_item": 4
      },
      "firmware": {
       "caught_not_named": 2,
       "named_and_caught": 0,
       "named_not_caught": 0,
       "neither": 1,
       "no_error_item": 0
      },
      "mechanical": {
       "caught_not_named": 0,
       "named_and_caught": 3,
       "named_not_caught": 4,
       "neither": 2,
       "no_error_item": 0
      }
     },
     "without_twin_condition": {
      "per_class": {
       "equilibrium": {
        "caught_not_named": 1,
        "named_and_caught": 1,
        "named_not_caught": 2,
        "neither": 2,
        "no_error_item": 4
       },
       "magnitude": {
        "caught_not_named": 1,
        "named_and_caught": 0,
        "named_not_caught": 1,
        "neither": 8,
        "no_error_item": 0
       },
       "propagation": {
        "caught_not_named": 1,
        "named_and_caught": 9,
        "named_not_caught": 0,
        "neither": 0,
        "no_error_item": 0
       },
       "unit": {
        "caught_not_named": 2,
        "named_and_caught": 2,
        "named_not_caught": 4,
        "neither": 2,
        "no_error_item": 0
       }
      },
      "per_role": {
       "control": {
        "caught_not_named": 3,
        "named_and_caught": 2,
        "named_not_caught": 2,
        "neither": 10,
        "no_error_item": 0
       },
       "electrical": {
        "caught_not_named": 1,
        "named_and_caught": 6,
        "named_not_caught": 0,
        "neither": 0,
        "no_error_item": 4
       },
       "firmware": {
        "caught_not_named": 1,
        "named_and_caught": 1,
        "named_not_caught": 1,
        "neither": 0,
        "no_error_item": 0
       },
       "mechanical": {
        "caught_not_named": 0,
        "named_and_caught": 3,
        "named_not_caught": 4,
        "neither": 2,
        "no_error_item": 0
       }
      }
     }
    },
    "s6_1_per_class": {
     "equilibrium": {
      "A": 0,
      "C": 0,
      "artefacts": 10
     },
     "magnitude": {
      "A": 0,
      "C": 0,
      "artefacts": 10
     },
     "propagation": {
      "A": 0,
      "C": 0,
      "artefacts": 10
     },
     "unit": {
      "A": 0,
      "C": 0,
      "artefacts": 10
     }
    },
    "s6_5_gate_caught_by_review_outcome": {
     "blocked": {
      "artefacts": 0,
      "caught": 0
     },
     "fail": {
      "artefacts": 39,
      "caught": 16
     },
     "pass": {
      "artefacts": 0,
      "caught": 0
     },
     "review_unavailable": {
      "artefacts": 1,
      "caught": 1
     }
    },
    "s6_7_twin_reviews": {
     "of": 40,
     "outcomes": {
      "blocked": 4,
      "fail": 30,
      "pass": 3,
      "review_unavailable": 3
     },
     "refused": 30
    },
    "s6_8_per_role": {
     "control": {
      "A": 0,
      "C": 0,
      "artefacts": 17
     },
     "electrical": {
      "A": 0,
      "C": 0,
      "artefacts": 11
     },
     "firmware": {
      "A": 0,
      "C": 0,
      "artefacts": 3
     },
     "mechanical": {
      "A": 0,
      "C": 0,
      "artefacts": 9
     }
    },
    "s6_9_not_judged_per_role": {
     "control": {
      "artefacts": {
       "blocked": [],
       "review_unavailable": [
        [
         "a19",
         "invalid_verdict"
        ]
       ]
      },
      "twins": {
       "blocked": [
        [
         "a19",
         "blocking_spec_defect"
        ],
        [
         "a32",
         "blocking_spec_defect"
        ],
        [
         "a38",
         "blocking_spec_defect"
        ],
        [
         "a39",
         "blocking_spec_defect"
        ]
       ],
       "review_unavailable": [
        [
         "a27",
         "invalid_verdict"
        ]
       ]
      }
     },
     "electrical": {
      "artefacts": {
       "blocked": [],
       "review_unavailable": []
      },
      "twins": {
       "blocked": [],
       "review_unavailable": [
        [
         "a08",
         "invalid_verdict"
        ]
       ]
      }
     },
     "firmware": {
      "artefacts": {
       "blocked": [],
       "review_unavailable": []
      },
      "twins": {
       "blocked": [],
       "review_unavailable": []
      }
     },
     "mechanical": {
      "artefacts": {
       "blocked": [],
       "review_unavailable": []
      },
      "twins": {
       "blocked": [],
       "review_unavailable": [
        [
         "a11",
         "invalid_verdict"
        ]
       ]
      }
     }
    }
   }
  },
  "I2": {
   "A": 0,
   "C": 0,
   "kill": true,
   "listed_not_approved_without_a_verdict": [],
   "per_artefact": [
    {
     "approved": false,
     "artefact": "a01",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "EA-9",
      "EH-6",
      "EP-4",
      "EP-5",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21",
      "ES-34"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "EH-6",
      "EP-4",
      "EP-5",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21"
     ],
     "class": "propagation",
     "deciding": [
      "ES-34"
     ],
     "error_items": [
      "ES-34"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 115,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 102
    },
    {
     "approved": false,
     "artefact": "a02",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "EA-9",
      "ES-34"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "EH-1",
      "EH-5",
      "EH-6",
      "EP-4",
      "EP-5",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21"
     ],
     "class": "propagation",
     "deciding": [
      "ES-34"
     ],
     "error_items": [
      "ES-34"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 114,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 101
    },
    {
     "approved": false,
     "artefact": "a03",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "MA-10",
      "MS-28",
      "MS-3",
      "MS-5"
     ],
     "cited_by_twin_review": [
      "MA-10",
      "MS-28"
     ],
     "class": "propagation",
     "deciding": [
      "MS-5"
     ],
     "error_items": [
      "MS-5"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 96,
     "review": "fail",
     "review_cause": null,
     "role": "mechanical",
     "twin_gate_failing_records": 0,
     "twin_records": 97,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 83
    },
    {
     "approved": false,
     "artefact": "a04",
     "caught": false,
     "cited_at_all": true,
     "cited_by_review": [
      "MA-10",
      "MS-1",
      "MS-2",
      "MS-28",
      "MS-3",
      "MS-5"
     ],
     "cited_by_twin_review": [
      "MA-10",
      "MS-28"
     ],
     "class": "unit",
     "deciding": [
      "MS-2"
     ],
     "error_items": [
      "MS-2"
     ],
     "expected_check": "units",
     "gate_blocking": [],
     "named": true,
     "records": 97,
     "review": "fail",
     "review_cause": null,
     "role": "mechanical",
     "twin_gate_failing_records": 0,
     "twin_records": 97,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 84
    },
    {
     "approved": false,
     "artefact": "a05",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "MA-10",
      "MH-2",
      "MP-10",
      "MS-1",
      "MS-26",
      "MS-28",
      "MS-3",
      "MS-5"
     ],
     "cited_by_twin_review": [
      "MA-10",
      "MS-28"
     ],
     "class": "equilibrium",
     "deciding": [],
     "error_items": [
      "MS-4"
     ],
     "expected_check": "equilibrium",
     "gate_blocking": [],
     "named": false,
     "records": 97,
     "review": "fail",
     "review_cause": null,
     "role": "mechanical",
     "twin_gate_failing_records": 0,
     "twin_records": 97,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": false,
     "unchecked_records": 84
    },
    {
     "approved": false,
     "artefact": "a06",
     "caught": false,
     "cited_at_all": true,
     "cited_by_review": [
      "MA-10",
      "MS-1",
      "MS-2",
      "MS-28",
      "MS-3"
     ],
     "cited_by_twin_review": [
      "MA-10",
      "MS-28",
      "MS-3"
     ],
     "class": "unit",
     "deciding": [
      "MS-2"
     ],
     "error_items": [
      "MS-2"
     ],
     "expected_check": "units",
     "gate_blocking": [],
     "named": true,
     "records": 97,
     "review": "fail",
     "review_cause": null,
     "role": "mechanical",
     "twin_gate_failing_records": 0,
     "twin_records": 97,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 84
    },
    {
     "approved": false,
     "artefact": "a07",
     "caught": false,
     "cited_at_all": true,
     "cited_by_review": [
      "MA-10",
      "MH-1",
      "MH-2",
      "MS-1",
      "MS-28",
      "MS-3",
      "MS-4"
     ],
     "cited_by_twin_review": [
      "MA-10",
      "MS-28"
     ],
     "class": "equilibrium",
     "deciding": [
      "MS-4"
     ],
     "error_items": [
      "MS-4"
     ],
     "expected_check": "equilibrium",
     "gate_blocking": [],
     "named": true,
     "records": 116,
     "review": "fail",
     "review_cause": null,
     "role": "mechanical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": false,
     "unchecked_records": 103
    },
    {
     "approved": false,
     "artefact": "a08",
     "caught": false,
     "cited_at_all": null,
     "cited_by_review": [
      "EA-9",
      "EH-1",
      "EH-2",
      "EH-6",
      "EP-5",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21",
      "ES-32"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "EH-6",
      "EP-4",
      "EP-5",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-5"
     ],
     "class": "equilibrium",
     "deciding": [],
     "error_items": [],
     "expected_check": "equilibrium",
     "gate_blocking": [],
     "named": null,
     "records": 116,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": false,
     "unchecked_records": 103
    },
    {
     "approved": false,
     "artefact": "a09",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "MA-10",
      "MS-1",
      "MS-28",
      "MS-3"
     ],
     "cited_by_twin_review": [
      "MA-10",
      "MP-8",
      "MS-24",
      "MS-28"
     ],
     "class": "equilibrium",
     "deciding": [],
     "error_items": [
      "MS-4"
     ],
     "expected_check": "equilibrium",
     "gate_blocking": [],
     "named": false,
     "records": 116,
     "review": "fail",
     "review_cause": null,
     "role": "mechanical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": false,
     "unchecked_records": 103
    },
    {
     "approved": false,
     "artefact": "a10",
     "caught": true,
     "cited_at_all": false,
     "cited_by_review": [
      "EA-9",
      "EH-6",
      "EP-5",
      "ES-14",
      "ES-15",
      "ES-16"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "EH-1",
      "EP-5",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21"
     ],
     "class": "equilibrium",
     "deciding": [],
     "error_items": [
      "ES-7",
      "ES-9",
      "ES-33"
     ],
     "expected_check": "conservation",
     "gate_blocking": [
      "conservation"
     ],
     "named": false,
     "records": 112,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 99
    },
    {
     "approved": false,
     "artefact": "a11",
     "caught": false,
     "cited_at_all": true,
     "cited_by_review": [
      "MA-10",
      "MH-2",
      "MH-5",
      "MS-1",
      "MS-14",
      "MS-15",
      "MS-28",
      "MS-3",
      "MS-4"
     ],
     "cited_by_twin_review": [
      "MA-10",
      "MS-28",
      "MS-6"
     ],
     "class": "equilibrium",
     "deciding": [
      "MS-4"
     ],
     "error_items": [
      "MS-4"
     ],
     "expected_check": "equilibrium",
     "gate_blocking": [],
     "named": true,
     "records": 116,
     "review": "fail",
     "review_cause": null,
     "role": "mechanical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": false,
     "unchecked_records": 103
    },
    {
     "approved": false,
     "artefact": "a12",
     "caught": false,
     "cited_at_all": null,
     "cited_by_review": [
      "EA-9",
      "EH-6",
      "EP-4",
      "EP-5",
      "ES-1",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21",
      "ES-7",
      "ES-8"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "EH-1",
      "EH-6",
      "EP-4",
      "EP-5",
      "ES-14",
      "ES-15",
      "ES-16"
     ],
     "class": "equilibrium",
     "deciding": [],
     "error_items": [],
     "expected_check": "equilibrium",
     "gate_blocking": [],
     "named": null,
     "records": 116,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": false,
     "unchecked_records": 103
    },
    {
     "approved": false,
     "artefact": "a13",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "MA-10",
      "MP-3",
      "MS-26",
      "MS-28",
      "MS-3",
      "MS-5"
     ],
     "cited_by_twin_review": [
      "MA-10",
      "MS-28",
      "MS-6"
     ],
     "class": "equilibrium",
     "deciding": [
      "MS-26",
      "MS-3"
     ],
     "error_items": [
      "MS-3",
      "MS-26"
     ],
     "expected_check": "conservation",
     "gate_blocking": [
      "conservation"
     ],
     "named": true,
     "records": 112,
     "review": "fail",
     "review_cause": null,
     "role": "mechanical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 99
    },
    {
     "approved": false,
     "artefact": "a14",
     "caught": false,
     "cited_at_all": null,
     "cited_by_review": [
      "EA-9",
      "EH-1",
      "EP-5",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "EP-4",
      "EP-5",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21"
     ],
     "class": "equilibrium",
     "deciding": [],
     "error_items": [],
     "expected_check": "equilibrium",
     "gate_blocking": [],
     "named": null,
     "records": 116,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 116,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": false,
     "unchecked_records": 103
    },
    {
     "approved": false,
     "artefact": "a15",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "EA-9",
      "EH-5",
      "EH-6",
      "EP-4",
      "EP-5",
      "ES-1",
      "ES-10",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21",
      "ES-33",
      "ES-34",
      "ES-5",
      "ES-7",
      "ES-8"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "EH-1",
      "EH-6",
      "EP-4",
      "EP-5",
      "ES-10",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-17",
      "ES-21",
      "ES-28",
      "ES-33",
      "ES-5",
      "ES-6",
      "ES-7",
      "ES-9"
     ],
     "class": "propagation",
     "deciding": [
      "ES-34"
     ],
     "error_items": [
      "ES-34"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 90,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 92,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 76
    },
    {
     "approved": false,
     "artefact": "a16",
     "caught": false,
     "cited_at_all": null,
     "cited_by_review": [
      "EA-9",
      "EH-1",
      "EP-4",
      "EP-5",
      "ES-10",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-28",
      "ES-32",
      "ES-5",
      "ES-6",
      "ES-7"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "EH-1",
      "EH-6",
      "EP-4",
      "EP-5",
      "ES-10",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-19",
      "ES-21",
      "ES-35",
      "ES-5",
      "ES-7",
      "ES-8"
     ],
     "class": "equilibrium",
     "deciding": [],
     "error_items": [],
     "expected_check": "equilibrium",
     "gate_blocking": [],
     "named": null,
     "records": 118,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 118,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": false,
     "unchecked_records": 105
    },
    {
     "approved": false,
     "artefact": "a17",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "EA-2",
      "EA-9",
      "EH-5",
      "ES-34"
     ],
     "cited_by_twin_review": [],
     "class": "propagation",
     "deciding": [
      "ES-34"
     ],
     "error_items": [
      "ES-34"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 83,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 84,
     "twin_review": "pass",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 70
    },
    {
     "approved": false,
     "artefact": "a18",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "AC-9",
      "DS-30",
      "DS-4"
     ],
     "cited_by_twin_review": [],
     "class": "propagation",
     "deciding": [
      "DS-30"
     ],
     "error_items": [
      "DS-30"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 82,
     "review": "fail",
     "review_cause": null,
     "role": "firmware",
     "twin_gate_failing_records": 0,
     "twin_records": 84,
     "twin_review": "pass",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 69
    },
    {
     "approved": false,
     "artefact": "a19",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "A7",
      "D28"
     ],
     "cited_by_twin_review": [],
     "class": "propagation",
     "deciding": [
      "D28"
     ],
     "error_items": [
      "D28"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 72,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 78,
     "twin_review": "pass",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 59
    },
    {
     "approved": false,
     "artefact": "a20",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "AC-9",
      "DS-1",
      "DS-10",
      "DS-2",
      "DS-27",
      "DS-29",
      "DS-4",
      "DS-5",
      "RH-2"
     ],
     "cited_by_twin_review": [
      "AC-9",
      "DS-1",
      "DS-4",
      "DS-5"
     ],
     "class": "unit",
     "deciding": [
      "DS-27"
     ],
     "error_items": [
      "DS-27"
     ],
     "expected_check": "units",
     "gate_blocking": [
      "units"
     ],
     "named": true,
     "records": 86,
     "review": "fail",
     "review_cause": null,
     "role": "firmware",
     "twin_gate_failing_records": 0,
     "twin_records": 86,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 73
    },
    {
     "approved": false,
     "artefact": "a21",
     "caught": false,
     "cited_at_all": true,
     "cited_by_review": [
      "A7",
      "D17",
      "D22",
      "D23",
      "D25",
      "D28",
      "D29",
      "D30",
      "D33",
      "D6",
      "R1",
      "S2",
      "S4",
      "S5"
     ],
     "cited_by_twin_review": [
      "A7",
      "D13",
      "D17",
      "D22",
      "D23",
      "D29",
      "D30",
      "D33",
      "D6",
      "S5"
     ],
     "class": "unit",
     "deciding": [
      "D25"
     ],
     "error_items": [
      "D25",
      "D26"
     ],
     "expected_check": "units",
     "gate_blocking": [],
     "named": true,
     "records": 86,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 86,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 73
    },
    {
     "approved": false,
     "artefact": "a22",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D13",
      "D17",
      "D30",
      "D6",
      "R9",
      "S5"
     ],
     "cited_by_twin_review": [
      "A7",
      "D1",
      "D10",
      "D11",
      "D13",
      "D14",
      "D17",
      "D22",
      "D23",
      "D24",
      "D29",
      "D3",
      "D30",
      "D32",
      "D33",
      "D4",
      "D5",
      "D6",
      "D7",
      "D8",
      "D9",
      "S2",
      "S4",
      "S5"
     ],
     "class": "magnitude",
     "deciding": [],
     "error_items": [
      "D25",
      "D27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [],
     "named": false,
     "records": 86,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 86,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 73
    },
    {
     "approved": false,
     "artefact": "a23",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "S5"
     ],
     "cited_by_twin_review": [
      "A7",
      "D10",
      "D11",
      "D13",
      "D17",
      "D22",
      "D23",
      "D24",
      "D3",
      "D30",
      "D33",
      "D4",
      "D5",
      "D6",
      "D7",
      "D8",
      "D9",
      "R1",
      "S2",
      "S4",
      "S5"
     ],
     "class": "unit",
     "deciding": [],
     "error_items": [
      "D25",
      "D26"
     ],
     "expected_check": "units",
     "gate_blocking": [],
     "named": false,
     "records": 91,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 91,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 78
    },
    {
     "approved": false,
     "artefact": "a24",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "A7",
      "D17",
      "D22",
      "D23",
      "D25",
      "D28",
      "D30",
      "D33",
      "D6",
      "S5"
     ],
     "cited_by_twin_review": [
      "A7",
      "D1",
      "D10",
      "D11",
      "D13",
      "D17",
      "D22",
      "D23",
      "D24",
      "D29",
      "D3",
      "D30",
      "D32",
      "D33",
      "D4",
      "D5",
      "D6",
      "D7",
      "D8",
      "D9",
      "S2",
      "S4",
      "S5"
     ],
     "class": "magnitude",
     "deciding": [
      "D25"
     ],
     "error_items": [
      "D25",
      "D27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [
      "magnitude"
     ],
     "named": true,
     "records": 91,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 91,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 78
    },
    {
     "approved": false,
     "artefact": "a25",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "A7",
      "D1",
      "D10",
      "D11",
      "D12",
      "D13",
      "D14",
      "D16",
      "D17",
      "D22",
      "D23",
      "D24",
      "D25",
      "D28",
      "D29",
      "D3",
      "D30",
      "D32",
      "D33",
      "D4",
      "D5",
      "D6",
      "D7",
      "D8",
      "D9",
      "R2",
      "R9",
      "S2",
      "S4",
      "S5"
     ],
     "cited_by_twin_review": [
      "A7",
      "D1",
      "D10",
      "D11",
      "D13",
      "D17",
      "D29",
      "D30",
      "D33",
      "D6",
      "D7",
      "D8",
      "D9",
      "R1",
      "S2",
      "S4",
      "S5"
     ],
     "class": "unit",
     "deciding": [
      "D25"
     ],
     "error_items": [
      "D25",
      "D26"
     ],
     "expected_check": "units",
     "gate_blocking": [
      "units"
     ],
     "named": true,
     "records": 79,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 79,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 66
    },
    {
     "approved": false,
     "artefact": "a26",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "A7",
      "D1",
      "D10",
      "D11",
      "D12",
      "D13",
      "D14",
      "D17",
      "D23",
      "D28",
      "D29",
      "D3",
      "D30",
      "D33",
      "D4",
      "D5",
      "D6",
      "D7",
      "D8",
      "D9",
      "S2",
      "S4",
      "S5"
     ],
     "cited_by_twin_review": [
      "A7",
      "D10",
      "D11",
      "D12",
      "D13",
      "D14",
      "D15",
      "D17",
      "D23",
      "D24",
      "D29",
      "D3",
      "D30",
      "D33",
      "D4",
      "D5",
      "D6",
      "D7",
      "D8",
      "D9",
      "R1",
      "R2",
      "S2",
      "S4",
      "S5"
     ],
     "class": "propagation",
     "deciding": [
      "D28"
     ],
     "error_items": [
      "D28"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 76,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 79,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 63
    },
    {
     "approved": false,
     "artefact": "a27",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D1",
      "D10",
      "D11",
      "D13",
      "D14",
      "D17",
      "D22",
      "D23",
      "D24",
      "D29",
      "D3",
      "D30",
      "D33",
      "D4",
      "D5",
      "D6",
      "D7",
      "D8",
      "D9",
      "R1",
      "S2",
      "S4",
      "S5",
      "consistency"
     ],
     "cited_by_twin_review": [
      "A7",
      "D1",
      "D10",
      "D11",
      "D13",
      "D14",
      "D17",
      "D18",
      "D21",
      "D23",
      "D24",
      "D29",
      "D3",
      "D30",
      "D32",
      "D33",
      "D4",
      "D5",
      "D6",
      "D7",
      "D8",
      "S2",
      "S4",
      "S5"
     ],
     "class": "magnitude",
     "deciding": [],
     "error_items": [
      "D25",
      "D27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [],
     "named": false,
     "records": 79,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 79,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 66
    },
    {
     "approved": false,
     "artefact": "a28",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D1",
      "D10",
      "D11",
      "D12",
      "D13",
      "D14",
      "D17",
      "D22",
      "D23",
      "D24",
      "D29",
      "D3",
      "D30",
      "D33",
      "D4",
      "D5",
      "D6",
      "D7",
      "D8",
      "D9",
      "R2",
      "S2",
      "S4",
      "S5"
     ],
     "cited_by_twin_review": [
      "A7",
      "D1",
      "D13",
      "D17",
      "D22",
      "D23",
      "D24",
      "D29",
      "D30",
      "D33",
      "D6",
      "D8",
      "D9",
      "R1",
      "R2",
      "S2",
      "S4",
      "S5"
     ],
     "class": "magnitude",
     "deciding": [],
     "error_items": [
      "D25",
      "D27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [],
     "named": false,
     "records": 79,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 79,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 66
    },
    {
     "approved": false,
     "artefact": "a29",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "EA-9",
      "EH-3",
      "EP-3",
      "ES-1",
      "ES-3",
      "ES-31",
      "ES-32",
      "ES-4"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "EH-3",
      "EP-3",
      "ES-1",
      "ES-21",
      "ES-3",
      "ES-4"
     ],
     "class": "unit",
     "deciding": [
      "ES-31",
      "ES-32"
     ],
     "error_items": [
      "ES-31",
      "ES-32"
     ],
     "expected_check": "units",
     "gate_blocking": [
      "units",
      "propagation"
     ],
     "named": true,
     "records": 78,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 79,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 65
    },
    {
     "approved": false,
     "artefact": "a30",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "MA-10",
      "MH-8",
      "MS-29",
      "MS-30",
      "MS-31",
      "MS-5"
     ],
     "cited_by_twin_review": [],
     "class": "propagation",
     "deciding": [
      "MS-5"
     ],
     "error_items": [
      "MS-5"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 79,
     "review": "fail",
     "review_cause": null,
     "role": "mechanical",
     "twin_gate_failing_records": 0,
     "twin_records": 81,
     "twin_review": "pass",
     "twin_review_cause": null,
     "unchecked_on_expected_check": false,
     "unchecked_records": 66
    },
    {
     "approved": false,
     "artefact": "a31",
     "caught": false,
     "cited_at_all": true,
     "cited_by_review": [
      "AC-9",
      "DS-27",
      "RH-2"
     ],
     "cited_by_twin_review": [
      "AC-9",
      "DS-27",
      "RH-2"
     ],
     "class": "magnitude",
     "deciding": [],
     "error_items": [
      "DS-27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [],
     "named": false,
     "records": 72,
     "review": "fail",
     "review_cause": null,
     "role": "firmware",
     "twin_gate_failing_records": 0,
     "twin_records": 72,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 59
    },
    {
     "approved": false,
     "artefact": "a32",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D28",
      "R10",
      "R7",
      "R9"
     ],
     "cited_by_twin_review": [
      "A7",
      "D28"
     ],
     "class": "magnitude",
     "deciding": [],
     "error_items": [
      "D25",
      "D27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [],
     "named": false,
     "records": 75,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 75,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 62
    },
    {
     "approved": false,
     "artefact": "a33",
     "caught": false,
     "cited_at_all": true,
     "cited_by_review": [
      "A7",
      "D25",
      "D28",
      "R9",
      "S5"
     ],
     "cited_by_twin_review": [
      "D1",
      "D10",
      "D11",
      "D13",
      "D14",
      "D17",
      "D23",
      "D24",
      "D29",
      "D3",
      "D30",
      "D32",
      "D33",
      "D4",
      "D5",
      "D6",
      "D7",
      "D8",
      "D9",
      "R1",
      "S2",
      "S4",
      "S5"
     ],
     "class": "magnitude",
     "deciding": [
      "D25"
     ],
     "error_items": [
      "D25",
      "D27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [],
     "named": true,
     "records": 86,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 86,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 73
    },
    {
     "approved": false,
     "artefact": "a34",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D1",
      "D13",
      "D15",
      "D17",
      "D23",
      "D24",
      "D28",
      "D29",
      "D30",
      "D32",
      "D33",
      "D6",
      "R11",
      "R9",
      "S2",
      "S4",
      "S5"
     ],
     "cited_by_twin_review": [
      "A7",
      "D17",
      "D30",
      "D6",
      "R1",
      "R11",
      "S5"
     ],
     "class": "magnitude",
     "deciding": [],
     "error_items": [
      "D25",
      "D27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [],
     "named": false,
     "records": 86,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 86,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 73
    },
    {
     "approved": false,
     "artefact": "a35",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "EA-9",
      "EH-1",
      "EH-6",
      "EP-4",
      "EP-5",
      "ES-10",
      "ES-11",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21",
      "ES-28",
      "ES-34",
      "ES-7"
     ],
     "cited_by_twin_review": [
      "EA-9",
      "EH-6",
      "EP-4",
      "EP-5",
      "ES-1",
      "ES-10",
      "ES-11",
      "ES-13",
      "ES-14",
      "ES-15",
      "ES-16",
      "ES-21",
      "ES-27",
      "ES-28",
      "ES-33",
      "ES-5",
      "ES-6",
      "ES-7",
      "ES-8"
     ],
     "class": "propagation",
     "deciding": [
      "ES-34"
     ],
     "error_items": [
      "ES-34"
     ],
     "expected_check": "propagation",
     "gate_blocking": [
      "propagation"
     ],
     "named": true,
     "records": 116,
     "review": "fail",
     "review_cause": null,
     "role": "electrical",
     "twin_gate_failing_records": 0,
     "twin_records": 118,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 103
    },
    {
     "approved": false,
     "artefact": "a36",
     "caught": true,
     "cited_at_all": true,
     "cited_by_review": [
      "A7",
      "D25"
     ],
     "cited_by_twin_review": [],
     "class": "unit",
     "deciding": [
      "D25"
     ],
     "error_items": [
      "D25",
      "D26"
     ],
     "expected_check": "units",
     "gate_blocking": [
      "units"
     ],
     "named": true,
     "records": 86,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 86,
     "twin_review": "blocked",
     "twin_review_cause": "blocking_spec_defect",
     "unchecked_on_expected_check": true,
     "unchecked_records": 73
    },
    {
     "approved": false,
     "artefact": "a37",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7",
      "D1",
      "D10",
      "D11",
      "D13",
      "D17",
      "D21",
      "D22",
      "D23",
      "D24",
      "D29",
      "D3",
      "D30",
      "D32",
      "D33",
      "D4",
      "D5",
      "D6",
      "D7",
      "D8",
      "D9",
      "R1",
      "R2",
      "S2",
      "S4",
      "S5"
     ],
     "cited_by_twin_review": [
      "A7",
      "D10",
      "D11",
      "D13",
      "D14",
      "D17",
      "D22",
      "D23",
      "D24",
      "D3",
      "D30",
      "D33",
      "D4",
      "D5",
      "D6",
      "D7",
      "D8",
      "D9",
      "R1",
      "S2",
      "S4",
      "S5"
     ],
     "class": "magnitude",
     "deciding": [],
     "error_items": [
      "D25",
      "D27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [],
     "named": false,
     "records": 79,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 79,
     "twin_review": "fail",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 66
    },
    {
     "approved": false,
     "artefact": "a38",
     "caught": false,
     "cited_at_all": false,
     "cited_by_review": [
      "A7"
     ],
     "cited_by_twin_review": [],
     "class": "magnitude",
     "deciding": [],
     "error_items": [
      "D25",
      "D27"
     ],
     "expected_check": "magnitude",
     "gate_blocking": [],
     "named": false,
     "records": 75,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 75,
     "twin_review": "blocked",
     "twin_review_cause": "blocking_spec_defect",
     "unchecked_on_expected_check": true,
     "unchecked_records": 62
    },
    {
     "approved": false,
     "artefact": "a39",
     "caught": false,
     "cited_at_all": true,
     "cited_by_review": [
      "A7",
      "D21",
      "D25",
      "S5"
     ],
     "cited_by_twin_review": [],
     "class": "unit",
     "deciding": [
      "D25"
     ],
     "error_items": [
      "D25",
      "D26"
     ],
     "expected_check": "units",
     "gate_blocking": [],
     "named": true,
     "records": 75,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 75,
     "twin_review": "blocked",
     "twin_review_cause": "blocking_spec_defect",
     "unchecked_on_expected_check": true,
     "unchecked_records": 62
    },
    {
     "approved": false,
     "artefact": "a40",
     "caught": false,
     "cited_at_all": true,
     "cited_by_review": [
      "A7",
      "D25",
      "R9"
     ],
     "cited_by_twin_review": [],
     "class": "unit",
     "deciding": [
      "D25"
     ],
     "error_items": [
      "D25",
      "D26"
     ],
     "expected_check": "units",
     "gate_blocking": [],
     "named": true,
     "records": 86,
     "review": "fail",
     "review_cause": null,
     "role": "control",
     "twin_gate_failing_records": 0,
     "twin_records": 86,
     "twin_review": "pass",
     "twin_review_cause": null,
     "unchecked_on_expected_check": true,
     "unchecked_records": 73
    }
   ],
   "secondary": {
    "s6_10_named_against_caught": {
     "cited_at_all": 25,
     "named": 24,
     "no_error_item": 4,
     "per_class": {
      "equilibrium": {
       "caught_not_named": 1,
       "named_and_caught": 1,
       "named_not_caught": 2,
       "neither": 2,
       "no_error_item": 4
      },
      "magnitude": {
       "caught_not_named": 0,
       "named_and_caught": 1,
       "named_not_caught": 1,
       "neither": 8,
       "no_error_item": 0
      },
      "propagation": {
       "caught_not_named": 0,
       "named_and_caught": 10,
       "named_not_caught": 0,
       "neither": 0,
       "no_error_item": 0
      },
      "unit": {
       "caught_not_named": 0,
       "named_and_caught": 4,
       "named_not_caught": 5,
       "neither": 1,
       "no_error_item": 0
      }
     },
     "per_role": {
      "control": {
       "caught_not_named": 0,
       "named_and_caught": 5,
       "named_not_caught": 4,
       "neither": 8,
       "no_error_item": 0
      },
      "electrical": {
       "caught_not_named": 1,
       "named_and_caught": 6,
       "named_not_caught": 0,
       "neither": 0,
       "no_error_item": 4
      },
      "firmware": {
       "caught_not_named": 0,
       "named_and_caught": 2,
       "named_not_caught": 0,
       "neither": 1,
       "no_error_item": 0
      },
      "mechanical": {
       "caught_not_named": 0,
       "named_and_caught": 3,
       "named_not_caught": 4,
       "neither": 2,
       "no_error_item": 0
      }
     },
     "without_twin_condition": {
      "per_class": {
       "equilibrium": {
        "caught_not_named": 1,
        "named_and_caught": 1,
        "named_not_caught": 2,
        "neither": 2,
        "no_error_item": 4
       },
       "magnitude": {
        "caught_not_named": 0,
        "named_and_caught": 1,
        "named_not_caught": 2,
        "neither": 7,
        "no_error_item": 0
       },
       "propagation": {
        "caught_not_named": 0,
        "named_and_caught": 10,
        "named_not_caught": 0,
        "neither": 0,
        "no_error_item": 0
       },
       "unit": {
        "caught_not_named": 0,
        "named_and_caught": 4,
        "named_not_caught": 5,
        "neither": 1,
        "no_error_item": 0
       }
      },
      "per_role": {
       "control": {
        "caught_not_named": 0,
        "named_and_caught": 5,
        "named_not_caught": 4,
        "neither": 8,
        "no_error_item": 0
       },
       "electrical": {
        "caught_not_named": 1,
        "named_and_caught": 6,
        "named_not_caught": 0,
        "neither": 0,
        "no_error_item": 4
       },
       "firmware": {
        "caught_not_named": 0,
        "named_and_caught": 2,
        "named_not_caught": 1,
        "neither": 0,
        "no_error_item": 0
       },
       "mechanical": {
        "caught_not_named": 0,
        "named_and_caught": 3,
        "named_not_caught": 4,
        "neither": 2,
        "no_error_item": 0
       }
      }
     }
    },
    "s6_1_per_class": {
     "equilibrium": {
      "A": 0,
      "C": 0,
      "artefacts": 10
     },
     "magnitude": {
      "A": 0,
      "C": 0,
      "artefacts": 10
     },
     "propagation": {
      "A": 0,
      "C": 0,
      "artefacts": 10
     },
     "unit": {
      "A": 0,
      "C": 0,
      "artefacts": 10
     }
    },
    "s6_5_gate_caught_by_review_outcome": {
     "blocked": {
      "artefacts": 0,
      "caught": 0
     },
     "fail": {
      "artefacts": 40,
      "caught": 17
     },
     "pass": {
      "artefacts": 0,
      "caught": 0
     },
     "review_unavailable": {
      "artefacts": 0,
      "caught": 0
     }
    },
    "s6_7_twin_reviews": {
     "of": 40,
     "outcomes": {
      "blocked": 3,
      "fail": 32,
      "pass": 5
     },
     "refused": 32
    },
    "s6_8_per_role": {
     "control": {
      "A": 0,
      "C": 0,
      "artefacts": 17
     },
     "electrical": {
      "A": 0,
      "C": 0,
      "artefacts": 11
     },
     "firmware": {
      "A": 0,
      "C": 0,
      "artefacts": 3
     },
     "mechanical": {
      "A": 0,
      "C": 0,
      "artefacts": 9
     }
    },
    "s6_9_not_judged_per_role": {
     "control": {
      "artefacts": {
       "blocked": [],
       "review_unavailable": []
      },
      "twins": {
       "blocked": [
        [
         "a36",
         "blocking_spec_defect"
        ],
        [
         "a38",
         "blocking_spec_defect"
        ],
        [
         "a39",
         "blocking_spec_defect"
        ]
       ],
       "review_unavailable": []
      }
     },
     "electrical": {
      "artefacts": {
       "blocked": [],
       "review_unavailable": []
      },
      "twins": {
       "blocked": [],
       "review_unavailable": []
      }
     },
     "firmware": {
      "artefacts": {
       "blocked": [],
       "review_unavailable": []
      },
      "twins": {
       "blocked": [],
       "review_unavailable": []
      }
     },
     "mechanical": {
      "artefacts": {
       "blocked": [],
       "review_unavailable": []
      },
      "twins": {
       "blocked": [],
       "review_unavailable": []
      }
     }
    }
   }
  }
 },
 "primary_delta_C": {
  "bootstrap": {
   "high": 0.0,
   "low": 0.0,
   "undefined_draws": 0
  },
  "discordant_F_not_I": 0,
  "discordant_I_not_F": 0,
  "exact_p": 1.0,
  "largest_effects_not_excluded": [
   0.0,
   0.0
  ],
  "newcombe_per_round": {
   "1": {
    "difference": 0.0,
    "high": 3.5048640478914654,
    "low": -3.5048640478914654
   },
   "2": {
    "difference": 0.0,
    "high": 3.5048640478914654,
    "low": -3.5048640478914654
   }
  },
  "pairs_tested": 34,
  "shown": false,
  "value": 0.0
 },
 "results_2_3_4_6_printed_once": {
  "s6_2_expected_check": {
   "all_caught": 17,
   "among_all_caught": 17,
   "caught_on_another_check": []
  },
  "s6_3_unchecked": {
   "equilibrium": {
    "not_judged_on_expected_check": [],
    "unchecked_records": 1005
   },
   "magnitude": {
    "not_judged_on_expected_check": [
     "a22",
     "a27",
     "a28",
     "a31",
     "a32",
     "a33",
     "a34",
     "a37",
     "a38"
    ],
    "unchecked_records": 678
   },
   "propagation": {
    "not_judged_on_expected_check": [],
    "unchecked_records": 792
   },
   "unit": {
    "not_judged_on_expected_check": [
     "a04",
     "a06",
     "a21",
     "a23",
     "a39",
     "a40"
    ],
    "unchecked_records": 731
   }
  },
  "s6_4_propagation_edges_by_domain_pair": {
   "control -> firmware": [
    "a03",
    "a19",
    "a26"
   ],
   "electrical -> control": [
    "a18"
   ],
   "electrical -> firmware": [
    "a15",
    "a17"
   ],
   "electrical -> mechanical": [
    "a01",
    "a02",
    "a35"
   ],
   "mechanical -> control": [
    "a30"
   ]
  },
  "s6_6_gate_events_and_records": {
   "artefacts_caught": 17,
   "controls_failing_records": 0,
   "controls_gate_lines": 40,
   "controls_records": 3758,
   "injected_failing_records": 26,
   "injected_gate_lines": 40,
   "injected_records": 3727
  }
 },
 "rounds": [
  1,
  2
 ],
 "secondary": {
  "blocked_and_unavailable": {
   "F1": {
    "control": {
     "artefacts": {
      "blocked": [],
      "review_unavailable": []
     },
     "twins": {
      "blocked": [
       [
        "a19",
        "blocking_spec_defect"
       ],
       [
        "a32",
        "blocking_spec_defect"
       ],
       [
        "a36",
        "blocking_spec_defect"
       ],
       [
        "a38",
        "blocking_spec_defect"
       ],
       [
        "a39",
        "blocking_spec_defect"
       ]
      ],
      "review_unavailable": [
       [
        "a40",
        "invalid_verdict"
       ]
      ]
     }
    },
    "electrical": {
     "artefacts": {
      "blocked": [],
      "review_unavailable": []
     },
     "twins": {
      "blocked": [],
      "review_unavailable": [
       [
        "a16",
        "invalid_verdict"
       ]
      ]
     }
    },
    "firmware": {
     "artefacts": {
      "blocked": [],
      "review_unavailable": []
     },
     "twins": {
      "blocked": [],
      "review_unavailable": []
     }
    },
    "mechanical": {
     "artefacts": {
      "blocked": [],
      "review_unavailable": []
     },
     "twins": {
      "blocked": [],
      "review_unavailable": []
     }
    }
   },
   "F2": {
    "control": {
     "artefacts": {
      "blocked": [],
      "review_unavailable": []
     },
     "twins": {
      "blocked": [
       [
        "a19",
        "blocking_spec_defect"
       ],
       [
        "a32",
        "blocking_spec_defect"
       ],
       [
        "a36",
        "blocking_spec_defect"
       ],
       [
        "a38",
        "blocking_spec_defect"
       ],
       [
        "a39",
        "blocking_spec_defect"
       ]
      ],
      "review_unavailable": []
     }
    },
    "electrical": {
     "artefacts": {
      "blocked": [],
      "review_unavailable": []
     },
     "twins": {
      "blocked": [],
      "review_unavailable": []
     }
    },
    "firmware": {
     "artefacts": {
      "blocked": [],
      "review_unavailable": []
     },
     "twins": {
      "blocked": [],
      "review_unavailable": []
     }
    },
    "mechanical": {
     "artefacts": {
      "blocked": [],
      "review_unavailable": []
     },
     "twins": {
      "blocked": [],
      "review_unavailable": []
     }
    }
   },
   "I1": {
    "control": {
     "artefacts": {
      "blocked": [],
      "review_unavailable": [
       [
        "a19",
        "invalid_verdict"
       ]
      ]
     },
     "twins": {
      "blocked": [
       [
        "a19",
        "blocking_spec_defect"
       ],
       [
        "a32",
        "blocking_spec_defect"
       ],
       [
        "a38",
        "blocking_spec_defect"
       ],
       [
        "a39",
        "blocking_spec_defect"
       ]
      ],
      "review_unavailable": [
       [
        "a27",
        "invalid_verdict"
       ]
      ]
     }
    },
    "electrical": {
     "artefacts": {
      "blocked": [],
      "review_unavailable": []
     },
     "twins": {
      "blocked": [],
      "review_unavailable": [
       [
        "a08",
        "invalid_verdict"
       ]
      ]
     }
    },
    "firmware": {
     "artefacts": {
      "blocked": [],
      "review_unavailable": []
     },
     "twins": {
      "blocked": [],
      "review_unavailable": []
     }
    },
    "mechanical": {
     "artefacts": {
      "blocked": [],
      "review_unavailable": []
     },
     "twins": {
      "blocked": [],
      "review_unavailable": [
       [
        "a11",
        "invalid_verdict"
       ]
      ]
     }
    }
   },
   "I2": {
    "control": {
     "artefacts": {
      "blocked": [],
      "review_unavailable": []
     },
     "twins": {
      "blocked": [
       [
        "a36",
        "blocking_spec_defect"
       ],
       [
        "a38",
        "blocking_spec_defect"
       ],
       [
        "a39",
        "blocking_spec_defect"
       ]
      ],
      "review_unavailable": []
     }
    },
    "electrical": {
     "artefacts": {
      "blocked": [],
      "review_unavailable": []
     },
     "twins": {
      "blocked": [],
      "review_unavailable": []
     }
    },
    "firmware": {
     "artefacts": {
      "blocked": [],
      "review_unavailable": []
     },
     "twins": {
      "blocked": [],
      "review_unavailable": []
     }
    },
    "mechanical": {
     "artefacts": {
      "blocked": [],
      "review_unavailable": []
     },
     "twins": {
      "blocked": [],
      "review_unavailable": []
     }
    }
   }
  },
  "delta_A": {
   "bootstrap": {
    "high": 1.5,
    "low": 0.0,
    "undefined_draws": 0
   },
   "discordant_F_not_I": 1,
   "discordant_I_not_F": 0,
   "exact_p": 1.0,
   "largest_effects_not_excluded": [
    0.0,
    1.5
   ],
   "newcombe_per_round": {
    "1": {
     "difference": 0.0,
     "high": 3.5048640478914654,
     "low": -3.5048640478914654
    },
    "2": {
     "difference": 1.0,
     "high": 5.1525475853896365,
     "low": -2.6001778308067847
    }
   },
   "pairs_tested": 80,
   "shown": false,
   "value": 0.5
  },
  "delta_CNN": {
   "bootstrap": {
    "high": 1.0,
    "low": -3.0,
    "undefined_draws": 0
   },
   "discordant_F_not_I": 1,
   "discordant_I_not_F": 3,
   "exact_p": 0.625,
   "largest_effects_not_excluded": [
    -3.0,
    1.0
   ],
   "newcombe_per_round": {
    "1": {
     "difference": -3.0,
     "high": 0.6404435951488041,
     "low": -7.53271033198706
    },
    "2": {
     "difference": 1.0,
     "high": 5.070052142113245,
     "low": -2.3089231597293796
    }
   },
   "pairs_tested": 34,
   "shown": false,
   "value": -1.0
  },
  "delta_C_among_rejected": {
   "bootstrap": {
    "high": 1.5,
    "low": 0.0,
    "undefined_draws": 0
   },
   "discordant_F_not_I": 1,
   "discordant_I_not_F": 0,
   "exact_p": 1.0,
   "largest_effects_not_excluded": [
    0.0,
    1.5
   ],
   "newcombe_per_round": {
    "1": {
     "difference": 0.9999999999999987,
     "high": 2.949180877902562,
     "low": -0.9461388226549858
    },
    "2": {
     "difference": 0.0,
     "high": 0.5257296071837196,
     "low": -0.5257296071837196
    }
   },
   "pairs_tested": 80,
   "shown": false,
   "value": 0.5
  },
  "delta_T": {
   "bootstrap": {
    "high": -1.0,
    "low": -5.5,
    "undefined_draws": 0
   },
   "discordant_F_not_I": 0,
   "discordant_I_not_F": 6,
   "exact_p": 0.03125,
   "largest_effects_not_excluded": null,
   "newcombe_per_round": {
    "1": {
     "difference": -1.9999999999999998,
     "high": 1.45346507697639,
     "low": -6.534270994307461
    },
    "2": {
     "difference": -4.0,
     "high": -0.09285937620678086,
     "low": -9.15043570634704
    }
   },
   "pairs_tested": 80,
   "shown": true,
   "value": -3.0
  },
  "delta_cited_without_the_twin_condition": {
   "bootstrap": {
    "high": 1.5,
    "low": -5.0,
    "undefined_draws": 0
   },
   "discordant_F_not_I": 3,
   "discordant_I_not_F": 6,
   "exact_p": 0.5078125,
   "largest_effects_not_excluded": [
    -5.0,
    1.5
   ],
   "newcombe_per_round": {
    "1": {
     "difference": 1.0000000000000009,
     "high": 4.206626117326675,
     "low": -2.2540922526953455
    },
    "2": {
     "difference": -3.999999999999999,
     "high": 0.5791660972652896,
     "low": -8.347600639498504
    }
   },
   "pairs_tested": 80,
   "shown": false,
   "value": -1.5
  },
  "delta_named": {
   "bootstrap": {
    "high": 4.0,
    "low": -4.0,
    "undefined_draws": 0
   },
   "discordant_F_not_I": 6,
   "discordant_I_not_F": 6,
   "exact_p": 1.0,
   "largest_effects_not_excluded": [
    -4.0,
    4.0
   ],
   "newcombe_per_round": {
    "1": {
     "difference": 3.0000000000000004,
     "high": 7.012686425366837,
     "low": -1.188103598012965
    },
    "2": {
     "difference": -2.9999999999999982,
     "high": 1.995208807232343,
     "low": -7.792463027664046
    }
   },
   "pairs_tested": 80,
   "shown": false,
   "value": 0.0
  },
  "lag_F_minus_I_s": {
   "round 1": {
    "injected": {
     "max_s": 1340.8382556438446,
     "median_s": 573.4321703910828,
     "min_s": -785.4108374118805,
     "pairs": 40,
     "per_artefact": {
      "a01": 655.1424705982208,
      "a02": 323.30060863494873,
      "a03": 565.5486941337585,
      "a04": 406.6997079849243,
      "a05": -458.6705324649811,
      "a06": -78.7584457397461,
      "a07": 601.001407623291,
      "a08": 608.6906628608704,
      "a09": 680.5445463657379,
      "a10": -614.8315713405609,
      "a11": 620.7745633125305,
      "a12": 624.5522067546844,
      "a13": 1180.215047121048,
      "a14": 989.9750020503998,
      "a15": 1340.8382556438446,
      "a16": 292.6380753517151,
      "a17": 563.4834532737732,
      "a18": -594.3145289421082,
      "a19": 626.6415123939514,
      "a20": 731.5472097396851,
      "a21": 99.04513001441956,
      "a22": 305.16866970062256,
      "a23": 645.8770799636841,
      "a24": 484.68372416496277,
      "a25": 852.8382334709167,
      "a26": -785.4108374118805,
      "a27": 709.2694284915924,
      "a28": 1074.7911353111267,
      "a29": 222.85512948036194,
      "a30": 339.58660888671875,
      "a31": 581.315646648407,
      "a32": 1299.417426109314,
      "a33": 453.99029445648193,
      "a34": 1267.78262591362,
      "a35": 653.3956093788147,
      "a36": 591.1471395492554,
      "a37": 434.7397096157074,
      "a38": 318.7431740760803,
      "a39": 0.01644444465637207,
      "a40": 411.13028049468994
     }
    },
    "twin": {
     "max_s": 1270.6416778564453,
     "median_s": 446.04211926460266,
     "min_s": -474.3360402584076,
     "pairs": 40,
     "per_artefact": {
      "a01": 441.37167477607727,
      "a02": -18.594621658325195,
      "a03": 1145.057715177536,
      "a04": 600.136789560318,
      "a05": 760.858395576477,
      "a06": 522.3009569644928,
      "a07": 647.9207990169525,
      "a08": 568.5816974639893,
      "a09": 1270.6416778564453,
      "a10": 514.1450591087341,
      "a11": 298.0851888656616,
      "a12": 450.71256375312805,
      "a13": 738.5539891719818,
      "a14": 746.3072988986969,
      "a15": -33.315361738204956,
      "a16": 47.65988850593567,
      "a17": -132.90352964401245,
      "a18": 813.2707390785217,
      "a19": 426.92725348472595,
      "a20": 17.91174602508545,
      "a21": 454.4833273887634,
      "a22": -178.27347588539124,
      "a23": 791.0048062801361,
      "a24": -268.9348006248474,
      "a25": 414.5496895313263,
      "a26": -435.0923080444336,
      "a27": 991.2337255477905,
      "a28": -102.02287578582764,
      "a29": 42.76856517791748,
      "a30": 1158.821655511856,
      "a31": -467.1404981613159,
      "a32": 427.0762939453125,
      "a33": 135.95084834098816,
      "a34": 555.3925020694733,
      "a35": 721.7249472141266,
      "a36": 426.9688446521759,
      "a37": -474.3360402584076,
      "a38": 1263.9056565761566,
      "a39": -278.43609285354614,
      "a40": 649.118067741394
     }
    }
   },
   "round 2": {
    "injected": {
     "max_s": 3020.6775693893433,
     "median_s": 1291.5837808847427,
     "min_s": -53.55564880371094,
     "pairs": 40,
     "per_artefact": {
      "a01": 1374.923733472824,
      "a02": 2093.623773097992,
      "a03": 1023.0021903514862,
      "a04": 1890.160058259964,
      "a05": 201.09738636016846,
      "a06": 991.1306862831116,
      "a07": 1868.2085716724396,
      "a08": 549.8208959102631,
      "a09": 2119.1117737293243,
      "a10": 269.5976073741913,
      "a11": 1384.169827222824,
      "a12": 982.6231927871704,
      "a13": 2125.4958868026733,
      "a14": 2316.614785671234,
      "a15": 3020.6775693893433,
      "a16": 2103.679804801941,
      "a17": 938.4442620277405,
      "a18": 288.3093731403351,
      "a19": 1758.5640833377838,
      "a20": 2988.8013927936554,
      "a21": 183.0357484817505,
      "a22": 1658.413246870041,
      "a23": 2128.6453919410706,
      "a24": 1191.0914480686188,
      "a25": 1011.9626922607422,
      "a26": 1017.9578001499176,
      "a27": 566.2139494419098,
      "a28": 2136.519790649414,
      "a29": 1652.227596282959,
      "a30": 1990.738639831543,
      "a31": 1208.2438282966614,
      "a32": 2935.0569331645966,
      "a33": 888.3326117992401,
      "a34": 2554.769014596939,
      "a35": 622.4478347301483,
      "a36": -53.55564880371094,
      "a37": 165.08405089378357,
      "a38": 1956.7888042926788,
      "a39": -1.6797475814819336,
      "a40": 244.60937094688416
     }
    },
    "twin": {
     "max_s": 2904.1637568473816,
     "median_s": 1569.1239442825317,
     "min_s": 168.922456741333,
     "pairs": 40,
     "per_artefact": {
      "a01": 2144.0185391902924,
      "a02": 1639.2792928218842,
      "a03": 2011.6688315868378,
      "a04": 886.5629372596741,
      "a05": 880.1407952308655,
      "a06": 286.29814982414246,
      "a07": 1523.7134635448456,
      "a08": 2116.2654967308044,
      "a09": 2824.739333152771,
      "a10": 168.922456741333,
      "a11": 1587.8552606105804,
      "a12": 235.30000281333923,
      "a13": 2223.228763818741,
      "a14": 2382.2276940345764,
      "a15": 1522.5318496227264,
      "a16": 792.8286182880402,
      "a17": 986.6050291061401,
      "a18": 1946.524362564087,
      "a19": 1573.8574075698853,
      "a20": 936.7363064289093,
      "a21": 1037.3253598213196,
      "a22": 1747.872730255127,
      "a23": 1956.5000460147858,
      "a24": 1492.1628127098083,
      "a25": 855.3365755081177,
      "a26": 1576.872843503952,
      "a27": 1254.9896438121796,
      "a28": 1777.498762845993,
      "a29": 1546.556011915207,
      "a30": 2523.0493388175964,
      "a31": 1468.177719593048,
      "a32": 2038.0022339820862,
      "a33": 1865.5748281478882,
      "a34": 186.82077813148499,
      "a35": 1104.4512059688568,
      "a36": 1751.201140165329,
      "a37": 1564.3904809951782,
      "a38": 2904.1637568473816,
      "a39": 1487.8024303913116,
      "a40": 1873.966992855072
     }
    }
   }
  },
  "noise_floor": {
   "injected_approval": {
    "arm F, round 1 against 2": {
     "disagree": 1,
     "kappa": 0.0
    },
    "arm I, round 1 against 2": {
     "disagree": 0,
     "kappa": null
    },
    "round 1, arm F against arm I": {
     "disagree": 0,
     "kappa": null
    },
    "round 2, arm F against arm I": {
     "disagree": 1,
     "kappa": 0.0
    }
   },
   "twin_approval": {
    "arm F, round 1 against 2": {
     "disagree": 2,
     "kappa": -0.025641025641025057
    },
    "arm I, round 1 against 2": {
     "disagree": 6,
     "kappa": 0.17241379310344776
    },
    "round 1, arm F against arm I": {
     "disagree": 2,
     "kappa": 0.48051948051948035
    },
    "round 2, arm F against arm I": {
     "disagree": 4,
     "kappa": 0.3043478260869564
    }
   }
  },
  "per_class": {
   "equilibrium": {
    "artefacts": 10,
    "delta_A": 0.0,
    "delta_C": 0.0
   },
   "magnitude": {
    "artefacts": 10,
    "delta_A": 0.5,
    "delta_C": 0.0
   },
   "propagation": {
    "artefacts": 10,
    "delta_A": 0.0,
    "delta_C": 0.0
   },
   "unit": {
    "artefacts": 10,
    "delta_A": 0.0,
    "delta_C": 0.0
   }
  },
  "per_role": {
   "control": {
    "artefacts": 17,
    "delta_A": 0.5,
    "delta_C": 0.0
   },
   "electrical": {
    "artefacts": 11,
    "delta_A": 0.0,
    "delta_C": 0.0
   },
   "firmware": {
    "artefacts": 3,
    "delta_A": 0.0,
    "delta_C": 0.0
   },
   "mechanical": {
    "artefacts": 9,
    "delta_A": 0.0,
    "delta_C": 0.0
   }
  },
  "sensitivity": {
   "delta_A": {
    "bootstrap": {
     "high": 1.5,
     "low": 0.0,
     "undefined_draws": 0
    },
    "discordant_F_not_I": 1,
    "discordant_I_not_F": 0,
    "exact_p": 1.0,
    "largest_effects_not_excluded": [
     0.0,
     1.5
    ],
    "newcombe_per_round": {
     "1": {
      "difference": 0.0,
      "high": 3.497007294595286,
      "low": -3.497007294595286
     },
     "2": {
      "difference": 1.0,
      "high": 5.1525475853896365,
      "low": -2.6001778308067847
     }
    },
    "pairs_tested": 79,
    "shown": false,
    "value": 0.5
   },
   "delta_C": {
    "bootstrap": {
     "high": 0.0,
     "low": 0.0,
     "undefined_draws": 0
    },
    "discordant_F_not_I": 0,
    "discordant_I_not_F": 0,
    "exact_p": 1.0,
    "largest_effects_not_excluded": [
     0.0,
     0.0
    ],
    "newcombe_per_round": {
     "1": {
      "difference": 0.0,
      "high": 3.497007294595286,
      "low": -3.497007294595286
     },
     "2": {
      "difference": 0.0,
      "high": 3.5048640478914654,
      "low": -3.5048640478914654
     }
    },
    "pairs_tested": 33,
    "shown": false,
    "value": 0.0
   }
  },
  "sessions": {
   "F1": {
    "at_turn_bound": 0,
    "at_wall_bound": 0,
    "sessions": 80,
    "turns_max": 43,
    "turns_median": 18.0,
    "wall_s_max": 1628.268,
    "wall_s_median": 665.851,
    "without_a_stream": 0
   },
   "F2": {
    "at_turn_bound": 0,
    "at_wall_bound": 0,
    "sessions": 80,
    "turns_max": 43,
    "turns_median": 18.0,
    "wall_s_max": 1572.156,
    "wall_s_median": 670.6030000000001,
    "without_a_stream": 0
   },
   "I1": {
    "at_turn_bound": 0,
    "at_wall_bound": 0,
    "sessions": 80,
    "turns_max": 46,
    "turns_median": 17.0,
    "wall_s_max": 1437.34,
    "wall_s_median": 650.1735,
    "without_a_stream": 0
   },
   "I2": {
    "at_turn_bound": 0,
    "at_wall_bound": 0,
    "sessions": 80,
    "turns_max": 43,
    "turns_median": 17.0,
    "wall_s_max": 1557.303,
    "wall_s_median": 650.653,
    "without_a_stream": 0
   }
  }
 }
}
```

---

## The comparison with R-PG-01 (§8, step 3)

**Added 01.11.2026, after "numbers final"** (`a73a7892`, pushed on `exp/r-pg-01b-numbers`). Every
section the analyst wrote above was written before anyone who has read R-PG-01's results saw a
number of this experiment. §1's citations and §10 items 6 to 13 were added later by the
orchestrator, as the status note at the top says. This section changes no number above and no decision of §7 beyond D1's sentence.

**How it ran.**
- `compare_r_pg_01.py`, blob `d095335e6d2d2698b348747fe5b8a14e19b7ec55`, the same at the run tag,
  at both "scripts" commits and on `master`; run once, as `uv run --frozen python -I`.
- On Oracle, 01.11.2026 at 11:30:36Z, in a fresh clone of `exp/r-pg-01b-numbers` at `a73a7892`
  (`git clone --single-branch --no-tags`), not in the run checkout (deviation 12 of §10).
- Its refusal check passed: the remote held `a73a7892`, `numbers/tally.json` is in that commit, and
  that file's sha256 `719602a0…` is the one this file gives.
- **R-PG-01's run directory** is attempt 1's (`rp1-1`), kept on the macOS laptop where R-PG-01 ran.
  It was copied to Oracle for this step alone. Its listing digest (sha256 over the sorted
  `sha256sum` lines of its 8,364 files) is
  `f57fb7f6e3498782c6bfa05d8387d0dd1a6f311dd0a2c984a7b17d639ddfeaf3` before and after the copy. Its
  four run files' sha256 equal those R-PG-01's `RESULT.md` gives.

```
compare_r_pg_01.py --numbers-ref origin/exp/r-pg-01b-numbers
  --output experiments/R-PG-01b/numbers/tally.json
  --r-pg-01-run <copy of R-PG-01's run-1>
  --run I1=~/runs/rpg01b/run-4 --run F1=~/runs/rpg01b/run-3
  --run I2=~/runs/rpg01b/run-6 --run F2=~/runs/rpg01b/run-5
  --out <new file>
```

**R-PG-01's reading**, as its own `tally_rows.py` reads its run directory: A = 0, C = 0, the kill
reading fires.

**1. Replication, against the same-day noise floor.**

| Side | D_cross | D_same | D_cross − D_same (95 % bootstrap) | Discordant (arm I approved, R-PG-01 not / R-PG-01 approved, arm I not) | Exact p | Reading |
|---|--:|--:|---|---|--:|---|
| Injected | 0.0 | 0.0 | 0.0 (0.0 to 0.0) | 0 / 0 | 1.0 | **replicated** |
| Twins | 4.0 | 6.0 | −2.0 (−5.0 to 1.5) | 6 / 2 | 0.289 | **replicated** |

Arm I approved no injected artefact in either round, as R-PG-01 did. On the twins, arm I differs
from R-PG-01 on fewer artefacts (4.0 a round) than its own two rounds differ from each other (6),
and the test finds no systematic shift.

**2. The sheet's share of R-PG-01's advantage:** not computed. The floor of §7 holds (§5), and
R-PG-01's C is 0, below 1.

**3. The gate across time:** R-PG-01's gate records are byte-identical to each of the four runs'
(I1, F1, I2, F2). The gate's determinism holds across the two experiments.

**4. D1's sentence.** Arm I's two rounds agree on the kill reading, so row 1 does not hold.
R-PG-01's reading fires, arm I's fires on its means (Ā = 0.0, C̄ = 0.0), and arm F's fires on its
means (Ā = 0.5, C̄ = 0.0), so row 2 holds:

> **"The complete sheet did not change the kill reading."**

**The corrected headline (D1), complete:** arm F's kill reading fires, both rounds agree, and the
complete sheet did not change it. R-PG-01's published reading stands beside it, with its preface.

**The output**, `numbers/comparison.json`, sha256
`fd94c7f7c738d3e4cb273df33d8347d71d1aa6d8ba87ca80d78bf18a1c016ebb` over the bytes below:

```json
{
 "numbers_final": {
  "commit": "a73a7892110d2b335073ba813f44e6d6b63c7e82",
  "sha256": "719602a055ebf2fdb40b2af3bcc17563da541ee47d41dba3dbda0f4d5837d832"
 },
 "r_pg_01": {
  "A": 0,
  "C": 0,
  "kill": true
 },
 "step_1_replication": {
  "injected": {
   "D_cross": 0.0,
   "D_cross_minus_D_same": {
    "high": 0.0,
    "low": 0.0,
    "undefined_draws": 0,
    "value": 0.0
   },
   "D_same": 0.0,
   "discordant": [
    0,
    0
   ],
   "exact_p": 1.0,
   "replicated": true
  },
  "twins": {
   "D_cross": 4.0,
   "D_cross_minus_D_same": {
    "high": 1.5,
    "low": -5.0,
    "undefined_draws": 0,
    "value": -2.0
   },
   "D_same": 6.0,
   "discordant": [
    6,
    2
   ],
   "exact_p": 0.2890625,
   "replicated": true
  }
 },
 "step_2_share_of_r_pg_01_advantage": null,
 "step_3_gate_records_identical_to_r_pg_01": {
  "F1": true,
  "F2": true,
  "I1": true,
  "I2": true
 },
 "step_4_D1": {
  "row": 2,
  "sentence": "The complete sheet did not change the kill reading."
 }
}
```
