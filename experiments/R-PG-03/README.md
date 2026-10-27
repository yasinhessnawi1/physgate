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

## Readings disclosed

Where `CRITERIA.md` leaves a step to be read, the scripts take the readings below. None changes a
rule, threshold, seed or decision; each is how a sentence of the frozen file is carried out, and
each names that sentence. Quotes are `CRITERIA.md` as frozen at `3e7a3c8`.

**The fills and the code.**

1. **The fills live in `fills.json`, not in `[FILL]` slots.** `CRITERIA.md` has no `[FILL]` slot,
   and stays byte-identical to the freeze for good. This README is the freeze's bytes followed by
   this one section, and nothing else. The launch holds `CRITERIA.md` byte for byte, and this README
   as those bytes and this one section, the same bytes at `R`, `R_K` and the master ref, so these
   readings are final at "Commits filled" and nothing in this file moves during the run; later
   disclosures go to `RESULT.md`. Each fill is added to `experiments/R-PG-03/fills.json` on master
   by a commit of its own that changes that file alone, adds exactly one fill, in the order "Commits
   filled", "Sheet filled", "Set filled", names it in its subject, and changes no fill before it;
   every read of the record holds that history. Rests on: "Facts are filled later, each in its own
   dated commit, before the first review, and none is a choice"; "Every `[FILL]` below is such a
   fact."
2. **The `standard` class, built in the instrument:** a fifth error class, and a completeness rule
   for a corpus of that class alone. Rests on: §3.2, `R` "holds … the instrument change the
   `standard` class needs (a fifth error class, and a completeness rule for a corpus of that class
   alone)"; §2.5 item 1, "10 of `standard` for `fresh-v2-s`".
   - The class's name in `error_class` is `"standard"` (Appendix B, `brief_C.md`: "with
     `error_class` `"standard"`"); an item of it carries the fields of the classes other than
     propagation (`brief_C.md`: "`edge` `null`, `expected_check` …, and a `description` …"); its
     twin is formed as for every class (§2.1: "10 + 10"; §2.2: X1 writes `s01`–`s10`, C their
     errors).
   - A corpus of the class is told apart by its own artefacts, at the size the caller gives (10 for
     block `s`), and a corpus that mixes it with the four classes is refused (§2.5 item 1; §3.2: "a
     corpus of that class alone").
   - No telltale word is added for the class (§2.5 item 1: "the telltale scan"; a new word would
     change how earlier corpora load, which §3.2's test forbids), and no mechanical domain check is
     run on it (§2.5 lists none; §2.6: no pre-run domain check of the twins).
3. **R3 holds R-PG-01b's corpora and runs, this experiment's earlier attempts and a trial's records
   by placement alone,** never by opening them; a checks-only trial's records lie under
   `~/runs/rpg03-trials`, which every real block's scan holds as a place. Rests on: §5 R3, "a scan
   (R-PG-02 R3's rule) proves that no copy … is readable", naming among them "the dry-run results";
   §1, "No such file is read by any script".
4. **Prompt identity on the instrument's own test corpus; an older tree's inline sentence.** If the
   older tree's loader refuses the complete sheet's fields, both trees are fed the older form; the
   check can only fail closed. Rests on: §3.3, "the instrument's own test corpus, copied once from
   `R`"; "must differ only in the account's sheet sentence, where the two trees word it
   differently".

**The authoring.**

5. **The first turn's launch message** is the one line "Read brief.md in this directory, then do
   what it says.", and **every turn's bound is `--max-turns 150`.** Neither is in any tracked file
   before this experiment: R-PG-02's published authoring record holds neither. The bound is the one
   R-PG-02's sessions were resumed with, seen in a local copy of its session-resume script that was
   never published, and no source of the line was found. Both are therefore **this experiment's own
   fixed choices**, fixed in its scripts before any session. Rests on: §2.2's table, "the launch
   message"; "Every message a session receives is a file in Appendix B" (Appendix B holds X3's
   launch alone); "The sandbox is R-PG-02's".
6. **The briefs' additions, byte for byte:** one reading-list line in `brief_A.md`, the same line
   and one sentence in `brief_B.md`, and nothing else changed. Rests on: Appendix B, "in the reading
   list, after `format.md`: …"; "in `brief_B.md` only, appended to the class list's last paragraph:
   …".
7. **The facts template is one line per fact.** Rests on: Appendix B, "`<one line per fact: the
   check, the node, the quantity, the message>`"; §2.5, "the check's name, the node, the quantity,
   the message".
8. **The passed copies are a read-only record.** When a batch passes, its `base.json` and
   `clean/*.json` are copied into the pair attempt's record of passed copies, with their digests;
   every later session's copies, and every corpus, come from that record, so a writer that changes
   a passed copy later leaves the passed bytes intact. Rests on: §2.2, "Every corpus is assembled
   from those passed copies, never from a later session's directory. Every later session gets its
   own copies of what it needs, in its own directory."
9. **A turn and its resumes are one audit.** An audit failure in a part of a turn cut by a usage
    limit or an outage is carried to the turn's end and routed then, with the rest; a passed copy is
    judged at the turn's end alone, so that one is not carried. Rests on: §2.5, "a turn and every
    resume of it count as one turn"; "at the turn's end, a passed copy … that is changed or gone".
10. **The binary's own API-error messages are not "another model".** The pinned binary writes its
    report of an API error as an assistant message of the model `<synthetic>`, marked
    `is_api_error_message` (seen on the scripted endpoint); that model is excused on those messages
    alone, never wholesale. Rests on: §2.5, "a model other than the pinned one"; "An infrastructure
    cut never spends … and it is never an audit failure."
11. **`error_max_turns` ends a turn; it is not an outage,** and a turn that outlasts its six-hour
    wall-clock bound is an outage (the binary is killed; the turn is resumed on the retry ladder,
    and keeps its outcome and ledger line). Rests on: §2.5, "An infrastructure error is an API,
    connection or binary error, never a refusal and never something the author did."
12. **The owner stops only where the authoring waits for the owner's word after a turn's second
    retry ladder, and only at the cap of the batch that turn writes.** At `fresh-v2-s`'s cap the
    class is not run and the primary goes on; at the primary's cap the authoring stops for the
    owner. Rests on: §2.5, "If that second ladder is spent too, the authoring stops for the owner.
    The owner may only wait longer and resume the same turn …, or stop the authoring as at the cap
    of the batch that turn writes: the primary's cap for a primary batch, `fresh-v2-s`'s for the
    `s` batch."
13. **`fresh-v1c` is assembled by `sheet_check.py assemble-v1c` and accepted by `authoring.py
    accept --fresh-v1c`.** Rests on: §2.5, "`fresh-v1c` … is not authored, so it takes items 1, 2,
    5 and 6, at `R`"; §13's `sheet_check.py` row.

**The launch, the order and the ledger.**

14. **The whole-read smoke is a step of its own** (`launch.sh --block x1 --smoke`), run on the run
    account before the owner confirms that a weekly window has begun, never after; the first block
    needs a passed smoke whose end lies before that confirmation, and no stage of a block before its
    start runs on the account or writes a ledger line. The same step counts §7's five keys again and
    checks Q4's practice figure (below). Rests on: §2.4, "a whole-read smoke on the run machine
    before the first block"; §10 item 4, "nothing else runs on the run account between that
    confirmation and the first block"; §13, "with no ledger line after it".
15. **Practice records that cannot be read at their digests are "not checked", said plainly before
    the window's confirmation;** only a key whose count is not 1 (or R-LAW-01's files not being the
    probe's) refuses. Rests on: §7, "If the records cannot be read at those digests, the control
    cannot be computed: it is "not checked", and so the reading is "unchecked""; "a count other
    than 1 is a defect of the script: a failed precondition (§11)."
16. **Q4's practice figure is checked before the first block,** in the smoke's step, as the tally
    checks it: a figure other than 0.775 refuses; records that cannot be read at their digests are
    said plainly (the figure is then not computable). Rests on: §6.3, Q4: "The practice figure is
    the kept round's on the tuning set: J common 0.775."
17. **The blocks' dates:** no block before 5.11.2026 00:00 UTC; none before 12.11.2026 00:00 UTC if
    any line of R-PG-01b's ends (or starts) on 5.11 or later, midnight UTC standing for that day's
    reset, which errs toward the later start. The owner's window confirmation is refused if it is
    stamped after now or before that earliest start. Rests on: §10 item 4, "no earlier than Thursday
    5.11.2026. If R-PG-01b runs into a second window (item 1), the first possible start is Thursday
    12.11.2026"; "The confirmation is recorded in UTC"; §14 row 20.
18. **An attempt's number is the block record's;** a refused pre-flight of the same attempt keeps
    its directory beside it, renamed. Rests on: §11, "A void block … is re-attempted whole, never
    resumed, and every attempt is reported."
19. **The 5-hour projection fails closed:** it needs R-PG-01b's lines first, and a line in the
    trailing window with no total, or one whose sessions do not all have a total, cannot be counted,
    so the block waits. Rests on: §10, "It opens with R-PG-01b's lines"; "If R-PG-01b's records give
    no total for a step, the line says so"; §13, "the 5-hour projection, with R-PG-01b's ledger
    lines".
20. **A ledger line per authoring turn** (finer than one per session), with the turn's own start
    and end and **its weekly window computed from one reset of the weekly limit** that the owner
    reads from the usage page and records (`owner/account.json`): the last reset at or before the
    line's start. Rests on: §10, "one per block attempt …, per authoring session …, per resume of an
    authoring session"; "Each line holds `tokens_every_try` …, the account, its weekly window, and
    the start and end times."
21. **The scans:** the prefixes are counted with `scan.sh`'s own counter, after the smoke and after
    a block alike; the token's value only through `token.sh`, whose pattern goes to grep in a file.
    Rests on: §13, "Scans count with `scripts/experiment/scan.sh`"; §10, the token "is never
    printed" (so it cannot be an argument).
22. **The watcher, in authoring and in the reading,** counts only what is written after it starts
    (the directories keep every earlier step's files for good), and at a limit logs it and signals
    nothing: the session has already ended on the limit, and the step starts nothing after it, so
    the step finishes its own records. A block's watcher stops every arm at the first limit, as
    before. Rests on: §10, "**The same watcher** guards the authoring sessions, whose cut sessions
    are resumed (§2.5), and the reality reading (§7)"; §2.5, "resumed with Appendix B's fixed resume
    message"; §7, "run again whole, with the same packet bytes, after the limit resets".
23. **A crash or an incomplete run is a deviation the owner classifies, never a void.** It is
    recorded unclassified, and the launch refuses any further attempt of that block until the owner
    runs `checks.py classify` on the attempt's logs and the ledger alone, before any tally: either
    an instrument defect, naming the path of a tracked test that depends on no verdict and shows it
    and the id of the correction that names the block (the test's commit and blob are recorded; the
    block is then re-run at the corrected commit and both runs are reported, reading 24), or
    anything else impossible as specified (the decisions it feeds are not taken, and the block is
    not attempted again). The classification is written once, as
    `classification.json` next to the attempt, and in the block record. Rests on: §11, "An
    instrument defect found after a number is seen is a deviation only if a test that depends on no
    verdict shows it"; "Anything else impossible as specified is a deviation. The decisions it feeds
    are not taken".
24. **The corrected commit of an instrument defect is recorded beside "Commits filled", which never
    changes, and names every block the defect touches.** A correction is a commit of its own to
    `fills.json` alone, only after "Set filled", whose subject names "Commits corrected" and every
    block it touches, and which adds exactly one entry: an id no earlier correction has, the
    corrected `R'` and `R_K'`, and every block it touches, each with the path of a tracked test
    that depends on no verdict and shows the defect in that block's own records. `R'` descends from
    `R`; `R_K'` is one commit above `R'`, with the same five-path difference and the same check of
    `promotions.jsonl`'s content. For each block it names, the owner's `checks.py classify` writes
    the classification (an instrument defect, with that test and the correction's id) next to the
    block's attempt, a valid attempt too; an id classifies one attempt of a block, so a further
    defect is a correction of its own. The launch then runs exactly those blocks once more, at `R'`
    and `R_K'`, and no other: a touched block is attempted until it has a valid attempt after the
    touched one (a void attempt is re-attempted whole, as any is, and §11's three void attempts
    count over the block), and the blocks after it in the fixed order wait for that. Every other
    block runs at `R`. The trees, blobs and digests "Commits filled" records describe `R`, so they
    are not held at `R'`; every other pin of §3 is. A correction that names a block without that
    classification, a classification with a correction that does not name the block, and a
    classification other than the correction's for it, are refused. Both attempts are kept in the
    block record and listed in the tally's output; the tally, and the reading's lines, use the
    corrected attempt of a touched block, and the tally refuses while a block a correction names
    lacks it. Rests on: §11, "Every block it touches is then re-run at the corrected commit, and
    both runs are reported"; "The decision uses the corrected runs"; the header, "Facts are filled
    later, each in its own dated commit".

**The tally.**

25. **The stratified bootstrap:** X's, Y's and Z's pairs, each stratum in §7's line order. Rests on:
    §6.1, "stratified by author pair into three strata of 40 (X's 40, Y's 40 and Z's 40, each
    resampled with replacement within itself …)".
26. **Corrected A under Q1's guards:** the A guard is read on corrected A, the R guards unchanged.
    Rests on: §8, "The fix's sentence … is robust if it is the same under … the corrected-A reading …
    in both of its ways"; §7, "J_corrected = R (common) + A_corrected − 1".
27. **The locating rule on the raw evidence;** node ids are matched as whole words, case-folded, and
    not after a dot. Rests on: §4.1, "some rejecting line's evidence holds a changed node's id as a
    whole word, or a changed quantity's name with its node (R-PG-02's `names_pair`)".
28. **Blocks `p1` and `p2` are compared with R-PG-02's published per-item records** (its published
    tally), in R under the common rule and in A as well as in verdicts; an item with no published
    record refuses. Rests on: §6.4 item 10, "their R, A and J, and per item against R-PG-02's
    published `a-fresh` and `b-fresh`".
29. **The tally needs the reading,** outside a test on fixtures: without it the reading would read
    "unchecked", which §7 defines by its three controls. Rests on: §7, "The reading is reliable if
    all three bars are met, unreliable if any is missed, and unchecked if any is not checked."
30. **The knowledge digests are checked under the review roots the block record names.** Rests on:
    §3.1, "The tally checks both against the review's arm and role."
31. **The class clause gives each of §7's two ways apart only where they differ.** Rests on: §8,
    "Where the reading's two ways differ, k, a_A2 and a_B are given for each way."

**The reading (§7).**

32. **A call that ends on a usage limit, or never returns a result, is not an attempt;** each
    finding takes its first valid form across at most 3 attempts; a call is classed as R-PG-01b
    classes it (a terminal reason other than "completed" fails the call; the binary's form retries
    spent is an attempt). Rests on: §7, "Any session that ended on the limit, or did not end, is run
    again whole, with the same packet bytes"; "At most 3 attempts per packet"; "used as R-PG-01b
    uses it".
33. **A packet whose every call fails** stops the run each time, as every failed call does, and the
    scripts never declare anything of it: R-LAW-01's reading 17. If the owner judges that it cannot
    run as specified, that is §11's "anything else impossible as specified", recorded with the kept
    failed calls. Rests on: §7, "At most 3 attempts per packet"; §11, "Anything else impossible as
    specified is a deviation."
34. **A `true_flaw` of origin `n/a` is "O-unsplit",** counted apart. Rests on: §7, "O-introduced: such
    a line has origin `introduced` or `both`. O-base: every such line is `already_in_base`." (`n/a`
    is neither.)
35. **Calibration's error-item lines are those whose item is in the review's common cell.** Rests on:
    §7, "of `fresh-v2`'s P reviews (below), the share whose error-item lines include a `true_flaw`
    line …"; "P, credited: an injected review credited under §4.1's common rule".
36. **The standards file's heading** on a `fresh-v2-s` packet, and **the corpus by its name** for
    which packets carry it (that corpus holds the class alone). Rests on: §7, "verbatim, under a
    heading of its own after the parts sheet"; "Every packet built for a design version of
    `fresh-v2-s`, on either side …"; "No packet of the four generic classes carries it".
37. **§7's order is held by every step:** the rejection controls are drawn once every reading packet
    has ended; the false-finding packets are numbered after them; the second judgments are built
    once every reading, control and false-finding packet has ended, and the class's third once every
    second judgment has; packet numbers follow from that order alone. A false-finding step whose
    records cannot be read at their digests is recorded as not checked. The score refuses until
    every step has run, draws the controls, the second judgments and the third again from the final
    verdicts, and refuses on any difference. Rests on: §7, "**The order:** the injected versions'
    packets; the twins' packets; the rejection controls, drawn from the injected versions' first
    judgments; the false-finding control; the second judgments; the class's third judgments"; "after
    every reading and control packet has a verdict or has run out of attempts".
38. **The steps that read first judgments print that they are built, and no count that depends on a
    verdict.** Rests on: §7, "No packet's verdict is read by any person until every packet, control
    and confirmation packet has a verdict, or has run out of attempts."

**Disclosures.**

- **An implementer of this experiment's scripts saw a few code lines of R-PG-01's scripts:** one
  early search for callers printed them. No result and no `RESULT.md` of R-PG-01 was seen; that
  directory was left out of every search after it.
- **The instrument's earlier-corpora test reads R-PG-01's corpus.** §3.2 asks for a test that every
  earlier corpus still loads byte for byte, and among them are R-PG-01's corpus (`v1`) and `v1` with
  the complete sheet; the test loads them through the loader and holds them by manifest digest and
  by count, and prints nothing of them. §1 says that no file of R-PG-01 is read by any script of this
  experiment; this test is the instrument's, run in the repository's suite, and is disclosed here.
- **The scripts' reviewer ran one search for file names** under a local copy of R-PG-02's run
  records, while looking for R-PG-02's launch line; no file was opened, and no file of R-PG-01 and
  no corpus was read.
- **The pinned binary was run on the scripted endpoint** (no model called) to see how it writes an
  API error in its stream (reading 11).
