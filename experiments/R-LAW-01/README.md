# R-LAW-01: the ceiling of a deterministic law library for the physics gate

**The pre-registration is `CRITERIA.md`.** It was committed before any code of this experiment
existed, and nothing in it changes after the first metric is produced. An amendment is a new
experiment that cites this one.

## What it asks

Of the flaws the reviewers find, what share could a closed-form physical law over the quantities the
design-state nodes hold catch, beyond what the physics gate's seven checks (ARCH-080) already catch?
That share is the ceiling for a law library added to the gate. It decides whether the library is a
small, targeted set of laws or a priority (`CRITERIA.md` §10).

## What it reads

- The review records of seven runs of R-PG-02's practice set and fresh set (`CRITERIA.md` §2.1),
  each file held to its sha256 at the "Inputs filled" commit.
- The two corpora's base designs, patches and full parts sheet (§2.5).
- The physics gate at the pinned tree, re-run on every design version (§5.6).

Nothing of R-PG-01 is read.

## Order of commits

| Commit | What |
|---|---|
| the freeze | `CRITERIA.md` and this file; no code |
| scripts | the scripts of `CRITERIA.md` §13, tested on synthetic fixtures only |
| "Inputs filled" | the digests of every input (§2.4) |
| "Slice filled" | the six calibration pair ids (§6) |
| "Prompt filled" | the final coder and adjudicator prompts and the bank items taken (§6) |
| result | `RESULT.md`, the published lines, forms, re-gate records and tally (§11) |

## Models

Coders, adjudicator and reality adjudication: `claude-opus-5-5`. Cross-model audit, reported only:
`claude-fable-5-1`. Every session runs with no tools, no settings, no MCP and an empty working
directory, and its model string is recorded per session.
