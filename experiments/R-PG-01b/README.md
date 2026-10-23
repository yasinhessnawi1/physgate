# R-PG-01b: R-PG-01's reviewer side, re-run with the complete parts sheet

**The pre-registration is `CRITERIA.md`.** It was committed before any code of this experiment
existed, and nothing in it changes after the first metric is produced. An amendment is a new
experiment that cites this one.

## What it asks

How much of the physics gate's advantage over the paired reviewers in R-PG-01 came from the
reviewers' incomplete parts sheet? In R-PG-01 every review was given a sheet in which 62 of 163 rows
had no value and no row carried the authors' notes. The gate never reads the sheet, so the defect
touched the reviewer side only. The answer is ΔC, the change in the gate's added catches when the
reviewers have the complete sheet (`CRITERIA.md` §5.2), read two-sided.

## How

- Two reviewer arms, identical in everything but the sheet: arm I replicates R-PG-01 byte for byte,
  and arm F gives the same 40 artefacts and 40 clean twins with the complete sheet (§2.1, §2.5).
- Two rounds; in each, both arms run at the same time, each one review at a time, paired by artefact
  (§2.1).
- The code is R-PG-01's run commit `8bc03fc` plus a sheet-format backport, on a tagged run branch
  that is never merged (§2.4). The gate, reviewers, rubrics, binary version and run parameters are
  R-PG-01's pins (§2.2).
- Every rejection is read for its reason (§6), and every review's reads of the sheet are checked for
  a cut (§5.5).
- A blind analyst, who has not read R-PG-01's results, computes every number and pushes it before
  anything is compared with R-PG-01 (§8, Appendix A).

Nothing of R-PG-01 is changed or re-scored. Its `RESULT.md` and run directory are read only at the
last step (§8).

## Order of commits

| Commit | What |
|---|---|
| the freeze | `CRITERIA.md` and this file; no code |
| scripts | the scripts of `CRITERIA.md` §14, tested on synthetic fixtures only |
| sheet | arm F's corpus `corpora/injected-errors/v1-fullsheet/`, and the edited table copy in `sheet/` (§2.5) |
| "sheet filled" | arm F's manifest label and digest (§2.5), and nothing else |
| run branch | `exp/r-pg-01b-run` off `8bc03fc`, tagged `r-pg-01b-run`, never merged (§2.4) |
| "run commit filled" | the run commit and its instrument tree (§2.4), and nothing else |
| "numbers final" | on `exp/r-pg-01b-numbers`: `RESULT.md`'s sections on R-PG-01b alone, with the tally's output and its sha256 (§8) |
| comparison | `RESULT.md`'s last section, the comparison with R-PG-01 (§8) |

## Models and host

Reviewers: `claude-sonnet-5`, through Claude Code 2.1.301, R-PG-01's version. Reality
adjudication of the rejections: `claude-opus-5-5`, with no tools, no settings, no MCP and an empty
working directory. Every session of the run uses one run account on one ARM Linux server,
unattended (§10, §11). One earlier smoke, on another account and machine, is recorded as it ran
(§10).
