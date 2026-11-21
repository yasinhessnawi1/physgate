# Sizing — standards

> Researched and drafted from published sources by an agent, and approved by a person before use.
> Every number carries its
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
node. A quantity only one domain reads is that domain's; a quantity two domains read and
the plan left off sizing's nodes is recorded in sizing's work as unowned, with the domains that
read it, and not written by a domain.

**Enforced:** the hook layer and the change check refuse a write to a non-interface `cross` node by
any role but the one that owns the cross nodes, and a write by that role to any node of another
domain; no session creates an interface node. Whether a quantity is truly cross is judgement.

## 2. Every cross value says where it came from, at what condition

A cross value is one of three things, and its `source` says which: a value the brief states (quoted,
with the brief's criterion); a maker's figure (the document, its revision or date, and the condition
it holds at: a voltage, a temperature, a gear ratio); or a calculation from those (the formula and
every input, each with its own source). A value with none of these is a best estimate, marked as
requirement writing marks an unsettled value: "It is better to use a best estimate for a value and
mark it 'To Be Resolved' (TBR) with the rationale along with what should be done to eliminate the
TBR, who is responsible for its elimination, and by when" [NASA, *NASA Systems Engineering
Handbook*, NASA/SP-2016-6105 Rev 2, 2016, Appendix C, checklist] (*borrowed basis*: written for
requirement values, applied here to design values). A TBR names its rationale, what would resolve it
and who; "by when" is left out, since no pass sets a date. Each end of a TBR range has a basis (a
maker's figure, a comparable, a geometric bound or a measurement); a multiple of the nominal is not
one. A maker's figure is quoted at its own condition and not reused at another without the
conversion shown (§4, §5).

**Judgement-only** — the schema refuses a quantity without a source (cross §1); nothing reads
whether the source supports the number.

## 3. A value the brief fixes is written as the brief states it, and a conflict is recorded, never resolved by sizing

Where a criterion of the brief fixes a cross quantity (a part, a limit, a rating), sizing writes
that value, converted where needed with the conversion shown, and does not move it to make another
criterion easier to meet. The one exception is a value a person chose on a dispute, carried to the
pass by the harness's order: that value is written instead (§11). Where two requirements conflict,
sizing writes the value the brief
fixes and records the conflict in its module's record, cited from that value's `source`: both
statements, the calculation that shows the conflict, and the criterion it puts at risk.
Requirements are to be "stated consistently without contradicting themselves" [NASA SE Handbook,
Appendix C, checklist]; finding a contradiction is sizing's to record, and deciding it is a
person's. A conflict written only in a record reaches nobody: the record opens with each conflict,
and the review raises it to a person as a blocking defect (the rubric's verdict policy). Only a
requirement not met at the brief's own stated conditions is a conflict; one a person has decided
is not raised again, and the closing pass records only a conflict a domain's change made new. A
domain that disagrees with a cross value disputes it; the harness rules on the dispute by fixed
precedence (the physics checks, then sizing, then a person) and no session negotiates
[architecture specification, ARCH-040].

**Enforced:** in part. A domain's dispute is ruled by the harness's fixed precedence, after the
automated checks, and never reaches sizing's session; a repeat dispute of a quantity, or one on the
disputing subtask's last attempt, goes to a person. Whether sizing recorded a conflict it could see
is judgement.

## 4. A supply voltage is a range, and each demand is checked at the end of the range that is worst for it

A battery's voltage falls as it discharges: on the Balboa robot, "as your batteries run out, the
voltage supplied to the motor drivers (VSW) will decrease" [Pololu, *Pololu Balboa 32U4 User's
Guide*, §3.3, retrieved 31.10.2026]. A NiMH cell drops "from an open-circuit voltage of
approximately 1.4 volts to the 1.2 volt plateau", and a cut-off of "0.9 volts per battery" "may be
premature" at 1–4C [Energizer, *Nickel Metal Hydride (NiMH) Handbook and Application Manual*,
NiMH02.01, 2010, pp. 6 and 10] (*typical value*). Six cells span about 8.4 V to 5.4 V (*derived*),
the window the electrical standards use; for a pack loaded above 1C (motors at stall) the bottom so
taken is optimistic, and said so. So a supply quantity carries its nominal value and the range it
takes in use, each end with its source: the top is the charged open-circuit voltage, and the bottom
the cut-off less any drop under load the design knows. A demand that grows with voltage (a stall
current, the voltage across a part against its rating, a dissipation) is checked at the top; a
capability that falls with voltage (a no-load speed, a torque at speed, a headroom) at the bottom.
Where the specification pins a criterion to one design voltage, that criterion is checked at it, and
what the other ends give is stated beside it as information. A demand against a part's rating (a
current limit among them) is judged at the brief's voltage and also checked at the top: a rating
exceeded only at the top is an open point, no conflict, recorded under a suffixed name
(`stall_current_max`, §10) with figure, voltage, rating and source for the design to settle, carried
to integration, blocking nothing. Sizing cuts no command limit on its account; a person's decision
on it (a limit on average motor voltage, say) comes as an order (§11).

**Judgement-only** — the gate checks a value's size only where a bounds table gives its name or
kind a span (cross §3; none is loaded for a voltage), and a stall current against the current limit
on its own node or on the supply its edges name (§5, cross §4); nothing reads which end of a
voltage range a value was computed at.

## 5. A motor's operating points come from its published points, by a stated model

A brushed DC motor at steady state obeys `V = R·I + K_e·ω` and `T = K_t·I_T`, with `I_T` the
current that makes torque (*derived*, the motor's circuit). From a maker's two points at its rated
voltage `V_r`, the usual fit is `R = V_r / I_stall` and `K_e = (V_r − I_noload·R) / ω_noload`,
and either `K_t = T_stall / I_stall` or, treating the no-load current as friction as the `K_e` fit
does, `K_t = T_stall / (I_stall − I_noload)` (*model*: friction current constant with speed and
voltage; the stall figures extrapolated). The fit chosen is stated and used throughout. At another
voltage `V` the stall current is `V / R` and the no-load speed `(V − I_noload·R) / K_e`
(*derived* from the model). For an ideal motor `K_t = K_e` in SI units (power balance
`K_e·ω·I = T·ω`); constants fitted at a gearbox output differ, since the output torque carries
the gearbox's losses and the speed does not, so each is used only where fitted. A further gear stage
multiplies `K_e` by its ratio and `K_t` by its ratio times the stage's efficiency, taken as 1 where
no efficiency is sourced and stated as an assumption. A maker's stall figures may be extrapolated:
Pololu calls them "theoretical values; stalls could damage the motor or gearbox" and advises "25% or
less of the stall current" for brushed DC operation [Pololu, item #3073, retrieved 31.10.2026]
(*rule of thumb*; a sourced analysis may override it).

A motor's rotor inertia `J_m` (kg·m², at the motor shaft) is a motor constant, written beside `R`,
`K_t` and `K_e`. Where the maker gives none, it is a TBR estimate (§2): a nominal, a low and a high
value, each with its basis (published inertias of motors of comparable size, construction named; a
solid-cylinder bound `J = π·ρ·L·D⁴/32`, *derived*, from the rotor's dimensions inside the
magnets' bore, each assumption stated, with the bore sourced or the mass it implies leaving room
in the motor's published mass for the stator, magnets, case and gearbox, each with its basis; a
bound that leaves them no mass is not a basis), cross-checked by
`τ_m = R·J_m/(K_t·K_e)` (*derived*, no load), with the measurement that resolves
it named (a voltage step on a spare motor, encoder logged). Through a gearing `N` it adds
`N²·J_m` on the wheel's speed relative to the motor's housing (*derived*); where the housing moves
(a balancing robot's body), that is the wheel's speed relative to the body.

**Enforced:** in part: the gate holds a `stall_current` against a `current_limit` on its own node,
and against the `current_limit` of each supply its own `constrains` edges name (gate check 4); a
limit further along the path is not read, and a `stall_current` that no limit bounds, on its node or
on a node its edges name, is recorded unchecked, never passed. The fit and the conversions are
judgement.

## 6. A command limit becomes a voltage only at a stated supply voltage

A pulse-width command is a fraction of the supply: a driver that brakes during the off time (both
low-side switches on: the DRV8838's "Brake" row with `EN = 0` [Texas Instruments, *DRV883x
Low-Voltage H-Bridge Driver*, SLVSBA4F, revised April 2021, §7.3.1, Table 7-2]) applies on average
`D·V_supply` for duty `D` while its current is continuous (*derived*). A count limit `n` of a full
scale `n_max` is the duty `n / n_max`, and a voltage only at a named supply voltage. The Balboa
library's timer counts to 400 at 20 kHz and clamps commands to 300 by default [Pololu Balboa32U4
Arduino library, version 1.1.2, `Balboa32U4Motors.cpp`, `.h` (`ICR1 = 400`, `maxSpeed = 300`,
`allowTurbo`), retrieved 31.10.2026]: a duty of 0.75, which is 5.4 V at the nominal 7.2 V (§4). A
voltage limit is written with the duty and the supply voltage it assumes, and a count limit with its
full scale. §12 computes the headroom it leaves.

**Judgement-only** — nothing reads the conversion of a count or duty into a voltage.

## 7. A current budget sums what can flow at once, against every rating on its path

For each supply path (cell, switch, driver, regulator), the budget sums the currents that can flow
together at the worst condition: every motor at the largest average voltage it can be commanded (the
command limit's duty times the voltage the brief pins, else the top of the supply range, §4; the
full top where no limit is fixed), plus the logic and sensors. A motor that starts from rest draws
its stall current, `V / R`; a motor reversed while turning draws up to `(V + K_e·ω) / R`, more than
its stall current (*derived*, §5). The budget carries the reversal current at the largest speed the
design states, or a stated reason it cannot occur. Each sum is compared with the rating of each
element it passes, a peak against a peak rating and a sustained draw against a continuous one, and
the rating's kind is named. The DRV8838 is rated "1.8-A Maximum Drive Current" (§1), a motor peak
current of 1.8 A (§6.3), with an overcurrent trip between 1.9 A and 3.5 A (§6.5) [TI DRV883x
datasheet, SLVSBA4F] (*normative*). A stall current over the 1.9 A trip minimum at the top of the
range only is §4's open point. A rating not found is stated as missing, never assumed.

**Enforced:** in part: gate check 4 holds each supply's declared output against its consumers'
declared draw, in watts, and each stall current against the current limit of the supply its edge
names (cross §4). The current sums themselves are judgement.

## 8. Mass and its distribution are summed from sourced parts

A mass that more than one domain uses (the whole robot's, a body's that sets a controller's plant,
a battery's) is the sum of its parts, each with its source, and its centre of mass and inertia,
where a domain needs them, are stated with how they were obtained: measured, computed from a
geometry, or a best estimate marked TBR (§2).

**Enforced:** in part: gate check 5 holds the mass of a node of kind `module` equal to the sum of the
masses of the nodes whose edges name it. A mass on another kind of node, or a part with no edge to
it, is not summed; whether every part is counted, and how a centre of mass was found, is judgement.

## 9. Every sizing result states its margin, against what, at what condition

A margin is "the allowances carried in budget ... and technical performance parameters ... to
account for uncertainties and risks" [NASA SE Handbook, Appendix B, glossary, "Margin"]. Each sizing
result that sets or checks a limit states the capability, the demand, the margin as their difference
with its unit and as the ratio capability ÷ demand, and the condition both are taken at. A margin a
source requires is quoted with its source; where none is sourced, the margin computed is stated and
none is invented. A negative margin at the brief's conditions is recorded as a conflict (§3), never
hidden by a changed condition.

**Judgement-only** — the gate's power, mass and thermal checks compare declared values with no
margin; nothing reads a stated margin.

## 10. Names the automated checks know, and edges to what each value bounds

The automated checks read a quantity by its name (cross §3) and a relation by the `constrains` edges
that join nodes (cross §4, §5). Sizing uses the checks' own names wherever a quantity is one of them
(for example `supply_voltage`, `rated_voltage`, `stall_current`, `stall_torque`, `no_load_speed`,
`current_limit`, `power_supply`, `power_draw`, `energy_capacity`, `mass`, `gear_ratio`,
`efficiency`, `duty_cycle`). An efficiency or a duty cycle is a fraction, written in the unit `1`
(0.75, never 75), under its name or a name ending in `_efficiency` or `_duty_cycle`, and the checks
hold it to 0 to 1 by definition (*derived*). Where a check compares the name with a bound, the value
under it is the one the check must judge: a demand at the brief's own condition (`stall_current` at
the voltage the brief pins, else at the top of the supply range, §4; `power_draw`), and the rating
for a capability (`current_limit`, `power_supply`, `energy_capacity`, `max_discharge_power`). Every
other known name carries the brief's value or the nominal one, which is what the domains read. The
same quantity at another condition goes under a name with a suffix of three letters or more, such as
`_max`, `_min` or `_nominal` (shorter suffixes on names the checks read are refused at write), which
the checks record as unchecked: the stall current at the top of the pack, beside the one judged, is
`stall_current_max` (§4). Each cross node has a `constrains` edge to every node whose work depends
on it, so that a change reaches them (§11). A name the checks do not know is recorded unchecked; a
needed edge left out leaves a change unpropagated.

Each interface node the plan gives sizing is the domains' contract, and sizing keeps a node of its
own joined to it: a node of domain `cross`, not an interface, that names the interface in its
`constrains` edges and holds every one of the interface's quantities under the same name. At the
first pass's change check the harness writes the interface from that node (value and unit; the
source names the node and the attempt); the reviewer judges it with the attempt. Sizing never writes the interface node itself.

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
node joined to it is rewritten to agree (a current budget to a controller's recorded peak current, a
mass to a part a domain chose), citing the node it follows, or keeps its values and states why in
its `no_change_justified`, under the changed node's id (cross §5). A value a person chose on a
dispute is written exactly as chosen, value and unit. A domain's record may ask sizing for a value
it owns, with the value needed and the bound sizing stated (§12); the closing pass meets each
request by a value inside the bound that meets it, citing the request (the readers follow, below).
Requests for different values of one quantity get one value that meets all of them, where one lies
inside the bound. Where none does, or sizing keeps its value, the criterion stays unmet at the
brief's own conditions: sizing records a conflict naming the request (§3), so it reaches a person,
and says why in `no_change_justified` under the request's id. A request is no dispute (§3). A
rewrite of a value whose edges reach a domain node leaves that node owing a follow-up that no later
pass may give: the closing pass records each one, with the node and the value, for integration and a
person to see.

**Enforced:** in part: gate check 7 runs on the whole design before integration and finds a changed
quantity whose `constrains` edges name a node with neither a later follow-up nor its owner's reason;
it follows edges from the changed node only, so a domain change reaches a sizing node only through
the domain's own edge. When the disputing domain's left-in-place dispute is ruled again, the harness
holds the value sizing wrote to the one the person chose. Whether a rewrite agrees with the domain's
work is judgement.

## 12. A command limit leaves a plant that falls by itself the headroom to recover from a disturbance

Applies where a criterion of sizing's specification, or of a domain module's specification that
reads the command limit, asks a plant that falls by itself (a balancing robot) to recover from a
disturbance (a push). Sizing computes the largest disturbance **any** controller could recover with
the limit's headroom, while it can still change the limit.

**The bound** (*derived*).
- To hold the criterion's speed the motors already need `V_hold = K_e·ω + I_noload·R`, `K_e` and
  `ω` at the same shaft (§5). The headroom is `ΔV = D·V_supply − V_hold` (§6).
- Linearised there, `x' = A·x + B·v`, with `v` the voltage above `V_hold` and `v ≤ ΔV` on the side
  that rights the plant (the other side has `D·V_supply + V_hold`). `A` has one real unstable
  eigenvalue `λ`; with `w` its left eigenvector (`wᵀA = λ·wᵀ`), `z = wᵀx` obeys exactly
  `z' = λ·z + (wᵀB)·v`. Once `|z| ≥ |wᵀB|·ΔV / λ`, no admissible `v` brings `z` back: the
  plant falls under every controller.
- A disturbance `d` moves the state by `d·e` and `z` by `d·(wᵀe)`, so the largest any controller
  recovers is `d_max = |wᵀB|·ΔV / (λ·|wᵀe|)`. A loop that first acts a dead time `T` after the
  disturbance leaves `z` to grow unopposed for `T`, which multiplies `d_max` by `e^(−λT)`.

**The inputs**, each fixed, since a free one could pass a failing limit.
- Inputs sizing writes are used as written. The others (centre-of-mass height, pitch, wheel and
  rotor inertia) carry how each was found, or are TBR with a range (§2, §8).
- The rotor inertia is §5's estimate; its low and high values are the range the spread below uses.
- Where the brief states the falling behaviour with a tolerance, the centre-of-mass height is
  solved so that the motors-off pole (terminals braked, the driver's state with its enable low: the
  same `A`) is that value. Of two such heights, the one inside the body's stated geometry is taken;
  if both are, the one giving the smaller `d_max`.
- A push is a horizontal impulse at the body's centre of mass, scaled to raise the tilt rate by
  `d`; `e` is the state change it gives per unit `d`, wheel rate included, unless the criterion's
  specification names another point of application (*model*).
- `T` is one sample period plus the computation and lateness bounds plus the sensor's age, from the
  nodes the criterion's specification names; 0 only where none states them, and said so.
- The condition is the criterion's own: the supply voltage it or the brief pins (§4), else the
  nominal; its speed at the lowest admissible value; the disturbance at the top of its band. The
  headroom at the supply range's ends is stated beside it.

**The spread.** `d_max` is computed with the rotor inertia across §5's range (×0.5 to ×2 of a
maker's single figure), each with the fall time across its tolerance, ends and points between:
`d_max` need not be monotonic in either. It is also stated, not judged, at `K_e`, `I_noload` and
`R`'s sourced tolerances: `ΔV` is a small difference of two large voltages.

**The threshold.** `d_max·e^(−λT) ÷ d`, with the smallest `d_max` of the spread, is at least 1
(*derived*: below it no controller recovers the disturbance in the model, and the spread is the
model's uncertainty). No margin above 1 is required: none is sourced (§9). The bound is necessary
only: a ratio of 1 or more does not show that a given controller recovers.

**Recorded**, from a script that reads the node's values and prints them: `V_hold`, `D·V_supply`,
`ΔV`, `λ`, `w` (tilt-rate component 1), `B`, `e`, `wᵀB`, `wᵀe`, `|wᵀA − λ·wᵀ|`, `T`, `d_max` at
the nominal and the deciding point, `d`, both ratios, the condition (§9) and the largest limit the brief and the ratings allow, the
bound a request for a larger limit is read against (§11).

**Below 1.** If a larger limit the brief allows (stall current within its rating at the brief's
judging voltage, duty below 1) reaches 1, sizing writes a value within the bound that does and
states the trade: a larger limit gives headroom and costs current, heat and motor life (§6), a
smaller the reverse. The smallest limit that reaches 1 on sizing's own estimates is a floor, not the
choice, while the consumers' ranges are unseen; the closing pass moves it within the bound as a
request asks (§11). A rating then exceeded only at the top is §4's open point. If none reaches 1, it
records the conflict with the ratio at the largest (§3).

**Judgement-only** — nothing reads the bound; the reviewer redoes it by reading.
