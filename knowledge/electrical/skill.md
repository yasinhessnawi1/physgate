# Electrical — skill

> Procedures and antipatterns for electrical tasks, researched and drafted from published sources by
> an agent and approved by a person before use. Rule numbers (§N) refer to
> `knowledge/electrical/standards.md`; read `knowledge/cross/standards.md` first. Numbers marked
> *derived* are this draft's arithmetic on the cited values; the reference robot's parts appear only
> as examples.

## Procedure: building the power budget

1. Draw the power tree: each source, every series element (switch, reverse-polarity device,
   multiplexer, regulator, fuse, connector, trace) and every load on each rail.
2. Fill one row per load. Every number is value, unit and source (cross-domain standards §1):

   | Load | Rail | Typical current | Worst-case current | Worst-case condition | Duration | Source |
   |---|---|---|---|---|---|---|
   | e.g. motor, left | VSW | ... A | stall at max V (§5) | start-up or stall | ... s | maker, measured or extrapolated |

3. Fill one row per supply or series element: continuous rating, peak or current-limit rating, the
   condition of each (§1), and the source.
4. Convert each regulator's output load to input power at the lowest input voltage, with a sourced
   efficiency; with no source, record the conversion as unverified, not as 100%.
5. Sum averages against continuous ratings; sum coincident worst cases against peak ratings. The
   rail limit is the lowest element rating in its path (§2).
6. Record the margin of each comparison, and declare each supply and draw as quantities, which gate
   checks 4 and 5 read (cross-domain standards §4).

## Procedure: the battery voltage window and sag

1. Name the cell and maker; take nominal voltage, rated capacity with its rate, internal resistance
   with its state of charge, maximum discharge rate and cut-off from that maker (§3, §4).
2. V_max = cells × highest open-circuit voltage. V_min = cells × cut-off − (I_peak − I_cut) × R_pack,
   where I_cut is the load the cut-off is taken at (the cut-off is a loaded voltage) and R_pack the
   sum of cell resistances at their worst state, tolerance included (*derived*, Ohm's law).
3. Check the pack current against the C-rate limit, every part on the battery rail at V_max, and
   every regulator and threshold at V_min.
4. State that cells × cut-off does not protect the weakest cell of a series pack (§4).

Example (*derived*): six NiMH at 30 mΩ (charged) to 48 mΩ (40 mΩ half discharged, +20%) give
R_pack = 0.18 to 0.29 Ω; a 4.2 A step from two stalled motors sags the pack 0.76 to 1.2 V. The sheet
gives no end-of-discharge or aged value, and resistance "will rise sharply" near end of life [NiMH
handbook, p. 6], so 48 mΩ is the worst published value, not the worst state. Six fresh
alkaline cells at 150 to 300 mΩ give 0.9 to 1.8 Ω; a 2 A step costs 1.8 to 3.6 V [cell values:
Energizer NH15-2300 and E91 datasheets].

## Procedure: checking a motor against its driver

1. Get the motor's stall current at its rated voltage; note if extrapolated. Estimate winding
   resistance R = V_rated / I_stall and the bound I_stall,max = V_max / R (*derived*; series driver,
   wiring and battery resistance lower it, and may be counted only with their own sources).
2. Compare I_stall,max with the driver's continuous rating, peak rating and minimum OCP trip (§5).
   If it exceeds the trip, state what the driver does (DRV8838: outputs off, retry after 1 ms) and
   tell the control role the actuator saturates there. Limit stall duration for the motor's sake.
3. Compare the expected continuous (RMS) current with the driver's thermal limit (next procedure).
4. Check the motor supply against the driver's maximum at V_max (§4) and set PWM within its range
   (§11).

Example (*derived*): 1.5 A at 6 V gives 4 Ω; at 8.4 V the bound is 2.1 A, above the DRV8838's 1.8 A
peak rating and 1.9 A minimum trip.

## Procedure: estimating driver junction temperature

1. P = rDS(on),max × I_rms² for an H-bridge (high plus low side); use rDS(on) at the expected
   temperature, not 25 °C, where the datasheet gives it (§6).
2. Choose the thermal metric and say why: RθJA only as a JEDEC-board comparison; RθJA(effective)
   with its board stated; or a measured board (ΨJB) or case (ΨJT, no heat sink) temperature.
3. TJ = T_reference + metric × P. Compare with the thermal-shutdown minimum and record the margin.
4. Declare the thermal resistance and dissipation as quantities, which the thermal-margin check
   reads (cross-domain standards §6), and record which metric the number is.

## Procedure: the falling-supply sequence

1. List every undervoltage behaviour with its threshold and source: regulator input minimum (from
   its recommended operating conditions), regulator UVLO, power-good, multiplexer switchover, MCU
   brown-out, driver UVLO.
2. Sort them by voltage and walk the supply down from V_max to zero, with and without each optional
   source (USB, bench supply). At each threshold write what stops and whether the outputs are left
   in a safe state (§9).
3. Check the MCU's brown-out trip against the supply its clock frequency needs (§9).

Example (*derived*): the MP4423H's recommended conditions allow VOUT up to 0.9 × VIN [MP4423H,
p. 3], so 5 V out needs 5.56 V in: six cells at 0.93 V each. The 5 V rail leaves its recommended
range before the 0.9 V cut-off, even before sag. The Balboa's multiplexer, if the regulator output
"falls below about 4.5 V", selects "the higher of the two sources", typically USB if connected
[Balboa guide, p. 23]; with no USB there is no switchover. The DRV8838's VM has no UVLO; its VCC
lockout is at 1.7 V [SLVSBA4F, Table 7-4, p. 16].

## Procedure: checking a logic interface

1. For each signal between parts on different supplies, take from each datasheet at its own supply
   voltage: driver VOH(min) and VOL(max) at the actual load current, receiver VIH(min), VIL(max) and
   maximum input level from the electrical characteristics, with the table's temperature.
2. Require VOH(min) ≥ VIH(min), VOL(max) ≤ VIL(max), driver high level ≤ receiver maximum input, with
   the margins recorded (§10). Repeat for both directions of a bidirectional line.
3. Where a check fails, add a level shifter whose own ranges are sourced (for example, the Balboa's
   general-purpose shifter takes 1.8 to 5.5 V in and 3 to 5.5 V on VCC [Balboa guide, §3.8, p. 30]).
4. Note datasheet caveats: the ATmega32U4's DC limits are marked as preliminary design targets
   [Table 29-1, note 5, p. 385].

## Procedure: choosing overcurrent protection

1. Find the highest normal current through the protected path, including start-up and stall
   pulses, and the lowest current rating among the conductors and contacts the device protects.
2. Pick a rating at or above normal current / 0.75 at 25 °C, rerated with the maker's curve for the
   real ambient [Littelfuse Fuseology Design Guide, pp. 3, 6] (*rule of thumb*).
3. Check repetitive pulses: pulse I²t no more than 20% of the device's melting I²t (same, p. 4).
4. Check that the voltage rating is at least the circuit voltage (same, p. 6), and that the
   time-current curve opens before the weakest protected element exceeds its rating (*derived* from
   the device's purpose, §9). If no rating fits between the two, this library's choice is to change
   the conductor rather than the margin.

## Procedure: the derating record

1. For each power-path part, tabulate: parameter, operating worst case, rating, condition, ratio,
   source (§7).
2. State the basis: manufacturer recommended operating conditions (this library's limit), or a named
   published derating practice the design chooses to follow, with its class of hardware stated.
3. Mark any ratio above the chosen basis, and any transient without its own rating (§7).

## Procedure: ERC and part records

1. Check each symbol's pin electrical types against the datasheet, then run the ERC (§12).
2. Give each power net a power-output pin or a PWR_FLAG, and each intentionally open pin a
   no-connect flag [KiCad *Schematic Editor* manual, 9.0].
3. Clear every error and warning, or exclude it with a written reason; save the report (steps 3–4
   are this library's choice, §12).
4. Record per part: manufacturer part number, datasheet and revision, ratings used with conditions.

## Connector conventions

- Rate and record current per contact from the connector maker's contact rating and its
  conditions (§1, §8); EEE-INST-002's tie of contact current to its vacuum wire table is space
  practice, not adopted.
- Connect every board's ground to the common ground; the Balboa guide says the ground node "should
  be connected to the ground node of every other circuit board or device" [§3.10, p. 36].
- Make wrong mating impossible or harmless, and separate power and return contacts by an unassigned
  contact: both are space practice [ECSS-Q-ST-30-11C Rev.2, §6.11.3a and c, p. 39], offered here as
  practice, not adopted as rules.
- Record which side of the overcurrent device each battery-side connector sits on; a connector
  ahead of the fuse is unprotected against a short (§9).

## Antipatterns

- **Designing to the absolute maximum rating.** It is a stress rating, not an operating limit (§1).
- **A power budget of typical currents.** Stall, start-up and coincident peaks are the cases that
  trip protection and brown out the logic (§2).
- **Quoting the chip's rating for the board.** For example, on the Balboa a 3 A regulator chip sits
  on a board documented at 2 A, before a 1.9 A multiplexer (§1, §2).
- **One battery voltage.** Checking at nominal hides the top and the sagged bottom; for example, a
  six-NiMH pack of nominal 7.2 V reaches about 8.4 V charged (§4).
- **Stall current at the motor's rated voltage.** Stall current scales with the applied voltage;
  the check uses the pack's highest voltage (§5).
- **TJ = TA + θJA × P on a real board, unlabelled.** θJA is a JEDEC test-board figure; on another
  board the result can be badly wrong (§6).
- **Space derating presented as physics.** ECSS and NASA factors are practice for spacecraft parts;
  cite them as a chosen basis or not at all (§7).
- **Trace width from the IPC-2221 fit without ΔT, layer or range.** The fit is a rule of thumb, and
  newer data change the internal case (§8).
- **Vacuum wire ratings used in air.** The NASA and ECSS tables state vacuum conditions (§8).
- **A fuse sized at the load current.** Loaded at 100% it nuisance-opens; sized above the wire's
  rating it protects nothing (§9).
- **Brown-out enabled and assumed sufficient.** The trip level must sit above what the clock needs
  (§9).
- **A clean ERC taken as a correct schematic.** ERC cannot detect all errors (§12).
- **A 3.3 V to 5 V link checked one way.** Both directions and the receiver's maximum input apply
  (§10).
- **Bulk capacitor rated at the nominal supply.** Regenerated motor energy raises the rail; the
  rating must exceed the highest operating voltage (§11).
