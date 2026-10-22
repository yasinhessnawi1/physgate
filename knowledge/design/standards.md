# Design — standards

> Researched and drafted from published sources (the NASA Systems Engineering Handbook, the Systems
> Engineering Body of Knowledge, Parnas's paper on modular decomposition, and a failure inquiry
> report) by an agent, and approved by a person before use. Every number carries its source and its
> kind: *derived* (definition, theorem or arithmetic; never relaxed), *normative* (a rule of the
> cited document or of this harness), or *rule of thumb / typical value* (a published practice a
> sourced analysis may override). A *harness basis* is a number this harness sets for its own
> records, not taken from a source about hardware: normative, never widened. Read
> `knowledge/cross/standards.md` first; this file does not repeat it. It holds the rules for a plan: the decomposition of a brief into modules, their
> specifications and the interface nodes between them.

## 1. Every requirement of the brief is allocated, and every criterion traces back

Bidirectional traceability is "the ability to trace any given requirement/expectation to its parent
requirement/expectation and to its allocated children" [NASA, *NASA Systems Engineering Handbook*,
NASA/SP-2016-6105 Rev 2, 2016, §6.2, p. 150]. Each requirement the brief states (a function, a
performance figure, a constraint, a part to be used) is allocated to at least one module's
acceptance criteria, or to an interface node, or is stated in the plan as not allocated, with the
reason. The plan's form holds modules, with their specifications, and interface nodes, and nothing
at plan level, so a record about the plan as a whole (a requirement not allocated, a conflict in
the brief) goes in the specification of the module it concerns, or of any module where it concerns
none, under a heading that names it. Each acceptance criterion of a module traces to a requirement of the brief, or is "identified
as self-derived" (ibid., §6.2.1.2.3, p. 152) with its reason (a good practice, or a decision the
decomposition made). The trace "fully addresses its parent": "if it does not, some other
requirement(s) should complete fulfillment of the parent" (ibid.).

**Judgement-only** — no check traces a brief's requirements to a plan's criteria.

## 2. Modules follow the run's roles, and each hides the decisions its role owns

The architecture assigns each domain role what it owns (concept and decomposition, geometry,
component selection and power budget, plant and controller, drivers and real-time loop) [the
project's architecture specification, ARCH-050]; a module is the work of one role. Within that,
decompose by what may change, not by processing steps: "one begins with a list of difficult design
decisions or design decisions which are likely to change. Each module is then designed to hide such
a decision from the others" [D. L. Parnas, "On the Criteria To Be Used in Decomposing Systems into
Modules", *Communications of the ACM* 15(12), 1972, p. 1058]. The interface between modules is
"chosen to reveal as little as possible about its inner workings" (ibid., p. 1056), and
requirements are "as weakly coupled as possible" so "ripple effects from changes are minimized"
[NASA SE Handbook, Appendix C.4, p. 239]. A module whose specification needs another module's
internals to be met has its boundary in the wrong place.

**Enforced:** the plan checks refuse a module assigned a role the run has no model for, two modules
with one name, and overlapping module directories. Whether a boundary hides the right decisions is
judgement.

## 3. Every quantity that crosses a module boundary is on an interface node its producer owns

Interface management means to "define interfaces" and "identify the characteristics of the
interfaces" [NASA SE Handbook, §6.3, p. 156], including their "origin, destination, stimuli, and
special characteristics" (ibid., §6.3.1.2.2, p. 158). Each quantity one module produces and another
reads is a quantity on an interface node: value, unit, source and writer, owned by the producing
role, with the consumers named where the plan names them. A quantity has one producer: two modules that
both owe it, or two interface nodes of different owners that both carry it, leave the difference
between them owned by no one (§5). "Are all internal interfaces clearly
defined? ... Are all interfaces necessary, sufficient, and consistent with each other?" (ibid.,
Appendix C.4, pp. 238–239). An interface node is fixed once the plan is accepted, so its values are
the plan's commitment.

**Enforced:** the schema refuses a quantity without a value, unit, source and writer; the plan
checks refuse a node that is not of kind interface, two interface nodes with one id, a node owned
by a role no module has, and a quantity name that shadows one a relation reads. Whether every
crossing quantity has a node is judgement.

## 4. A quantity that constrains more than one domain is given to sizing, not fixed twice

Sizing owns "every quantity constraining more than one domain" [architecture specification,
ARCH-051]. When the run has a sizing module, the plan names such quantities in sizing's
specification and does not state them, with values of its own, in two domain specifications. When
it has none, a shared value is stated once, on an interface node or in one specification that the
others cite.

**Judgement-only** — no check yet reads which plan quantities constrain more than one domain.

## 5. One value, one place

A number that appears in two specifications, or in a specification and an interface node, is the
same quantity, with the same unit and value; better, the specification cites the node. Two values
are the same when, after conversion, they differ by no more than 1e-9 of the larger magnitude: a
representation tolerance for conversion rounding, not an engineering margin (a *harness basis*,
the tolerance it compares interface values with). With no absolute term, a value of zero agrees
only with zero; whether one is added is left to the contract check's frozen criteria. The Mars
Climate Orbiter was lost when one side of an interface wrote "pound-seconds (lbf-s)" where its
specification required "Newton-seconds (N-s)", a factor of 4.45 [Mars Climate Orbiter Mishap
Investigation Board, *Phase I Report*, 10 November 1999, p. 16]. Requirements are to be "stated
consistently without contradicting themselves or the requirements of related systems" [NASA SE
Handbook, Appendix C.4, p. 238].

**Judgement-only** — no check compares numbers across specifications.

## 6. Each specification numbers its acceptance criteria, and each criterion can be verified at the module's level

Criteria are numbered lines under a heading that names acceptance criteria; the review contract
counts them that way, and a specification that does not leaves its criteria uncountable. Each
criterion states what is checked, the threshold with its unit and tolerance ("complete with
tolerances", NASA SE Handbook, Appendix C.2, p. 236), and how it is verified: analysis,
demonstration, inspection or test (ibid., §5.3, box "Methods of Verification", p. 108). It is
verifiable at the module's own level: "Can this be done at the level of the system at which the
requirement is stated?" (ibid., Appendix C.4, p. 239). A requirement only the assembled system can show (behaviour across modules, end to end) is
allocated to integration, with the module criteria that contribute to it named. The harness, not
the decomposition, writes integration's specification, from the recorded plan; so the allocation
belongs in the plan's list of system requirements allocated to integration, apart from its modules
and interface nodes. Where the plan's form has no such list, the allocation has no place to be
written, and the contributing modules' criteria are what the plan can show.

**Enforced:** the review contract reads a specification's numbered lines under an
acceptance-criteria heading and holds each review to one line per criterion. Whether a criterion
is verifiable is judgement.

## 7. A requirement says what, in one statement, without ambiguous terms

"Shall = requirement", "Will = facts or declaration of purpose", "Should = goal" [NASA SE Handbook,
Appendix C.1, p. 236]. One thought per statement, one subject and one predicate; "free from
indefinite pronouns (this, these) and ambiguous terms (e.g., 'as appropriate,' 'etc.,' 'and/or,'
'but not limited to')" (ibid., Appendix C.4, p. 237). Requirements "state WHAT is needed, NOT HOW to
provide it" (ibid., Appendix C.2, p. 236); where a specification does fix a method (a part the brief
names, a controller structure), "the rationale should state why the decision was made to limit the
solution to this one method" (ibid., §4.2.1.2.3, box "Rationale", p. 70).

**Judgement-only** — no check reads a requirement's wording.

## 8. Unknowns are stated, not invented

"The use of 'To Be Determined' (TBD) values should be minimized. It is better to use a best
estimate for a value and mark it 'To Be Resolved' (TBR) with the rationale along with what should be
done to eliminate the TBR" [NASA SE Handbook, Appendix C.3, p. 237]; "Have all assumptions been
explicitly stated?" (ibid., Appendix C.4, p. 237). A value the brief does not give is either derived
with its derivation shown, taken from a cited source, or marked as an estimate to be resolved, with
who resolves it. A requirement of the brief that contradicts another is recorded in the plan with
both statements, and how the plan treats it (in a specification, §1), not resolved silently.

**Judgement-only** — no check reads whether a value was estimated.

## 9. Each specification is complete for its implementer

An implementer reads its own specification, the standards and skill files, and the interface
contracts touching its module before any other action [architecture specification, ARCH-020].
So a specification states, or cites by node, everything the module's work needs from outside it:
the inputs it receives and from where, the outputs it owes and to whom, the parts and values it
must use, and its criteria. A specification is at most 32,768 characters. A specification that
relies on the implementer reading another module's specification is incomplete.

**Enforced:** the plan's schema refuses a specification longer than 32,768 characters, and the
mandatory-reading hook holds an implementer to its reading set. Whether a specification is
complete is judgement.

## 10. The criteria together meet the brief, and none is tighter or looser than it needs

"Are all described functions necessary and together sufficient to meet mission and system goals
and objectives?"; functions are arranged "so that any specified operational usage of the system can
be traced in an end-to-end path" [NASA SE Handbook, Appendix C.4, p. 238; §4.3.1.2.2, p. 75].
"Are the tolerances overly tight? ... Ask, 'What is the worst thing that could happen if the
tolerance was doubled or tripled?'" (ibid., Appendix C.4, p. 238); requirements are not
"redundant or over-specified" (ibid., §4.2.1.2.4, step 6, p. 71). A criterion looser than the brief's
requirement it traces to does not meet the brief; a criterion the brief's parts cannot meet is
flagged in the plan, not left to fail in a module.

**Judgement-only** — no check compares criteria with the brief.

## 11. Integration is planned with the decomposition

"Interfaces are defined in this phase and are the pathway of system interactions" [NASA SE
Handbook, §5.2, p. 97]. Ariane 501's inertial system was never tested against its new trajectory
because "the SRI specification ... does not contain the Ariane 5 trajectory data as a functional
requirement" [Inquiry Board (J. L. Lions, chair), *Ariane 5 Flight 501 Failure*, 19 July 1996,
§2.3]; the board recommended to "include trajectory data in specifications and test requirements"
(ibid., §4, R10). So the operating conditions a module must meet (ranges, rates, load cases) are in
its specification, and the system-level requirements that only integration can verify are
allocated to it as §6 says.

**Judgement-only** — no check reads a plan's integration content.
