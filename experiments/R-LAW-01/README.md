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

## Readings disclosed

Where `CRITERIA.md` left a choice to the scripts, these were fixed on 22.10.2026, before the slice
was drawn and before any model session. None changes a frozen number, seed or threshold.

1. **The slice draw (§6).** One `random.Random(23)` serves both sets, fresh first and then practice,
   in the order the text lists them. Each pair is drawn with `choice` from its class's eligible pairs
   sorted by id; the two practice classes are drawn with `sample` from the four classes sorted by
   name, and used in the order drawn. The draw refuses sets whose error classes are not the four
   §6 names, and any number of fresh pairs per class but one, before the generator is used
   (added 23.10.2026; the six pairs drawn on 22.10 are unchanged).
2. **The seeded shuffles "per design version"** (seeds 37, 29, 31, 41 and 43). One generator per seed,
   run across the design versions in (set, pair, side) order, not a fresh generator per version. For
   reality, the injected versions come first and the twin versions after them, with the same
   generator. The adjudicator's A and B labels are drawn from seed 41's generator, line by line,
   after that version's shuffle.
3. **The bank rewordings (Appendix D)** are applied literally: each replaces exactly the sentence it
   names, and nothing else. If a rewording is taken, the prompt loses what that sentence said:
   - **W2** replaces step 1, so the step no longer says "go to step 5".
   - **W3**: its named sentence is read as "G before L." alone; the sentence after it, on a value
     under another name, stays.
   - **W6** replaces the first sentence of the "relative" bullet, so the prompt no longer says that
     a relative tolerance is written with `==` or that its percentage is at most 25 (the script
     still enforces both).
   - **W8** replaces the definition of kind "limit", so the prompt no longer gives the `a <= b`
     shape, the single input on each side or the absence of a number (the pairing check still
     enforces them).
   - **W1** replaces step 0's second sentence, which drops "each with a one-sentence restatement and
     a code (these are recorded only)".
   - A taken example is appended after example 14 as the next number, with its label and text, and
     without its bank id or its code-pair tag.
4. **Appendix B's span** "from THE DESIGN DATA to WORKED EXAMPLES" is read inclusively: the
   adjudicator's prompt holds the coder's prompt from THE DESIGN DATA through the worked examples
   (and any taken examples) up to OUTPUT.
5. **After a stop**, a run resumes with `RLAW_RESUME=1`, because each packet is an independent
   session on fixed inputs. Every stop, every failed call and every resume is logged with its time
   (`ledger/interruptions.jsonl`) and is reported in `RESULT.md` as an interruption. An interruption
   is not a deviation and does not change whether the decision is taken. No finished packet is run
   again and no output file is overwritten.
   - A call that fails is not a try: the frozen retry (§5.5) is for an invalid form. A failed call
     is an error result (a usage limit, a rate limit, a refused credential, a server error after
     the binary's own retries, an API error), no result at all (a network failure, a crash),
     another terminal reason, or a non-zero exit. Its output is kept under its own name, the run
     stops, and on resume the packet runs the same try again.
   - One error result is not a failed call: the binary's own report that the model's output never
     fit the schema (subtype `error_max_structured_output_retries`, or terminal reason
     `structured_output_retry_exhausted`; the binary exits 1 on it, and either mark makes it a try
     at any exit code). The call completed, and the output has no form: it is a try, §5.5's one
     retry applies, and a second one leaves the line without that coder's form, as any invalid
     form does.
   - A stop writes `STOPPED`: no new session starts, and the sessions in flight end on their own,
     each settled as a try or a failed call. Only the token guard kills them. A session cut off
     mid-call (its process killed) counts as a try and gets the frozen retry.
   - The driver reads only the call that just ended, and the watcher only the files written since
     the phase began, so a resume is never stopped by the evidence of the stop it resumes from.
   - Only a `STOPPED` older than `ledger/phase-start` is the stop a run resumes from; the launcher
     consumes it once, as the phase starts. A `STOPPED` written since, by another driver of the
     same phase, is a stop: a driver that starts after it starts nothing. With no phase start to
     compare, a `STOPPED` is read the same way.
   - The 60 M guard (§12) is read before each session and once more after a driver's last session
     settles. A total that cannot be read as a non-negative integer (a torn ledger line, a row
     without a whole token count) fails closed: `STOPPED` with its cause, logged as a stop, and no
     session starts. It is never `VOID`, which is the §12 result and is never resumed. Each ledger
     line is counted by `law_verify.py` and written in one append.
   - The projection check after calibration round 1 (§12, step 6) reads the ledger through the
     same reader. A ledger it cannot read is a stop of the run, resumable once the ledger is
     repaired; the projection deviation is only the check failing on a ledger it has read.
   - A ledger line that cannot be written (its call would go uncounted by the guard) is a stop
     with that cause. The driver refuses to start unless its Python is 3.11 or later.
6. **Smaller readings.**
   - A line with an empty locus is not eligible for the rejection control.
   - A section 1 line absorbed at step A joins its target's flaw but adds nothing to its locus (the
     drafting count's rule; the frozen counts reproduce this way).
   - A line keeps the first try's form if it is valid, else the retry's.
   - The projection check's "sessions remaining" are the table's 590 less the sessions run so far.
   - Tokens are input, output, cache-read and cache-creation tokens, of every try and every failed
     call.
   - In reading S5, an L line whose relation is a `limit` takes its form's fallback code.
   - The audit's L share is counted per line, over the audited real lines.

Readings 7 to 10 were fixed on 22.10.2026 after a review of the scripts: after the slice was drawn
and before any model session. None changes a frozen number, seed or threshold, and none depends on
the slice.

7. **A relation's inputs (§5.5).** A G or L relation lists at least one input, and every input it
   lists appears in the relation; otherwise the form fails (`no_input`, `unused_input`) and its
   fallback code is used. A requirement's unit must be a whole unit token of the requirement (a
   number may stand right before it), so `h` is not found in "heater", nor `W` in "Wh".
8. **A missing form (§7)** is the category `none`, which agrees with nothing, another missing form
   included. κ₅ has six categories and κ_L three (G or L, the rest, none); chance agreement runs
   over the codes only, and PABAK uses six and three. At the flaw level, a coder with no form on
   any of a flaw's real lines is `none`.
9. **The literals and the scope note (§8.2 item 8, §10).** The literals are listed for every
   distinct relation of every measured line whose final code is L, with the lines that state it,
   not for one line per flaw. L + L-if-data beside the decision, the count of L flaws with one input
   each side and a non-integer literal, and the scope note are computed on the flaws the deciding
   share is computed on: every real flaw, or the real flaws elsewhere when the decision is
   mix-dependent.
10. **The blind check (§4).** Before its sessions start, every coder, adjudicator, audit, control
    and reality packet is held to its template's text outside the findings' own words, the design
    and the sheet; no node shows an artefact's own fields; and the design shown is the packet's
    version exactly. A coder or adjudicator packet names no role, error class or expected check
    outside the findings; a reality packet names its own reviewer's role in the prior
    adjudication's one sentence and nothing more. An adjudicator is shown each coder's form cut to
    the schema's fields.

Reading 11, and the additions to readings 1, 5 and 9, were fixed on 23.10.2026 after a second review
of the scripts: after the slice was drawn and before any session of the experiment (the smoke
session and a schema probe of 22.10 ran outside it and wrote no ledger line). None changes a frozen
number, seed or threshold, and none depends on the slice.

11. **The token guard in the tally, and the G claims per coder (§7, §12).**
    - The tally sums `ledger/ledger.jsonl` itself: a total of 60,000,000 tokens or more is the
      void deviation of §12 whether or not the driver wrote `VOID` (sessions in flight when the
      guard was last read can end past it). A ledger with a line it cannot read is refused, and so
      is a missing one outside a dry run.
    - "For each coder, the share of G-caught lines it claimed G" (§7) is taken over the G-caught
      lines that coder was given, from its own rows: the adjudicator's over the disputed lines it
      saw, the audit's over its 20 % (its rows are step `audit`).

Reading 12, and the projection check's addition to reading 5, were fixed on 23.10.2026, after a
live capture of the binary's structured-output exhaustion and before any session of the
experiment. Neither changes a frozen number, seed or threshold, and reading 12 only ever counts
more toward the 60 M guard, never less.

12. **A call that reports no usage (§12).** The binary's structured-output exhaustion reports no
    usage although the model ran (captured live: two turns, every count 0, `modelUsage` empty),
    and a call with no result reports none either. So a try or failed call whose output has no
    result, or a result whose `modelUsage` is empty, is charged ceil(turns / 2), at least 1, times
    the largest token count any completed try has reported in the ledger when its line is
    written; while no try has reported one, the unit is §12's 50,000 per session. With no result,
    the turns are 1. An estimate is not a report, and a failed call is not a try, so neither sets
    the unit. A failed call refused before any model work (a usage limit, a rate limit, a refused
    credential) is charged nothing, but only when no model turn completed before it: no result,
    or `num_turns` at most 1; after model turns it is charged like any other. A charge is never
    less than what the output reports, the row carries `tokens_estimated: true` with
    `models_used` as the output gives it (empty), and the tally prints the count and the summed
    charge of such rows beside the token total. The charges also enter the projection check's
    measured tokens per session; that makes the projection deviation slightly more likely, never
    less, and is kept because it is conservative.

Readings 13 to 15, and the additions to readings 5 and 12, were fixed on 23.10.2026 after a second
independent review of the scripts, before any session of the experiment. None changes a frozen
number, seed or threshold.

13. **The projection check, once (§12, step 6).** Exit 1, the projection deviation, is only a
    projection over the 60 M guard computed on a ledger read in full. A missing ledger, one it
    cannot read, no round-1 session in it, or any failure to compute is exit 2: a stop of the
    run, resumable, never the deviation. The first projection (exit 0 or 1) is kept with its line
    in `ledger/projection.json`, and a resume of calibration reuses it and never recomputes it
    with round 2's rows; an exit 1 kept there is the deviation already recorded.
14. **Repairing a torn ledger line.** A ledger line cut short (a driver killed mid-append) stops
    the run. The operator repairs it:
    - finds the call the line belongs to (its packet and try, from the session files and the lines
      around it);
    - copies the ledger truncated just before the torn line, and re-derives the call's row from its
      kept output with `law_verify.py ledger <that copy> …`, so that an output without usage is
      charged from the ledger as it stood when the call ended (reading 12), not the 50,000 unit a
      scratch ledger would give;
    - sets the row's `utc` to the original call's time: for a failed call, the time in its file
      name (`<packet>.try<n>.failed-<time>.json`); for a try, the modification time of
      `<packet>.try<n>.json`, written as the call was settled; the repair's own time only where
      neither exists, and the event says which;
    - replaces the torn line with that row, and logs an `interruptions.jsonl` event `repair` with
      the time and the cause.

    The tally counts and prints the repairs beside the other interruptions. Deleting a torn line
    without a re-derived row is never a repair: the guard would lose that call's tokens.
15. **The binary's environment, one launcher per work dir, and the dry run.**
    - Every call of the binary (each session, the smoke session, `--version`) runs under
      `env -i` with only `HOME`, `USER`, `LOGNAME` and `TMPDIR` and `LANG` from the caller where
      it has them, `PATH=/usr/bin:/bin:/usr/sbin:/sbin` and `DISABLE_AUTOUPDATER=1`. Nothing else
      of the caller's (a Claude Code session's variables, `ANTHROPIC_*`,
      `MAX_STRUCTURED_OUTPUT_RETRIES`) reaches it. The launch log records the names as `env -i`
      hands them over (`law_sessions.sh envnames`), never the values.
    - A launcher holds an flock on `ledger/launch.lock` for the whole phase, through a file
      descriptor that every process of the phase inherits. The kernel holds it while any of them
      lives and frees it when the last one ends, also across a reboot, so a reused pid never
      keeps it held. Of launchers started together exactly one takes it, and a second launcher
      is refused, so a launcher whose terminal closed cannot leave two drivers on one work dir.
      The file records the launcher's pid and the phase's process group, for the log only; a
      record left by a phase that did not end cleanly is logged as a `takeover` interruption by
      the next launcher that takes the lock. Only the phase holds it: the watcher, which is no
      part of it, runs without the descriptor, so the lock is free the moment a launcher ends.
    - A dead phase's lock is never cleared by hand: nothing of it is left to clear. If a launcher
      is refused although no phase should be running, a process of the old phase still holds the
      lock. The operator lists the holders (`lsof <work dir>/ledger/launch.lock`), checks that
      they are R-LAW-01 processes of that phase, ends them (their calls are settled on the
      resume, as reading 5 says), and logs a `stop` interruption with the cause. The lock file is
      never deleted or moved while a holder lives.
    - The launcher runs end to end on the synthetic fixture with the stand-in, as a test, and
      only there: `RLAW_STANDIN` and `RLAW_DRY_PINS` are each refused without the other, a
      stand-in that is the pinned binary is refused, a dry run refuses a work dir whose
      `slice.json` is the committed one (the real work dir), and a real preflight refuses a work
      dir that holds any stand-in's output (a marked ledger, codes or reality row, or a `.standin`
      session file). Every output of a dry run is marked a stand-in's, and the tally refuses it outside
      `--dry-run`.

Reading 16 was written on 23.10.2026, before any session of the experiment. It changes no frozen
number, seed or threshold.

16. **The parts sheet's own words (§2.1, §2.5).** Every packet carries `parts_sheet.md` verbatim,
    as §2.5 requires. Its line 1 reads "Stand-in design, not the reference solution. Kit: …", its
    line 5 is the author's "Kit choice: I chose …", and the note of row R6.05 contains
    "answered". The text is kept because §2.5 freezes the sheet verbatim at its digest, and §2.1
    already labels the design a stand-in.
    - It is identical in every packet of every step, arm and control, so it cannot tell an
      injected version from a twin, or one reviewer, role or class from another; none of its
      words is in the blind check's forbidden list (the check finds none in the whole sheet).
    - The coders' question (could a law over the design's quantities catch this flaw?) does not
      turn on it.
    - Its one plausible effect is on the reality judge's prior that a finding is real. That is
      measured by reality's calibration and rejection controls, which carry the same sheet. The
      prior adjudication's packets did not carry these lines, which may shift the agreement with
      the prior adjudication.
    - `RESULT.md` reports it as a disclosed threat to validity.

Reading 17, and the corrections to readings 14 and 15, were written on 23.10.2026 after the third
and fourth reviews of the scripts, before any session of the experiment. None changes a frozen number, seed or
threshold.

17. **A packet stuck on one cause (§12).** A packet whose call fails three times in a row for the
    same try (the first failure and the two resumes after it), each time with the identical cause,
    is a deviation under §12's "anything else impossible as specified": the decision is not taken.
    - The cause is identical when classify's label and, where the output has them, the binary's
      own `api_error_status` and error text (`errors`, or `result`) are the same in all three. Any
      failed call counts except a usage limit, a rate limit (429) and a refused credential.
    - The failures are the packet's, not an outage's: between each and the next, at least one
      other packet's call completed as a try, as the ledger shows.
    - The owner chose (23.10.2026) that the run also ends there. `RESULT.md` reports the packet and
      its cause; any figures reached before the stop are descriptive only, never a result.
    - The driver applies the rule, not a person, after every failed call (`law_verify.py stuck`).
      It reads only the ledger and the kept failed-call files (each failed call's ledger row names
      its file, `output`), so the count holds across resumes. When the rule fires, the driver
      writes `deviations.json` naming the packet, the try, the cause and the three files, logs a
      `deviation` interruption and stops; preflight then refuses the work dir.

    It changes no frozen number, seed or threshold.
