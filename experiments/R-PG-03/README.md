# R-PG-03: the review-calibration fix, tested on new material

**The pre-registration is `CRITERIA.md`.** It was committed before any file of the new set and
before this experiment's scripts existed, except the one count-only probe that its §13 names, and
nothing in it changes after the first metric is produced. An amendment is a new experiment that
cites this one.

## What it asks

Did the review-calibration fix make the paired specialist reviewers better on design revisions
written after the fix was frozen, and are they now at least as good as one role-aware generalist
reviewer? R-PG-02's P4 failed: paired J 0.45 against generalist J 0.80. The fix, two rubric rules
inside the domain sections, was tuned on R-PG-02's fresh set, which is therefore never a test set
again. The answer is read from two paired contrasts, J_A2 − J_A1 (the fix) and J_A2 − J_B
(pairing), by the criteria and outcome rows fixed in `CRITERIA.md` §6.3 and §8, with the claim
shift committed in advance.

## How

- Three arms review the same items on `claude-sonnet-5` (§3.1): A2, the fixed specialists
  (ARCH-060 as built, with the four frozen fixed rubrics); A1, R-PG-02's specialists
  (configuration K); and B, R-PG-02's role-aware generalist byte for byte.
- A new set, `fresh-v2`, authored after the fix was frozen: 120 injected revisions and 120 clean
  twins from three independent author pairs, 30 per error class, and a secondary domain-standard
  class of 10 pairs (§2).
- The authors get fixed inputs and messages and eight authoring rules (Appendix A, Appendix B).
  The reviewers get the complete parts sheet, written by the converter with the call fixed in §2.4.
- One run per arm. A block is one corpus, reviewed by all three arms launched together on one
  seed, in a fixed order (§10). Blocks `p1` and `p2` re-review the tuning set with the complete
  sheet for a sheet-matched Q4, and never decide.
- The code is one run commit `R` for A2, and its rubric-only sibling `R_K` for A1 and B, which
  differs from `R` in five paths only (§3.2).
- Every rejection is read for its reason, blind to the arm, with three reality controls and a
  confirmation pass (§7). Nothing is tallied before the last block has ended (§5, R8).

Nothing of R-PG-01 is read. Nothing of R-PG-02, R-LAW-01 or R-PG-01b is changed or re-scored.

## Order of commits

| Commit | What |
|---|---|
| the freeze | `CRITERIA.md` and this file; no code |
| code | the `standard` class in the instrument, with its loading test (§3.2); the scripts of `CRITERIA.md` §13, tested on fixtures only, and the probe that ran before the freeze, byte for byte |
| "Commits filled" | `R` and `R_K`, every tree, blob and digest of §3, and `code_changes.py`'s list (§3.3) |
| "Sheet filled" | the reviewers' sheet's sha256 and counts at `R` (§2.4) |
| "Set filled" | each corpus's manifest digest, after its acceptance checks (§2.5) |
| result | `RESULT.md`, and everything §12 lists, the corpora included |

## Models and host

Reviewers: `claude-sonnet-5` for every role, through Claude Code 2.1.301. Authors:
`claude-opus-5-5`, in R-PG-02's sandbox (Read, Write and Edit inside each session's own
directory). Reality reading: `claude-opus-5-5`, with no tools, settings, servers or persistence and
an empty working directory. The authoring and the blocks run on one ARM Linux virtual machine, on
the run account that R-PG-01b also uses; R-PG-01b goes first (§10).
