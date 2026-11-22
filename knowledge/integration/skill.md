# Integration — skill

> Procedures and antipatterns for integration tasks, researched and drafted from published sources
> by an agent and approved by a person before use. Rule numbers (§N) refer to
> `knowledge/integration/standards.md`; read `knowledge/cross/standards.md` first.

## Procedure: reading what you are given

1. List the modules the plan holds, each with its role, its accepted attempt and its specification's
   acceptance criteria (§1).
2. List the interface nodes, and for each its producer and its consumers.
3. Read the system-scope gate result; note every failure, or that the run's automated checks
   were switched off and there is none (§7).
4. Read the harness's recorded contract result for each interface pair, where one is recorded
   (§9).
5. Read the cross nodes sizing wrote and the nodes they constrain, as they now stand.
6. Read the simulation records the modules cite, by the record names their quantities carry (§6).

## Procedure: the interface clause table

One row per quantity on each interface node, per consumer (§2):

| Interface | Quantity | Producer value, unit | Consumer | Consumer value, unit, where read | Converted | Agree? |
|---|---|---|---|---|---|---|
| e.g. control–firmware timing | sample period | 10 ms (spec) | firmware | loop period constant, file and line | 10 ms | yes |

1. Find the consumer's use by reading its files and nodes, not by its summary.
2. Convert with the factor shown (cross-domain standards §2); agreement is the same value after
   conversion, within 1e-9 of the larger magnitude, |a − b| ≤ 1e-9 × max(|a|, |b|), a
   representation tolerance for conversion rounding, not an engineering margin (§2).
3. A disagreement names the module that differs from the interface node, the quantity and both
   values (§10).

## Procedure: the assumption cross-check

For each interface, two columns (§3):

1. What the consumer assumes: range, sign, frame, rate, latency, saturation, the condition the
   value holds at.
2. What the producer guarantees, from its node, its specification and its records.

A consumer assumption with no matching guarantee, or a range wider than the producer's, is a
finding. Example: a controller tuned for a sensor delay the firmware never states it meets.

## Procedure: running the composition

1. On the merged state, run each module's analysis and test scripts, pairwise across each interface
   first, then all together (§4, §8). With one interface pair, or one module, the pairwise run is
   the whole run.
2. Record per run: command, commit, exit status, the output or the file it wrote, and the interface
   pair it covers.
3. A failing run is recorded against the module whose script failed, with its output; do not edit
   that module to make it pass (§1).

## Procedure: the chain behind each system requirement

For each requirement the plan lists for integration, one row per link (§11):

| Requirement | Link | Module | Value as built, unit, where read | Value as analysed | Agree? |
|---|---|---|---|---|---|
| e.g. "drives at 1.2 m/s" | speed command applied by the program | firmware | constant, file and line | control's node | yes, or: held at zero |

1. Read each link from the module's own files and nodes, not from its summary.
2. A link nothing produces is a finding against the plan, with the requirement, the link and what
   was found; the requirement goes in the limits statement as not verified (§11).
3. Run the chain closed with a host build or an interpreter model of the control law, driven by
   the designer's plant model and the speed command read from the program's files, and record the
   run (§4); name the check as not shown only with the missing tool named.

## Procedure: the open items

1. From each module's record, list the inputs its specification did not give and what it did not
   show; from sizing's and control's records, each conflict, open point and request (§12).
2. For each: module, quantity, what resolves it. Name any safety input among them (a stale-command
   path, the board's state in reset, a fault count). For each request: the value needed, the
   owner's bound and the outcome (taken up with the new value, declined with the reason, or left
   without a reply), read from the module's record and from the defect its review recorded for it.
   A request not taken up leaves its criterion not met at those ends, and a system
   requirement resting on it is stated as not met, never met (§12).
3. Read any decision note you are given with the records; list what it carries, and what it
   approved as an open residual, beside the rest.

## Procedure: the limits statement

Write in plain words (§5):

1. What was exercised: which scripts ran together, which interface clauses were checked, which
   simulation records were read.
2. What was not: for example firmware against a simulated plant, timing on the target board,
   hardware in the loop.
3. Which acceptance criteria of the brief therefore stay unverified at system level.

## Procedure: the completion declaration

Per module, one line per precondition with its evidence (§9): accepted attempt; each interface
clause it takes part in passed; the recorded contract result of each pair it takes part in passed,
or none is recorded yet; no open dispute on its quantities; the system-scope gate passed, or the
run's automated checks were switched off and the record says so; the composition ran; the limits
stated. A module with any precondition open is listed as not
complete, with the open item named.

## Antipatterns

- **A requirement reported met that only the analysis shows.** The built program never applies the
  command the design assumed (§11).
- **Open items taken from the modules' summaries.** What a module records it was not given is
  listed with it, whatever its review found (§12).
- **Re-reviewing a module instead of composing it.** Integration checks the parts together; the
  domain review already judged each alone (§1).
- **Fixing another module in place.** A drifted value is recorded against its owner, never
  rewritten by integration (§1, §10).
- **An interface checked from one side.** The producer's node agreeing with the interface says
  nothing about what the consumer used (§2).
- **Matching numbers without units.** The same number in two units is two values; the Mars Climate
  Orbiter's interface failed this way (§2).
- **Assumptions left implicit.** A consumer's unstated range or timing is the Ariane 501 failure
  (§3).
- **Scripts run alone, called a composition.** Each module passing its own tests on its own copy
  is not integration (§4).
- **A result with no recorded run.** Output that is not in the record evidences nothing (§4).
- **"Works end to end" with no scope.** A claim beyond what was exercised hides what was never
  tested (§5).
- **A simulation summary without its record.** A figure that names no record, or a record run on
  older values, is not evidence (§6).
- **Excusing a system-scope gate failure.** The gate decides; integration records (§7).
- **Everything at once.** A big-bang run cannot say which interface failed (§8).
- **Completion declared with a precondition open.** A narrative does not close a failed clause, a
  failed contract result or an open dispute (§9).
- **Choosing a side in a mismatch.** An interface disagreement is recorded with both values, not
  settled by integration (§10).
