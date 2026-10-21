# Integration — standards

> Researched and drafted from published sources (the NASA Systems Engineering Handbook, the Systems
> Engineering Body of Knowledge, and two failure inquiry reports) by an agent, and approved by a
> person before use. Every number carries its source and its kind: *derived* (definition, theorem or
> arithmetic; never relaxed), *normative* (a rule of the cited document), or *rule of thumb /
> typical value* (a published practice a sourced analysis may override). A *harness basis* is a
> number this harness sets for its own records, not taken from a source about hardware: normative,
> never widened. Read `knowledge/cross/standards.md` first; this file does not repeat it. The domain standards hold
> each domain's own checks; this file holds what integration owns: interface satisfaction,
> behaviour of the modules together, and the completion declaration.

## 1. Integration verifies the modules together; it does not redo or overrule their review

Integration "iteratively combines implemented system elements to form complete or partial system
configurations in order to build a product or service" [ISO/IEC/IEEE 15288:2015, p. 68, as quoted
by SEBoK authors, "System Integration", *Guide to the Systems Engineering Body of Knowledge*,
v. 2.14, 2026; retrieved 21.10.2026]. In SEBoK's own words, integration is "to check correctness of
static and dynamic aspects of interfaces between the implemented elements" (ibid.). Before
assembling, "confirm that the received products ... have been validated ... including interface
requirements" [NASA, *NASA Systems Engineering Handbook*, NASA/SP-2016-6105 Rev 2, 2016,
§5.2.1.2.3, p. 100]. So integration reads, for each module, that its attempt was accepted, which
criteria it met and what its domain recorded; it does not re-judge a domain's design, and it writes
no node another role owns. A defect it finds in a module is recorded against that module for its
owner, not fixed in place.

**Enforced:** the hook layer's ownership rules and the store's role guard refuse a write to a node
by a role that does not own it. Whether integration re-judged a domain instead of composing it is
judgement.

## 2. Every interface quantity is checked, clause by clause, against what its producer and each consumer wrote

An interface is "the pathway of system interactions" [NASA SE Handbook, §5.2, p. 97]; "every
interface and interaction between implemented elements is verified" [SEBoK, "System Integration",
checking items]. For each quantity on an interface node, read the value the producer's module wrote
and the value each consumer's module used, and check that the name, the dimension and the value
after unit conversion agree. Values agree when they differ by no more than 1e-9 of the larger
magnitude, |a − b| ≤ 1e-9 × max(|a|, |b|): a representation tolerance that absorbs the rounding of
a conversion, not an engineering margin (a *harness basis*, the tolerance its contract check is
specified with). With no absolute term, a value of zero agrees only with zero; whether one is added
is left to the contract check's frozen criteria. A consumer that reads the value under another
name, in another unit without a shown conversion, or with another number has broken the
interface, whichever side drifted. The Mars Climate Orbiter's interface specification required
impulse in "Newton-seconds
(N-s)"; the producer wrote "pound-seconds (lbf-s)", the consumer "assumed the data was provided in
metric units", and the trajectory was underestimated "by a factor of 4.45" [Mars Climate Orbiter
Mishap Investigation Board, *Phase I Report*, 10 November 1999, pp. 6, 16].

**Judgement-only** — gate check 1 (`check_units.py`) checks the units of committed expressions and
check 7 (`check_propagation.py`) the follow-up of changed quantities; neither compares what a
producer and its consumers wrote for one interface quantity. A contract check that compares them at
this tolerance and records one result per pair is specified for the harness but not yet built; once
it is, its recorded result is an input to completion (§9), and integration's own clause record is
still judgement.

## 3. Assumptions one module makes about another's values are found and checked against the other's limits

The Ariane 5 inquiry asked to "identify all implicit assumptions made by the code and its
justification documents on the values of quantities provided by the equipment" and to "check these
assumptions against the restrictions on use of the equipment", and to "verify the range of values
taken by any internal or communication variables" [Inquiry Board (J. L. Lions, chair), *Ariane 5
Flight 501 Failure*, 19 July 1996, §4, recommendation R5]. For each interface, list what the
consumer assumes beyond the value (range, sign convention, rate, latency, frame, saturation) and
what the producer guarantees; a consumer range wider than the producer's, or an assumption the
producer never states, is a finding.

**Judgement-only** — no check compares one module's assumptions with another's limits.

## 4. Composition is exercised by running it, and every run is recorded

After assembly, "functional testing of the assembled or integrated unit is conducted"; "all or key
representative functions are checked" [NASA SE Handbook, §5.2.1.2.5, p. 101]. In this harness that
means running every module's own analysis and test scripts together on the merged state, with the
cross and interface values as they now stand, not each module's scripts against its own copy. Each
run is recorded with its command, the commit it ran at, its exit status and the output it produced;
work products include "identified anomalies and associated corrective actions" (ibid.,
§5.2.1.2.7, p. 101). A script that was not run, or whose output is not in the record, evidences
nothing.

**Judgement-only** — no check confirms that integration ran a module's scripts or recorded their
output.

## 5. An end-to-end claim names the environment it was exercised in, and what that environment leaves out

"As the saying goes, 'Test as you fly, and fly as you test'" [NASA SE Handbook, §5.3, box "Methods
of Verification", p. 108]. On Ariane 501, "no test was performed to verify that the SRI would behave
correctly when being subjected to the count-down and flight time sequence and the trajectory of
Ariane 5"; the board found that a "declaration of limitation ... should be mandatory for every
mission-critical device", and recommended "complete, closed-loop, system testing" with "realistic
input data" [Ariane 5 inquiry, §2.3; §4, R2]. So the integration record says, in words, what the
composition exercised (host-side analysis and test scripts together, simulation records read, the
interface clauses) and what it did not (for example firmware running against a simulated plant, or
timing on the target). A claim of end-to-end behaviour beyond what was exercised is a finding.

**Judgement-only** — nothing in code reads the scope of an end-to-end claim.

## 6. A simulation result is evidence only as the record it came from

A stability, margin or tracking claim taken from a simulation names the record it came from and the
quantity read from it; a quantity read off a simulation record names that record (the `series`
field of the quantity record). A summary figure with no record behind it, or a record whose run
used different values from the ones now on the graph, does not evidence the claim.

**Enforced:** the schema carries a quantity's simulation record reference, and a quantity that
names a record is checked against that record before the attempt reaches the gate. Whether a claim
in prose cites a record, and whether the record ran on today's values, is judgement.

## 7. The system-scope gate result is an input, never overridden

The gate's checks at system scope (cross-domain standards §3 to §6) run on the merged design before
integration's work, and their result is part of the state integration reads. A failure there is the
gate's to decide, not integration's to excuse; integration records it and does not declare a
module complete while it stands. When the run's automated checks are switched off there is no
system-scope result; the record says so, and the limits statement names it (§5).

**Enforced:** once every subtask is merged the loop runs the gate on the whole design at system
scope; with the gate on, a failure becomes an approval-queue item and the run ends escalated.
Whether integration's record treats the result as decided is judgement.

## 8. Integrate in an order that localises faults, and record the order

"The 'big-bang' integration technique is not appropriate for a fast detection of faults. It is thus
preferable to verify the interfaces progressively"; in incremental integration "a new fault is
usually localized in lately integrated implemented elements or dependent of a faulty interface"
[SEBoK, "System Integration", Tables 1 and 4] (*rule of thumb*). Within one integration pass,
compose across each interface pair before the whole, and record the order, so that a failure
names the pair it first appeared at. With one interface pair, or one module, the pair is the whole
and there is no order to record.

**Judgement-only** — no check reads the order of composition.

## 9. Completion is declared per module only when every precondition holds, with its evidence

A module is complete when its attempt was accepted, every interface it takes part in has passed its
clauses (§2), the harness's recorded contract result for every pair it takes part in passed where
one is recorded (a failed contract never blocks a merge, but it withholds completion), no dispute
on a quantity it uses is open, the system-scope result passed or, with the run's automated checks
switched off, the record says there was none (§7), the composition ran (§4) and the record states
its limits (§5). The declaration lists, for each module,
the evidence for each of these, and the integration product's outputs are "integrated product(s)
with all system interactions identified and properly balanced" with "identification of limitations
for both hardware and software" [NASA SE Handbook, §5.2.1.3, p. 101]. A precondition that is open
withholds the declaration for that module; it is not waived by a narrative.

**To be enforced** once the harness's completion code lands; it does not exist yet. Then only
integration's accepted attempt is to cause a module's completion, and code is to withhold it while
a registered precondition is open. Until then the whole of this rule is judgement, and whether the
evidence listed supports each precondition stays judgement after.

## 10. Interface records carry their decisions and changes

Interface documentation "identifies and captures the interface information and the approved
interface change requests", with "rationale for interface decisions made" and "actions taken to
correct identified interface anomalies" [NASA SE Handbook, §6.3.1.3 and §6.3.1.2.5, pp. 158–159].
Interface nodes are fixed at decomposition; a mismatch integration finds is recorded against the
module that drifted from the interface, with the quantity and both values, never resolved by
choosing one side.

**Enforced:** interface nodes are immutable after decomposition (the store and the hook refuse a
write to one). The content of the record is judgement.
