# Sizing — standards

> Researched and drafted from published sources (the NASA Systems Engineering Handbook, motor,
> driver and cell makers' datasheets, handbooks and product pages, and a robot maker's user's guide
> and motor library) by an agent, and approved by a person before use. Every number carries its
> source; a number that sets a rule or a limit also carries its kind: *derived* (definition,
> physical law or arithmetic; never relaxed), *normative* (a rule of the cited document, a maker's
> rating, or a rule of this harness), *model* (a stated modelling choice, with its assumptions), or
> *rule of thumb / typical value* (a published practice a sourced analysis may override). A
> *borrowed basis* is a number taken from a source for a class of hardware or practice the source
> does not cover: a rule of thumb, never a limit. Read `knowledge/cross/standards.md` first; this
> file does not repeat it. It holds what sizing owns: the quantities more than one domain depends
> on, written once, and kept true to the domains' work.

## 1. Sizing writes every cross quantity, and nothing else

Sizing owns "every quantity constraining more than one domain" [the project's architecture
specification, ARCH-051]: a supply voltage, a motor's command limit, torque and current, a current
budget, a mass, a gear ratio, any other quantity two domains read. It writes them on nodes of
domain `cross` that are not interface nodes, and writes no node of a domain role and no interface
node. A quantity only one domain reads is that domain's, not sizing's; a quantity two domains read
and the plan left off sizing's nodes is recorded in sizing's work as unowned, with the domains that
read it, not written by a domain in sizing's place.

**Enforced:** the hook layer and the change check refuse a write to a non-interface `cross` node by
any role but the one that owns the cross nodes, and a write by that role to any node of another
domain; no session creates an interface node. Whether a quantity is truly cross is judgement.

## 2. Every cross value says where it came from, at what condition

A cross value is one of three things, and its `source` says which: a value the brief states
(quoted, with the brief's criterion); a maker's figure (the document, its revision or date, and
the condition it holds at: a voltage, a temperature, a gear ratio); or a calculation from those
(the formula and every input, each with its own source). A value with none of these is a best
estimate, marked as requirement writing marks an unsettled value: "It is better to use a best
estimate for a value and mark it 'To Be Resolved' (TBR) with the rationale along with what should
be done to eliminate the TBR, who is responsible for its elimination, and by when it should be
eliminated" [NASA, *NASA Systems Engineering Handbook*, NASA/SP-2016-6105 Rev 2, 2016, Appendix C,
checklist] (*borrowed basis*: written for requirement values, applied here to design values). A
TBR names its rationale, what would resolve it and who; "by when" is left out, since no pass sets
a date. A maker's figure is quoted at its own condition and not reused at another without the
conversion shown (§4, §5).

**Judgement-only** — the schema refuses a quantity without a source (cross §1); nothing reads
whether the source supports the number.

## 3. A value the brief fixes is written as the brief states it, and a conflict is recorded, never resolved by sizing

Where a criterion of the brief fixes a cross quantity (a part, a limit, a rating), sizing writes
that value, converted where needed with the conversion shown, and does not move it to make another
criterion easier to meet. The one exception is a value a person chose on a dispute, carried to the
pass by the harness's order: that value is written instead (§11). Where two requirements conflict
(a limit that a performance criterion cannot be met within), sizing writes the value the brief
fixes and records the conflict in its module's record, cited from that value's `source`: both
statements, the calculation that shows the conflict, and the criterion it puts at risk.
Requirements are to be "stated consistently without contradicting themselves" [NASA SE Handbook,
Appendix C, checklist]; finding a contradiction is sizing's to record, and deciding it is a
person's. A domain that disagrees with a cross value disputes it; the harness rules on the dispute
by fixed precedence (the physics checks, then sizing, then a person) and no session negotiates
[architecture specification, ARCH-040].

**Enforced:** in part. A domain's dispute is ruled by the harness's fixed precedence, after the
automated checks, and never reaches sizing's session; a repeat dispute of a quantity, or one on the
disputing subtask's last attempt, goes to a person. Whether sizing recorded a conflict it could see
is judgement.

## 4. A supply voltage is a range, and each demand is checked at the end of the range that is worst for it

A battery's voltage falls as it discharges: on the Balboa robot, "as your batteries run out, the
voltage supplied to the motor drivers (VSW) will decrease, which will make the motors slower"
[Pololu, *Pololu Balboa 32U4 User's Guide*, §3.3, retrieved 31.10.2026]. A NiMH cell drops "from an
open-circuit voltage of approximately 1.4 volts to the 1.2 volt plateau", and "discharge cutoff is
based on voltage drops with a value of 0.9 volts per battery (75 percent of the 1.2 volt per battery
nominal mid-point voltage) often being used", "an excellent value for most medium to long-term
discharge for individual battery applications (<1C)"; at 1–4C that cut-off "may be premature", and
"75 percent of the mid-point voltage at that discharge rate" is the better choice [Energizer, *Nickel
Metal Hydride (NiMH) Handbook and Application Manual*, NiMH02.01, 2010, pp. 6 and 10] (*typical
value*). Six cells span about 8.4 V to 5.4 V (*derived*), the window the electrical standards use;
for a pack loaded above 1C (motors at stall) the bottom so taken is optimistic, and is stated so.
So a supply quantity carries its nominal value and the range it takes in use, each end with its
source: the top is the charged open-circuit voltage, and the bottom the cut-off less any drop under
load the design knows. A demand that grows with voltage (a stall current, the voltage across a part
against its rating, a dissipation) is checked at the top; a capability that falls with voltage (a
no-load speed, a torque at speed, a headroom) at the bottom. Where the specification pins a
criterion to one design voltage, that criterion is checked at it, and what the other ends give is
stated beside it as information; a demand against a part's rating is still checked at the top.

**Judgement-only** — the gate checks a value's size only where a bounds table gives its name or
kind a span (cross §3; none is loaded for a voltage), and a stall current against the current limit
on its own node or on the supply its edges name (§5, cross §4); nothing reads which end of a
voltage range a value was computed at.

## 5. A motor's operating points come from its published points, by a stated model

A brushed DC motor at steady state obeys `V = R·I + K_e·ω` and `T = K_t·I_T`, with `I_T` the current
that makes torque (*derived*, the motor's circuit and its torque law). From a maker's two points at
its rated voltage `V_r`, the usual fit is `R = V_r / I_stall` and `K_e = (V_r − I_noload·R) /
ω_noload`, and either `K_t = T_stall / I_stall` or, treating the no-load current as friction as the
`K_e` fit does, `K_t = T_stall / (I_stall − I_noload)` (*model*: friction current constant with
speed and voltage; the stall figures extrapolated). The fit chosen is stated and used throughout.
At another voltage `V` the stall current is `V / R` and the no-load speed `(V − I_noload·R) / K_e`
(*derived* from the model). For an ideal motor `K_t = K_e` in SI units, from the power balance
`K_e·ω·I = T·ω`; constants fitted at a gearbox output differ, because the output torque carries the
gearbox's losses and the friction current and the speed does not, so each is used where it was
fitted and neither is substituted for the other. A further gear stage multiplies `K_e` by its ratio
and `K_t` by its ratio times the stage's efficiency, taken as 1 where no efficiency is sourced and
stated as an assumption. A maker's stall figures may be extrapolated: Pololu's micro metal gearmotor
pages call them "theoretical values; stalls could damage the motor or gearbox", and give "a general
recommendation for brushed DC motor operation is 25% or less of the stall current" [Pololu, 50:1
Micro Metal Gearmotor HPCB 6V with Extended Motor Shaft, item #3073, retrieved 31.10.2026] (*rule
of thumb*; a sourced analysis may override it).

**Enforced:** in part: the gate holds a `stall_current` against a `current_limit` on its own node,
and against the `current_limit` of each supply its own `constrains` edges name (gate check 4); a
limit further along the path is not read, and a `stall_current` that no limit bounds, on its node or
on a node its edges name, is recorded unchecked, never passed. The fit and the conversions are
judgement.

## 6. A command limit becomes a voltage only at a stated supply voltage

A pulse-width command is a fraction of the supply: a driver that brakes during the off time (both
low-side switches on: the DRV8838's "Brake" row with `EN = 0` [Texas Instruments, *DRV883x
Low-Voltage H-Bridge Driver*, SLVSBA4F, revised April 2021, §7.3.1, Table 7-2]) applies on average
`D·V_supply` for duty `D` while its current is continuous (*derived*). On the Balboa the guide names
a direction pin and a PWM speed pin per driver [User's Guide, §3.3], and the DRV8838's inputs are PH
and EN, so the PWM is on EN: an inference, stated as one. A count limit `n` of a full scale `n_max`
is the duty `n / n_max`, and a voltage only at a named supply voltage. The Balboa library's timer
counts to 400 at 20 kHz and clamps commands to 300 by default ("Turning turbo mode on allows the
Balboa to move faster but could decrease the lifetime of the motors") [Pololu Balboa32U4 Arduino
library, version 1.1.2, `Balboa32U4Motors.cpp` (`ICR1 = 400`, `maxSpeed = 300`) and
`Balboa32U4Motors.h` (`allowTurbo`), retrieved 31.10.2026]: a duty of 0.75, which is 5.4 V at the
nominal 7.2 V, 6.3 V on a fresh charge and 4.05 V at the cut-off (§4). A voltage limit is written
with the duty and the supply voltage it assumes, and a count limit with its full scale.

**Judgement-only** — nothing reads the conversion of a count or duty into a voltage.

## 7. A current budget sums what can flow at once, against every rating on its path

For each supply path (cell, switch, driver, regulator), the budget sums the currents that can flow
together at the worst condition: every motor at the largest average voltage it can be commanded
(the command limit's duty times the top of the supply range, §4; the full top where no limit is
fixed), plus the logic and sensors. A motor that starts from rest draws its stall current, `V / R`;
a motor reversed while turning draws up to `(V + K_e·ω) / R`, more than its stall current
(*derived*, §5). The budget carries the reversal current at the largest speed the design states, or
a stated reason it cannot occur (for example a domain's statement that the motors never reverse at
speed). Each sum is compared with the rating of
each element it passes, a peak against a peak rating and a sustained draw against a continuous one,
and the rating's kind is named. The DRV8838 is rated "1.8-A Maximum Drive Current" (§1), a motor
peak current of 1.8 A (§6.3), with an overcurrent trip between 1.9 A and 3.5 A (§6.5) [TI DRV883x
datasheet, SLVSBA4F] (*normative*); "Under typical conditions, up to 2 A of current is available
from the VREG output" of the Balboa's 5 V regulator [Pololu, User's Guide, §3.6] (*typical value*,
not a continuous rating). A rating not found is stated as missing, never assumed.

**Enforced:** in part: gate check 4 holds each supply's declared output against its consumers'
declared draw, in watts, and each stall current against the current limit of the supply its edge
names (cross §4). The current sums themselves are judgement.

## 8. Mass and its distribution are summed from sourced parts

A mass that more than one domain uses (the whole robot's, a body's that sets a controller's plant,
a battery's) is the sum of its parts, each with its source, and its centre of mass and inertia,
where a domain needs them, are stated with how they were obtained: measured, computed from a
geometry, or a best estimate marked TBR (§2). Pololu gives the assembled Balboa with motors, 80 mm
wheels and bumper cage as 200 g, "This weight does not include batteries" [Pololu, item #3575,
specifications, retrieved 31.10.2026] (a maker's figure); a cell's mass is its maker's figure.

**Enforced:** in part: gate check 5 holds the mass of a node of kind `module` equal to the sum of the
masses of the nodes whose edges name it. A mass on another kind of node, or a part with no edge to
it, is not summed; whether every part is counted, and how a centre of mass was found, is judgement.

## 9. Every sizing result states its margin, against what, at what condition

A margin is "the allowances carried in budget, projected schedules, and technical performance
parameters (e.g., weight, power, or memory) to account for uncertainties and risks" [NASA SE
Handbook, Appendix B, glossary, "Margin"]; mass and power margins are among the measures a project
tracks [ibid., Appendix J, §7.4]. Each sizing result that sets or checks a limit states the
capability, the demand, the margin as their difference with its unit and as the ratio capability ÷
demand, and the condition both are taken at. A margin a source requires is quoted with its source;
where none is sourced, the margin computed is stated and none is invented. A negative margin is
recorded as a conflict (§3), never hidden by a changed condition.

**Judgement-only** — the gate's power, mass and thermal checks compare declared values with no
margin; nothing reads a stated margin.

## 10. Names the automated checks know, and edges to what each value bounds

The automated checks read a quantity by its name (cross §3) and a relation by the `constrains`
edges that join nodes (cross §4, §5). Sizing uses the checks' own names wherever a quantity is one
of them (for example `supply_voltage`, `rated_voltage`, `stall_current`, `stall_torque`,
`no_load_speed`, `current_limit`, `power_supply`, `power_draw`, `energy_capacity`, `mass`,
`gear_ratio`, `efficiency`, `duty_cycle`). An efficiency or a duty cycle is a fraction, written
in the unit `1` (0.75, never 75), under its name or a name ending in `_efficiency` or `_duty_cycle`,
and the checks hold it to 0 to 1 by definition (*derived*). A stall current and the current limit
that carries it may sit on one node, and are then held to each other; a stall current whose node
holds no limit is held to the supply its own edge names. Where a check compares the name with a bound, the value under it is the one the
check must judge: the largest for a demand (`stall_current` at the largest voltage the motor can be
commanded, §7; `power_draw`), and the rating for a capability (`current_limit`, `power_supply`,
`energy_capacity`, `max_discharge_power`). Every other known name (`supply_voltage`, `mass`,
`gear_ratio`, `rated_voltage`, `no_load_speed`, `stall_torque`) carries the brief's value or the
nominal one, which is what the domains read. The same quantity at another condition goes under a
name with a suffix of three letters or more, such as `_max`, `_min` or `_nominal` (shorter suffixes
on names the checks read are refused at write), which the checks record as unchecked. Each cross node
has a `constrains` edge to every node whose work depends on it, so that a change reaches them
(§11). A name the checks do not know is recorded unchecked, visibly, not wrong; a needed edge left
out leaves a change unpropagated.

Each interface node the plan gives sizing is the domains' contract, and sizing keeps a node of its
own joined to it: a node of domain `cross`, not an interface, that names the interface in its
`constrains` edges and holds every one of the interface's quantities under the same name. At the
first pass's change check the harness writes the interface from that node: each quantity takes its
value and unit, and its source names the node and the attempt; nothing else of the interface
changes. The gate and the reviewer judge the revised interface with the attempt, and the domains
read it once the pass merges. The node holds the values the domains are to read; a value at another
condition goes under a suffixed name, as above. Sizing never writes the interface node itself.

**Enforced:** gate checks 2, 4, 5 and 7 run on the names and edges the design declares; an unknown
name is recorded unchecked. The change check refuses a first-pass attempt in which no node is
joined to an interface sizing produces, a joined node lacks one of its names, two joined nodes
disagree on one, or a unit is not of the interface's kind; once another module has started, no
interface is revised again. Which value carries the name, and which edges a node needs, is
judgement.

## 11. The closing pass makes the cross values true to the domains' work

Sizing runs twice: first, before the domain modules, it writes the cross values they read; last,
after them, it reads every one of its nodes again with each node it constrains and each node that
constrains it, as they now stand. Where a domain's node changed after the first pass, each sizing
node joined to it is rewritten to agree (a current budget to a controller's recorded peak current,
a mass to a part a domain chose), citing the node it follows, or keeps its values and states why in
its `no_change_justified`, under the changed node's id (cross §5). A value a person chose on a
dispute is written exactly as chosen, value and unit. A rewrite of a value whose edges reach a
domain node leaves that node owing a follow-up that no later pass may give: the closing pass records
each one, with the node and the value, for integration and a person to see. The closing pass writes
no node of another role.

**Enforced:** in part: gate check 7 runs on the whole design before integration and finds a changed
quantity whose `constrains` edges name a node with neither a later follow-up nor its owner's reason;
it follows edges from the changed node only, so a domain change reaches a sizing node only through
the domain's own edge. When the disputing domain's left-in-place dispute is ruled again, the harness
holds the value sizing wrote to the one the person chose. Whether a rewrite agrees with the domain's
work is judgement.
