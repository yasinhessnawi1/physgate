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
     `structured_output_retry_exhausted`, with exit 1). The call completed, and the output has no
     form: it is a try, §5.5's one retry applies, and a second one leaves the line without that
     coder's form, as any invalid form does.
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
