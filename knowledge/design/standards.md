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

## 3. Every quantity that crosses a module boundary is on an interface node its producer owns; a design another module implements is read from its designer's own node

Interface management means to "define interfaces" and "identify the characteristics of the
interfaces" [NASA SE Handbook, §6.3, p. 156], including their "origin, destination, stimuli, and
special characteristics" (ibid., §6.3.1.2.2, p. 158). Each quantity one module produces and another
reads is a quantity on an interface node: value, unit, source and writer, owned by the producing
role, with the consumers named where the plan names them. A quantity has one producer: two modules that
both owe it, or two interface nodes of different owners that both carry it, leave the difference
between them owned by no one (§5). An interface node is fixed once the plan is accepted, so its values are
the plan's commitment.

So an interface node holds what both sides must agree on before either works: the signals that
cross, each with its unit and rate, the limits both sides hold to (a command range, a sample
period, a supply), and the physical properties one side gives the other (a mass, a motor
constant). It never holds a solution's tuned parameters. A value one module chooses while
doing its own work, such as a controller's coefficients, is that module's hidden decision (§2: the
interface reveals "as little as possible about its inner workings", Parnas 1972, p. 1056); fixed on
an interface node at plan time, it is taken from the module that owns it, and no session can change
it afterwards (interface nodes are written by the harness alone [architecture specification,
ARCH-011]). Where another module must implement that design (firmware running the control law that
control analysed), the plan does three things. The designing module writes its design (the law's
form and every coefficient, each a value with its unit) on a node of its own, which both
specifications name. The designing module comes before the implementing one in the plan, so its
merged node can be there when the implementer starts; where it is not, the implementer reports that
and implements no design of its own. And the implementing module's acceptance criteria compare the
implementation with that node as merged, each coefficient equal within §5's tolerance.
The interface node between them still carries the signals and limits.

**Enforced:** the schema refuses a quantity without a value, unit, source and writer; the plan
checks refuse a node that is not of kind interface, two interface nodes with one id, a node owned
by a role no module has, and a quantity name that shadows one a relation reads. Whether every
crossing quantity has a node, and whether a quantity on an interface node is a tuned parameter, is
judgement: by name and unit a coefficient and a limit look alike.

## 4. A quantity that constrains more than one domain is given to sizing, not fixed twice

Sizing owns "every quantity constraining more than one domain" [architecture specification,
ARCH-051]. When the run has a sizing module, the plan names such quantities in sizing's
specification and does not state them, with values of its own, in two domain specifications. When
it has none, a shared value is stated once, on an interface node or in one specification that the
others cite. A motor's stall current is `stall_current` at the voltage the brief pins; its figure at
the top of the pack is `stall_current_max`, and no plan node holds `peak_stall_current` for a brief
that pins the voltage (sizing standards §10).

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
Investigation Board, *Phase I Report*, 10 November 1999, p. 16].

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

A criterion is written only as the run environment can measure it (*normative*, this harness's
rule). A module's sessions have programs and files, and no physical board or instrument is
connected to them unless the brief says one is; a part a person has is not thereby connected. The
planner is shown no description of the environment, so what the plan relies on it states in the
specification of the module that relies on it, as an assumption with who resolves it (§8). The
standard tool environment holds the target's compiler (PlatformIO's avr-gcc) and `avrsim`, a
simulator of the ATmega32U4 with a model of the Balboa 32U4 board that runs the program built for
the board. A criterion on the board's own behaviour (an update's timing and lateness, the PWM
frequency and full scale at the pin, the encoder counting, a trip path's timing, the watchdog) is
written against `avrsim`, names it, the scenario it is shown under and the quantity read from its
summary, and says it is simulated, not measured on a board. A module whose session finds `avrsim`
absent states that criterion as not shown (firmware standards §12); a criterion `avrsim` cannot
show is written against what the run can measure with the compiler (a build without a warning in
the module's own files, its size, a check of its logic). A host-side test is named only
where the run environment records a host compiler, and a static analyser's run only where it
provides an analyser. A requirement the run cannot show (the loop closed; a sensor's noise and
filter delay; the clock's tolerance; the motor driver's electrical behaviour; what the board's
wiring sets) is not made a module's criterion: the plan records it as not shown in this run, with
the reason (§1).

**Enforced:** the review contract reads a specification's numbered lines under an
acceptance-criteria heading and holds each review to one line per criterion. Whether a criterion
is verifiable, and measurable in the run environment, is judgement.

## 7. A requirement says what, in one statement, without ambiguous terms

"Shall = requirement", "Will = facts or declaration of purpose", "Should = goal" [NASA SE Handbook,
Appendix C.1, p. 236]. One thought per statement, one subject and one predicate; "free from
indefinite pronouns (this, these) and ambiguous terms (e.g., 'as appropriate,' 'etc.,' 'and/or,'
'but not limited to')" (ibid., Appendix C.4, p. 237). Requirements "state WHAT is needed, NOT HOW to
provide it" (ibid., Appendix C.2, p. 236). A specification fixes a method (a structure, a law, an
algorithm, a set of coefficients) only where the brief itself requires that method, and then cites
the brief's requirement as its rationale: "the rationale should state why the decision was made to
limit the solution to this one method" (ibid., §4.2.1.2.3, box "Rationale", p. 70). A part the brief
names is such a requirement.

**Requires or cites.** The brief *requires* a method when one of its own requirements, read in its
own words, is met only if the method is used: it says the design shall use, run or contain it ("the
firmware shall run the maker's balancing program unchanged"). The brief *cites* a method when it
names a reference as the source of a number, a part or a condition ("the 10 ms update period of the
maker's example program"), or as background. A citation makes the numbers the brief's; the method
stays free. The test: strike the method from the specification and ask whether the plan, as
written, still carries every requirement of the brief. If it does, the brief cites the method and
does not require it. A requirement
that one module's implementation match what another module analysed (the firmware runs the
controller whose margins were shown) asks for consistency, not for a method: §3's route meets it,
whatever the method. Where the reading is in doubt, the plan leaves the method free and records the
doubt, with both readings, in the specification it concerns (§8), for the person who owns the brief.

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

## 12. A behaviour of the built system is allocated to every link that produces it

A requirement that names what the built system does (it drives at a speed, recovers from a push,
stops when it falls) is produced by a chain, and each link is a place where it can be missing: the
source of the command or input (who commands the speed, from what input, in what value and unit);
the law that follows it (the designing module); the code that applies it, reading the same value
(the implementing module); the plant that responds (sizing's quantities); and a check of the built
chain, not of each link alone. Functions are to be arranged "so that any specified operational usage
of the system can be traced in an end-to-end path" [NASA SE Handbook, §4.3.1.2.2]. A requirement
allocated to the module that analyses it and to no module that produces it is shown in an analysis
only: the system built never does it. So for each such requirement the plan (a) names the module
that produces the command or input and the implementing module that applies it (the one whose built
program reads the value), where the value comes from (a constant of the brief, a sensor, a person)
and its value and unit (the brief's value, or, for a one-sided bound, a command away from it by a stated margin, below), on the node
both modules read (§3); (b) gives the implementing module a criterion that its built program applies
the value read from that node, verified by a means the run environment provides (§6); (c) lists the
requirement in the plan's list for integration with the criteria of every link (§6); and (d) in the
specification of the module that closes the chain, under a heading "System checks", names each
quantity integration compares across the links (the value applied against the value analysed) and
the check it runs, or says the check is not shown in this run, with the reason (§1). A requirement
of the brief with a link no module owns is recorded in the plan as not allocated, with the reason,
only where the brief itself leaves that link to a person; where a module of the plan could produce
it, that module is given it.

Where the brief's criterion is a one-sided bound ("at least", "at most") on a quantity the system is commanded to (a speed, a position, a rate), the plan sets the command away from the bound, on the side that keeps it met, by a margin it states with its reason, and says which criterion the margin serves. A command equal to the bound leaves the criterion no room for the means' tolerance and is a finding. The brief's criterion stays as issued: the margin is the plan's choice, and the brief is neither relaxed nor tightened. A module that cannot reach the commanded value reports it and does not lower the command.

**Judgement-only** — no check follows a requirement through the modules that produce it.

## 13. A module that drives a motor is given the values of its safety checks, each with its source

Five checks need a value the implementing module cannot derive from its own work, and a module
given none can only choose one or leave the check out. The plan states each in the module's
specification with a value (the planner's rule for limits, timeouts and fault behaviour), a source
and, where it is the plan's own choice, the derivation:

1. *A stale command.* A loop that hangs holds its last motor command. The value, the stale-command
   timeout, is the longest time between refreshes before the motors go off, in ms, or the
   requirement of a watchdog that bounds it. A plant that falls by itself leaves its recoverable
   range in a time set by its fall time constant, which a stale command does not oppose, so the
   timeout is a few update periods and well under that constant (*derived* from the plant, stated as
   the plan's choice). The ATmega32U4's watchdog timer takes a time-out from 16 ms to 8 s, and in
   System Reset mode "is typically used to prevent system hang-up in case of runaway code"
   [Microchip, *ATmega16U4/ATmega32U4 datasheet*, Atmel-7766J, 2016, §8.9, Table 8-5]: a bound under
   16 ms needs another mechanism, named.
2. *A sensor fault during operation.* The count N of consecutive failed or implausible reads, or the
   time T without a valid read, that turns the motors off. The fault at power-up is another check.
   N update periods are within the stale-command timeout of check 1 (*derived*).
3. *The motor driver while the processor is in reset.* The state the board leaves the driver's
   inputs in, with its source. The ATmega32U4's port pins are tri-stated while a reset is active
   [ibid., §10.2.1]; each input of the DRV8838 has "a weak pulldown resistor" to ground, RPD 100 kΩ
   on PH and EN and 55 kΩ on nSLEEP [Texas Instruments, *DRV8837, DRV8838*, SLVSBA4F, revised April
   2021, §7.3.4 and the electrical characteristics], and its Table 7-2 reads enable low as Brake
   with nSLEEP high and nSLEEP low as Coast (§7.4: outputs Hi-Z). Whatever the board adds to those
   inputs decides, so the source is the board maker's schematic; where the plan has none, it records
   the state as not shown.
4. *A wait on the bus that never ends.* The bus's time-out value. I²C sets none, and a loop on a
   status bit needs "a fixed upper-bound" [G. J. Holzmann, "The Power of 10", *IEEE Computer*
   39(6), 2006, rule 2]. The value is a stated multiple of the bytes of the longest transfer at the
   configured rate, nine bit times a byte (eight data bits and an acknowledge, *derived*), and no
   longer than the stale-command timeout leaves.
5. *The sensor's own filter.* Its bandwidth and the delay it adds, against the rate at which the
   samples are used and the plant's unstable pole. For the LSM6DS33 gyroscope the digital low-pass
   cutoff follows the output data rate and the power mode (60.2 Hz at 208 Hz in normal mode, 66.7 Hz
   in high-performance mode, which the reset state of the mode bit G_HM_MODE selects; the output
   data rate itself resets to power-down and must be set, register CTRL2_G of the datasheet) and the
   maker gives no other setting of the digital filter [STMicroelectronics, *AN4682*, DocID027736 Rev
   1, §2.7, Tables 13 and 14]: the plan states "not settable", the mode the program selects and the
   delay with its document or measurement. The plan owns this value: control uses it, and firmware
   checks the configured setting against it. Content above half the rate of use aliases (the
   antialiasing filter is chosen below it), and a bandwidth under ten times the unstable pole costs
   the loop its margin, so the plan compares the figure with both.

A value the plan cannot source is written as an estimate to be resolved, with its derivation and who
resolves it (§8), never left out.

**Judgement-only** — no check reads whether a plan gives a module its safety values.
