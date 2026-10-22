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
   name, and used in the order drawn.
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
5. **After a usage-limit stop**, a run resumes with `RLAW_RESUME=1`, because each packet is an
   independent session on fixed inputs. Every stop and every resume is logged with its time
   (`ledger/interruptions.jsonl`) and is counted as a deviation in `RESULT.md`. No finished packet is
   run again and no output file is overwritten. A first try cut off mid-session counts as a try and
   gets the frozen retry.
6. **Smaller readings.**
   - A line with an empty locus is not eligible for the rejection control.
   - A section 1 line absorbed at step A joins its target's flaw but adds nothing to its locus (the
     drafting count's rule; the frozen counts reproduce this way).
   - A line keeps the first try's form if it is valid, else the retry's.
   - The projection check's "sessions remaining" are the table's 590 less the sessions run so far.
   - Tokens are input, output, cache-read and cache-creation tokens, every try.
   - In reading S5, an L line whose relation is a `limit` takes its form's fallback code.
   - PABAK uses six categories for κ₅ (five codes and a missing form) and two for κ_L.
   - The audit's L share is counted per line, over the audited real lines.
