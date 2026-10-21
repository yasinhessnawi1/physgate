# R-PG-02's practice set and tuning record (CRITERIA §2, R9, §10)

**Practice only, never a result.** The set the tuners read freely, and every reviewer-track
iteration run on it, the round that was not kept included.

- `corpus-v1/`: the practice set, 20 injected and 20 clean twins, five errors of each class
  (manifest sha256 `ddc255ab538f134c2983edfb71d29cbeba3c0dc3dd23cc01df9415120d9ddfb0`). It was
  written from the same frozen briefs as the fresh set (`../fresh-authoring/briefs/`).
- `tuning/`: each iteration's tally by the practice tally script, one file per run.

## The iterations

Every run: seed 11, 4 lanes, 40 reviews (20 injected, 20 twins), reviewer `claude-sonnet-5` on
the pinned binary, on the ARM virtual machine. Tokens are the binary's own totals over every try.

| Run | Reviewer configuration | Ran (UTC) | Tokens | Paired R / A / J | Gate R / A / J | Kept |
|---|---|---|--:|---|---|---|
| 0, first practice run | F: the rubrics and template as they were (`82cbf3b`), no account paragraphs | 18.10.2026 19:39–21:53 | 24,364,572 | 13 / 2 / −0.25 | 6 / 20 / 0.30 | baseline |
| 1, first calibration round | rule "Unwritten records" added; the account's fixed paragraphs | 19.10.2026 13:00–15:00 | 21,830,131 | 12 / 5 / −0.15 | 6 / 20 / 0.30 | no (stop rule: A 5 < 6) |
| 2, second and last round | rule "Stand-in absences" added to round 1's | 19.10.2026 18:20–20:35 | 24,417,539 | 13 / 7 / 0.00 | 11 / 20 / 0.55 | yes: K (`48929eb`), the pick |

- R and A are of 20. These are the practice tally script's figures, which key the error items by
  the expected check (R-PG-01's table). R-PG-02's frozen tally keys them by error class, and reads
  run 2 as R 14, A 7, J 0.05 (`../RESULT.md`).
- Each run's gate figures are those of the gate at the commit the run used. The gate's fixes were
  developed against hand-made errors, never against an item of any set (CRITERIA R7 item 4).
- In the tally files, three diagnosis fields were renamed to plain names
  (`refused_twins_with_unsure_words`, `refused_twins_naming_a_sheet_inherited_flaw`,
  `blocked_twins`); no value changed.

## The two rubric rules

Both were drafted blind by a development agent that read only the four rubrics, the author briefs,
the account's text (round 2) and the rule it was to state, and both were approved and promoted by
the owner (the approver's statement is in `../RESULT.md`). Neither round added, removed or
reworded a rubric item; the item ids are unchanged.

**Round 1, "Unwritten records".** One policy bullet in each rubric's proposed-revision section,
worded the same in all four:

- A proposed revision is a set of written values with units and sources, not a finished piece of
  work with its runs, reports, measurements, margins and budgets.
- A record the rubric requires the work to make (a stated value, a shown computation, a run, a
  measurement, a report, a listing) that the revision did not write is `noted`: a non-blocking
  specification defect naming the item and the record. It never rejects and never blocks.
- `unmet` still needs a written value inconsistent with another written value, its unit, the
  source it cites or its own arithmetic; or a check that involves a written value, that the values
  on the page decide, and that fails.
- The four error-detecting kinds are untouched: unit errors, magnitudes out of sense or
  unsupported by their source, balances that do not close, and a changed quantity that did not
  reach a node it constrains. An owed follow-up is expressly not an unwritten record, so a
  propagation error cannot hide under the rule.
- Small routing sentences point to the bullet from the missing-evidence rule, from each rubric's
  Section 1 consistency line, and from the places that already name the given-value `noted` case.

Why: the rubrics said an absent required record whose inputs are present is `unmet`. That is
right for a trajectory with a worktree, but for a revision of the design graph it rejects correct
work for not being a whole work product.

**Round 2, "Stand-in absences".** One more policy bullet, right after round 1's:

- A sub-check that cannot be decided because it needs an input the account lists as absent from
  the parts sheet by construction is `noted`, naming the sub-check and the missing input. It is
  never `unmet`, never a finding, and never makes the review `blocked`.
- Only that sub-check is `noted`; the rest of the item, and every other item, is judged normally.
- The rule reaches only the eight inputs the account lists (a plant pole, a moment of inertia, a
  centre-of-mass height, an actuator rate or slew limit, a disturbance magnitude, a floor friction
  coefficient, a worst-case execution time, a measured loop delay or jitter). An input not so
  listed keeps its handling and still blocks; a value the revision itself writes is still judged.
- Item counts are unchanged (56, 66, 54 and 61 across the four rubrics), and no item's check is reworded.
