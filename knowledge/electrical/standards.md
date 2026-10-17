# Electrical — standards

> Researched and drafted from published sources (datasheets, manufacturer application notes, and two
> public space derating standards) by an agent, and approved by a person before use. Every number
> carries its source and its kind: *derived* (definition, theorem or arithmetic; never relaxed),
> *normative* (a rule of the cited document), or *rule of thumb / typical value* (a published practice
> a sourced analysis may override). Every *derived* value here is this draft's derivation: its own
> arithmetic on the cited values. Read `knowledge/cross/standards.md` first; this file does not
> repeat it.

## 1. A rating is used together with its condition, and an absolute maximum rating is not an operating limit

Record every rating as value, unit and source (cross-domain standards §1) and also the condition it
was stated under: temperature, supply voltage, duty cycle, board or mounting. Design to the
recommended operating conditions. Absolute maximum ratings are "stress ratings only, and do not imply
functional operation of the device at these or any other conditions beyond those indicated under
Recommended Operating Conditions" [Texas Instruments, *DRV883x Low-Voltage H-Bridge Driver*,
SLVSBA4F, April 2021, §6.1 note (1), p. 6]. A motor driver's continuous current rating is
"calculated as the current that the device can provide at 25°C ambient temperature, when mounted on a
standard JEDEC-specified PCB" and "is not attained at higher ambient temperatures" or on poorer boards
[TI, *Understanding Motor Driver Current Ratings*, SLVA505A, July 2024, §3.1, p. 9]. The rating of a
board is not the rating of its chip: for example, the Balboa 32U4 user's guide limits the board input
to 10.8 V and says its 5 V output current "depends on input voltage and ambient conditions", up to
2 A "under typical conditions", while the regulator chip alone accepts 36 V and is rated 3 A
continuous [Pololu, *Balboa 32U4 Balancing Robot User's Guide*, 2001–2022, §3.6, p. 22; MPS,
*MP4423H*, Rev. 1.0, 2014, p. 1]. The driver datasheet gives 11 V (recommended) and 12 V (absolute
maximum) for the motor supply [SLVSBA4F, §6.1, §6.3, p. 6]. Where two sources differ, this library
chooses the stricter and records both.

**Judgement-only** — the schema refuses a quantity without a source (cross-domain standards §1), but
no check reads whether the cited condition matches the application or whether the number cited is an
absolute maximum rather than an operating limit.

## 2. The power budget lists every load at its worst case and closes against continuous and peak ratings separately

Enumerate every load on every rail with its source. For each, record the steady value and the worst
case that matters: motor stall and start-up, inrush, peak versus average. A driver's peak limit matters
"when considering the start-up current of a stalled DC motor" [SLVA505A, §1.2, p. 2]. Close the budget
twice: average draw against each supply element's *continuous* rating, and the coincident worst case
against its *peak* or current-limit rating. A rail can deliver no more than the lowest rating in its
series path (switch, multiplexer, regulator, connector, trace, fuse); *derived*. For example, the
Balboa's logic rail passes the regulator (2 A typical) and a power multiplexer whose "current limit
... is set to about 1.9 A nominally" [Balboa guide, §3.6, pp. 22–23], so the path limit is the lower.
A switching regulator's load enters the battery budget as input power, not output current; this
library holds no efficiency figure, so each design sources its own.

**Enforced:** gate checks 4 and 5 (`check_power.py`, `check_conservation.py`) hold each declared draw
to its supply's declared rating at module and system scope (cross-domain standards §4). They check
what is declared against one declared rating per supply: not the current through each series
element, not continuous and peak separately, and not whether the load list is complete.

## 3. Battery current stays within the cell's sourced maximum discharge rate, and the cell class is named

Name the chemistry and the cell; a C-rate limit belongs to a cell class and needs that maker's source.
For Energizer NiMH cells the handbook gives "the current maximum discharge rate of 4C", with
"significant reductions in voltage delivery" above 1C [Energizer, *Nickel Metal Hydride (NiMH)
Handbook and Application Manual*, NiMH02.01, 2010, p. 8] (*normative* for that maker's cells). For a
2300 mAh AA rated at 0.2C [Energizer, *NH15-2300 datasheet*, form NH15-2300GL1220], 4C is 9.2 A
(*derived*). The NH15-2300 is specified to discharge at 0 to 50 °C and charge at 0 to 40 °C. This
library holds no sourced maximum discharge rate for alkaline AA cells: a design on alkaline cells must
source one or show the load is within the published discharge curves (the E91 sheet plots capacity
at 25–500 mA [Energizer, *E91 datasheet*, form E91NA1018]). Cells in series all carry the full pack
current. A NiMH compartment needs ventilation and isolation from sparking switches, which "are
required to eliminate concerns regarding possible hydrogen ignition" [NiMH handbook, p. 14].

**Judgement-only** — no check compares pack current with a cell's C-rate; the gate holds power to the
declared rating, not current to a chemistry limit.

## 4. Every downstream rating holds over the battery's whole voltage window, under load

The window runs from the highest open-circuit voltage (fresh or fully charged) to the lowest
terminal voltage under the heaviest load at the cut-off. NiMH falls from "an open-circuit voltage of
approximately 1.4 volts" to a 1.2 V plateau; internal resistance is "typically less than 50
milliohms" fresh and rises with age [NiMH handbook, p. 6]; the NH15-2300 lists 30 mΩ charged and
40 mΩ half discharged, ±20%. Alkaline E91: 150 to 300 mΩ fresh. Sag is pack current × the sum of
series cell resistances (*derived*, Ohm's law). Discharge cut-off for NiMH: 0.9 V per cell below 1C,
75% of the mid-point voltage at 1–4C, chosen "only by considerations of preventing damage to the
battery" [NiMH handbook, p. 10] (*rule of thumb*); reversal "may result in battery venting as well as
irreversible damage" (p. 9). The same passage names "multiple-cell applications" as a second
complication and gives no rule for it, so cells × cut-off is a pack figure that does not show the
weakest cell stays out of reversal; this library holds no sourced rule for protecting it. Check against the top of the window every part on the
battery rail (driver, regulator input, capacitors, dividers), and against the bottom every
regulator's input minimum and every undervoltage threshold (§9). Example: six NiMH span about 8.4 V
open circuit to 5.4 V at 0.9 V per cell (*derived*); the Balboa guide notes motors slow as VSW falls
[§3.3, p. 17].

**Judgement-only** — the gate checks declared magnitudes and supply balance, not that each part is
rated at both ends of a voltage range.

## 5. A motor's stall current is checked against the driver's continuous, peak and protection limits

Take the stall current from the motor maker, at the maximum voltage of §4, and state whether it is
measured or extrapolated. Back-EMF is proportional to speed [Microchip, *AN905 Brushed DC Motor
Fundamentals*, DS00905B, 2010, p. 6], so at stall only resistance limits current, and the stall
current scales with applied voltage (*derived*). Compare it with three driver numbers: the continuous
(thermal) rating, the peak rating, and the minimum overcurrent trip level. Exceeding the trip "does
not damage the device, but can cause OCP to activate and disable the output" [SLVA505A, §3.1, p. 9].
For example, the DRV8838 is rated 1.8 A peak and trips at 1.9 A minimum, with retry after 1 ms
[SLVSBA4F, §6.3, §6.5, pp. 6–8]; a 6 V motor with 1.5 A extrapolated stall [Pololu, *50:1 Micro
Metal Gearmotor HPCB 6V with Extended Motor Shaft*, product page 3073, read 16.10.2026] reaches
about 2.1 A at 8.4 V (*derived*, 8.4 V / 4 Ω, ignoring series resistance), above both. A stall that
trips protection is a control-relevant event: declare it to the control and firmware roles. A
sustained stall is also a motor limit: "stalls could damage the motor or gearbox", with thermal
damage "potentially on the order of seconds" (same page); its guidance of "25% or less of the stall
current" for operation is a *rule of thumb*.

**Judgement-only** — no check compares a motor's stall current with a driver's limits.

## 6. Junction temperature is estimated from dissipated power with a thermal metric that fits the board, and the metric is named

Dissipation in an H-bridge is dominated by on-resistance, P = rDS(on) × I_rms² [SLVSBA4F, §9.3,
eq. 1, p. 20], and "the value of rDS(on) increases with temperature". θJA (RθJA) is measured on a
JEDEC test board; using TJ = TA + RθJA × P for a real board "is a misapplication", because "70%–95% of
the power generated by the chip is dissipated from the test board" and test-board construction alone
moves RθJA by up to 50% [TI, *Semiconductor and IC Package Thermal Metrics*, SPRA953D, March 2024,
§1.1–1.2, pp. 2–3]. Use RθJA only to compare packages, or an RθJA(effective) whose system conditions
are stated (§1.8, p. 5), or a measured board or case temperature with ΨJB or ΨJT (§3, §5,
eqs. 8–9); ΨJT "should not be used when application of a heat sink is intended" (§3.2, p. 10). Name
which. Keep the estimate below the thermal shutdown minimum (DRV8838: 150 °C) with the margin
stated. Example: 1.8 A through 0.33 Ω (the 25 °C maximum; hotter is worse) is 1.07 W; with
RθJA = 60.9 °C/W that is about 65 °C of rise on the JEDEC board, so 150 °C at 85 °C ambient
(*derived*): the driver cannot hold its peak rating continuously there.

**Enforced:** the thermal-margin check of cross-domain standards §6 (`check_thermal.py`) holds a
component with a declared thermal resistance to a margin. It cannot tell whether the declared
resistance is a test-board θJA misapplied to this board; that is this rule.

## 7. Each part's stress is recorded as a ratio to its rating, and the derating basis is stated

For every part in the power path record operating/rated for voltage, current, power and temperature
at the worst case, each side as value, unit and source (cross-domain standards §1). This library
adopts the manufacturer's recommended operating conditions as the limit (rule 1) and **does not
adopt** a space derating factor as a limit; a design that wants margin names the practice it follows.
Both public derating standards were written for spacecraft: ECSS-Q-ST-30-11C "applies to all
components, selected for space applications" procured to approved space specifications [ECSS, *Space
product assurance – Derating – EEE components*, ECSS-Q-ST-30-11C Rev.2, 23 June 2021, §5.3.1, p. 18];
EEE-INST-002 sets criteria "for use on NASA GSFC space flight projects" [NASA GSFC, *EEE-INST-002*,
NASA/TP-2003-212242, May 2003 with Addendum 1 2008, Section 1, §1.0, p. 1]. Their values are
*normative for that class*, and here only reference points: ECSS FETs 80% VDS, 75% drain current,
65% power; diodes 75% forward current and reverse voltage; junction 110 °C or TJmax − 40 °C,
whichever is lower (Tables 6-13, 6-36); chip resistors 80% voltage, 50% power to 85 °C case falling to
0% at 125 °C (Table 6-30); NASA ceramic capacitors 0.60 of rated voltage on DC plus peak ripple
(Section C1, Table 4, p. 23); the ECSS capacitor tables were not readable and are not quoted. A transient with
no rating of its own stays "below the steady-state specified maximum ratings" [ECSS, §5.4.2b, p. 21]
(*normative*, adopted); this library reads that as the recommended operating maximum (rule 1).

**Judgement-only** — no check computes load ratios or knows a part's rating table.

## 8. Conductors and contacts are sized for the current with a stated temperature rise and a stated basis

PCB traces: IPC-2221's chart fit, I = k × ΔT^0.44 × A^0.725 (I in A, ΔT in °C, A in mil²; k = 0.048
external, 0.024 internal), is a *rule of thumb* valid for 0–35 A, 10–100 °C rise and 0.5–3 oz copper,
"extrapolated and more error-prone" outside; read in a secondary reproduction (G. Hunter, *How To
Calculate Maximum Track Current*, mbedded.ninja, 2016), the standard itself not read. Its internal
factor came from halving the external chart; IPC-2152 (2009) found internal traces cool "almost as
well or better" and external currents about 25% lower than IPC-2221. The authors find that "with one
exception the IPC curves seem to be 'worst case' scenarios" and that trace temperature is too complex
"to represent with equations or graphs" [D. G. Brooks with J. Adam, *Trace Currents and Temperatures
Revisited*, UltraCAD, April 2015, abstract, §1, §5; IPC-2152 not read]. State the basis and ΔT used.
Wires: use the wire maker's rating with its conditions; the NASA and ECSS wire tables assume vacuum
(EEE-INST-002 W1 Table 4A note 1, p. 30; ECSS §6.32.4b, p. 86) and are not in-air ampacities.
Connectors: rate each contact from the connector maker's contact rating and its conditions (rule 1).
Space practice, not adopted here: EEE-INST-002 ties "Contact Current" to its vacuum wire table for
the wire size used (C2 Table 5, p. 54); ECSS limits contact current to 50% and temperature to 30 °C
below the rated maximum [ECSS Table 6-10, p. 38], NASA to 25 °C below (same NASA table).

**Judgement-only** — no check sizes a trace, wire or contact against its current.

## 9. Supply faults are designed for: overcurrent, reverse polarity and falling voltage each have a stated behaviour

Overcurrent: a protective device's rating sits above the highest normal current and opens before the
weakest conductor or contact in its path exceeds its rating (*derived* from its purpose). Littelfuse
recommends loading a fuse to "no more than 75 % of the nominal current rating" at 25 °C, rerated for
ambient, and a pulse I²t of no more than 20% of the fuse's melting I²t [Littelfuse, *Fuseology Design
Guide*, 2022, pp. 3–4] (*rules of thumb*). A shorted NiMH pack can deliver currents "sufficient to
cause burns or ignition" [NiMH handbook, p. 14]. Reverse polarity: a series diode costs its forward
drop; a FET costs rDS(on) × I_load [TI, *Reverse Current/Battery Protection Circuits*, SLVA139, 2003,
pp. 1–2]. Falling voltage: list in order what stops as the supply falls (regulator input minimum or
UVLO, power-good, multiplexer switchover, MCU brown-out, driver UVLO) and show the order is safe. The
DRV8838 has no VM undervoltage lockout [SLVSBA4F, §7.3.4, p. 16]. An MCU's brown-out trip must lie
above the lowest supply its clock frequency is rated for (*derived*): the ATmega32U4 needs 4.5 V at
16 MHz [Atmel, *ATmega16U4/32U4 datasheet*, 7766J, 04/2016, Fig. 29-2, p. 386], but its highest
brown-out level trips at 4.0 to 4.5 V (Table 8-1, p. 53), so at 16 MHz no setting guarantees it; the
same figure rates 8 MHz down to 2.7 V. Where no setting meets it, record that and the chosen remedy
for review; this library holds no sourced external supervisor.

**Judgement-only** — no check models protection devices, polarity or a falling supply.

## 10. Logic levels are checked at both supplies: VOH(min) ≥ VIH(min), VOL(max) ≤ VIL(max), and the high level within the receiver's maximum input

Use the guaranteed values (minimum VOH at the actual output current, maximum VOL, and the receiver's
guaranteed thresholds), each at its own part's supply voltage and at the temperature the table states
(*derived* from the threshold definitions). Then check the driving high level against the receiver's
maximum input level from its electrical characteristics, not its absolute maximum: the ATmega32U4's
VIH maximum is VCC + 0.5 V [ATmega32U4 datasheet, Table 29-1, p. 383]. Example: an ATmega32U4 at 5 V
guarantees VOH ≥ 4.2 V at 10 mA and VOL ≤ 0.7 V (same table); a DRV8838 at VCC = 5 V reads high above
0.5 × VCC = 2.5 V and low below 0.25 × VCC = 1.25 V, values given at TA = 25 °C, with inputs up to
5.5 V [SLVSBA4F, §6.3, §6.5, pp. 6, 8]; both margins hold. A 5 V and a 3.3 V part need a level shifter
where either check fails, as the Balboa uses for its I²C bus [Balboa guide, §3.5, p. 20].

**Judgement-only** — no check reads logic thresholds.

## 11. Motor supply transients have a path: bulk capacitance is rated above the highest supply voltage, and PWM is within the driver's limit

Bypass the driver's supply pins with the manufacturer's ceramic capacitors, rated for that supply
(DRV8838: 0.1 µF on VM and on VCC) [SLVSBA4F, §9.1, p. 20]. Bulk capacitance absorbs "excessive
current demands or dumps from the motor"; its "voltage rating ... should be higher than the operating
voltage, to provide margin for cases when the motor transfers energy to the supply", and its size
needs "system-level testing" [SLVSBA4F, §8.1, p. 19] (*normative*, adopted). Keep the PWM frequency
inside the driver's recommended range (DRV8838: 0 to 250 kHz, §6.3); 4 to 20 kHz is a *rule of
thumb* that attenuates audible noise at small switching loss [AN905, p. 5].

**Judgement-only** — no check models transients, capacitor ratings or PWM frequency.

## 12. The schematic passes an electrical rules check with every exclusion justified, and every part carries a part number, datasheet and ratings

Run the schematic tool's electrical rules check (ERC), "for automatic detection of incorrect and
missing connections", and record its report. In KiCad a power net needs a power-output pin or a
PWR_FLAG, or ERC reports "Input Power pin not driven by any Output Power pins"; a pin left open on
purpose carries a no-connect flag [KiCad, *Schematic Editor* manual, version 9.0, "Electrical
Connections" and "Electrical rules checking"]. ERC "is imperfect and cannot detect all errors", and
"if symbols are designed incorrectly, ERC will not report accurate information" (same), so a clean
report does not replace this file's checks, and symbol pin types are checked against the datasheet.
By this library's choice, the check passes only with no error or warning left unexcluded, each
exclusion is listed with its reason, and every part gets a manufacturer part number, its datasheet
with revision, and the ratings used (rule 1). The harness's separate sourcing step validates the
bill of materials against real availability (ARCH-051).

**Judgement-only** — the gate runs no ERC and reads no part record; the sourcing step checks
availability, not whether the ratings recorded are the right ones.
