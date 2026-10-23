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

## Readings disclosed

Where `CRITERIA.md` leaves a step to be read, the scripts take the readings below. None changes a
rule, threshold, seed or decision of `CRITERIA.md`; each is how a sentence of it is carried out.

**The stream check (§5.5, L10).**

1. **The binary's stubs, errors and missing results are not cuts** (ruled by the owner, Yasin, on
   23.10.2026, following §5.5's own words that a cut "can only come from the service's counting").
   Besides §5.5's `whole`, `part` and `cut`, a Read of `parts_sheet.json` is classed:
   - `unchanged`: its result is one of the pinned binary's own stubs for a read it did not repeat
     ("File unchanged since last read…", "Wasted call — file unchanged…", or the "already in your
     context" reminder), and an earlier read in the same session, of the same path (a relative
     path taken against the session's working directory), returned every line of the range this
     one asks for. A stub with no such earlier read stays `cut`: the check fails closed.
   - `error`: any other result the binary marked an error, such as a path that does not exist.
   - `no_result`: the call's result never came.

   `unchanged`, `error` and `no_result` are reported per arm, round and side, and void nothing.
   `cut` stays for a shortened text and for the binary's token-limit error ("File content (N
   tokens) exceeds maximum allowed tokens"), which is what a page counted above the limit
   returns. Tested on the pinned binary's own streams through the scripted endpoint, with a
   dummy token and no model call: a repeated whole read, a repeated page, a page counted at
   25,001 and a read of a path that does not exist, beside the 25,000 / 25,001 whole reads.
2. **"Asked for the file's end"** is read literally: a read whose range, from its offset and with
   its limit (or none), reaches the sheet's last numbered line, and such a read without the last
   row id in its text is cut. Read alone, that made every stub a cut; item 1 supersedes it there.
3. **L10.** The smoke reviews the pilot design's electrical artefact `e1`, its injected patch. A
   smoke whose reads of the sheet are all `part` has "no whole read", and is repeated. T (§11) is
   the largest token total of L10's smoke reviews; the check session does not count toward it.

**The launch and the round's end (§11, §12, §14).**

4. **L2 finds the commits** as the last commit on `master` that changed each path set: the
   "scripts" commit for `experiments/R-PG-01b/` but `CRITERIA.md`, `RESULT.md` and `sheet/`, and
   the "sheet" commit for arm F's corpus. Every blob under `experiments/R-PG-01b/` but
   `CRITERIA.md` must be the "scripts" commit's; `CRITERIA.md` must be the freeze's, `e1262da`,
   placeholders included, since the scripts were committed again after the two fills (23.10.2026).
5. **The fills.** Only the facts of §2.4 (the run commit and its instrument tree) and §2.5 (arm
   F's manifest label and digest) are filled in `CRITERIA.md`. The slot draw, the account label
   and the token's digest prefix are recorded at launch, in the run's records.
6. **L1** also holds the checkout's HEAD to the run commit filled on `master`, refuses while any
   `claude` or `physgate inject` process of the run account is alive, and refuses once the
   experiment has stopped. A check-only trial (`--checks-only`) never reads the token, and needs
   `RPB_RUNS`, a records directory of its own outside `~/runs/rpg01b`.
7. **The watcher acts on `usage_limit_reached` alone.** The calibration run's rule of stopping at
   the third HTTP 429 is dropped; the 429s are counted and logged. The watcher looks once more
   after every arm has ended, and the round's end searches both arms' run directories and review
   roots for `usage_limit_reached` itself.
8. **On a usage limit the watcher stops what this run started, and nothing else.** It signals an
   arm's process group only while its leader is the process `launch.sh` started (the same start
   time), and a review session's group only where the session's own process record under the
   review root proves it: a pid above 1, the directory's own session id, the recorded start
   time, the session id on the process's command line, and the group it leads. It then removes
   every session's credential directory under the review roots (`rpb-<slot>`). Off the run
   machine (Linux) it signals nothing. Under a review root or a run directory nothing is ever
   reached through a symlink, whether to signal, delete or read: a session directory, a
   `session`, a `config`, a stream or a process record that is a symlink is refused and left as
   it is. Every walk and read under a root goes from the root's own descriptor, each directory
   opened from its parent's with `O_NOFOLLOW`, and acts on what it holds, so nothing swapped in
   between is followed. Nothing that is not a regular file is opened for reading; a walk is
   bounded in depth (32) and entries (250,000) and a read in size (256 MiB), and a bound hit,
   or a directory that cannot be opened, stops the check with its cause. A slot, a label and a
   records directory are held to their forms before any path is built from them.
   **No login file outlives the round.** Whatever ended the sessions, the round's end walks
   every review root of the experiment (`rpb-*`) for a session's login file (`.credentials.json`
   in its `config`, or an API key in its `state`), and for a symlink where one could hide. Any
   such file left, or not confirmed removed, stops the launcher with that cause after the
   token's scan has run, and every later L1 refuses while it remains.
9. **A crashed or killed process** (§12) is any arm whose exit is other than 0 or 1, or that has
   none, and any run that is not complete: each arm's `results.jsonl` with 40 rows, and in both
   logs 40 planned subtasks, each with a final review line (a verdict, or `review_unavailable`
   with no retry to come) and a gate line. An exit of 1 alone proves nothing, since it is both
   inject's exit for a review with no verdict and Python's for an uncaught exception. An arm the
   watcher stopped is killed, so a usage-limit void lists this cause beside "usage limit".
10. **The cascade** counts the reviews whose final line is `review_unavailable` for an
    infrastructure cause with no retry to come.
11. **The stops of §12.** L10's cut read and L10's inapplicability (no whole read in three smokes
    and the check session) each record that the experiment has stopped, as does a cut read in an
    attempt of a round that already had one. Every later L1 refuses.
12. **§11's fallback, in consecutive windows.** The second arm starts at the first 5-hour
    boundary, counted from the round's first session (L10's first smoke), at or after the first
    arm's end. It never starts after the first arm's watcher stopped it; it then has no exit
    (`null`), and is recorded as not started.
13. **A deviation of R6 at the round's end** also covers `regate_r6.py` not running on a complete
    run.

**The analysis (§5, §6, §7, §8).**

14. **R6** compares, across runs, only the gate's own parts of results 2 and 4: `tally_rows.py`
    puts the reviewers' A and C beside them, and those are each run's own. The gate's catches
    must also be the same artefacts in every run.
15. **Under R6's deviation** C is not computed, and the primary contrast, the floor, D1 and D2
    are not taken; every figure that does not rest on the gate (approvals, twins, naming, the
    noise floor, the sessions, the lag) is still reported, and the tally does not stop.
16. **"Rejected"** (result 5, ΔC among rejected) means a review that came to `fail`. **"Either
    review"** (§5.3 item 8) means the two arms' injected-artefact reviews of the pair.
17. **The lag** of §9 threat 6 is each artefact's review start in arm F minus arm I, per round and
    side, where a review's start is its first session's spawn time in the session's own process
    record under the review root.
18. **The last step** uses whichever rounds are valid: with one, round 1 or round 2, that round's
    Newcombe interval. It takes D1's sentence and the share of step 2 only where the committed
    output says R6 held.
19. **§6, the reason reading.**
    - Only the finding lines of `fail` reviews are adjudicated; a `blocked` review is class B,
      listed with its cause.
    - A review with a `true_flaw` line is O; where none of its `true_flaw` lines is `introduced`
      or `both` and not all are `already_in_base` (a line of origin `n/a`), it is O-unsplit,
      counted apart from O-introduced and O-base.
    - For the O/N label, a control that "missed" its bar outranks one "not checked": the split is
      unreliable.
    - A reality session whose output lacks a valid form for some finding is tried once more
      (R-LAW-01's one retry); the first valid form of each finding is the one used.
    - Each packet is R-LAW-01's reality packet, word for word, with the authors' table at its end.

**Not a reading: the arms' environment.** The records directory (`RPB_RUNS`) reaches the launch's
own checks alone, never an arm's, a smoke's or a session's environment, as in R-PG-01.
