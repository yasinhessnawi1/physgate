# Control — skill

> Procedures and antipatterns,
> reusable across control tasks; every numbered standard it cites lives in
> `knowledge/control/standards.md`, drafted alongside this file and under the same review.

## Procedure: sizing a PID loop from a plant model

1. Obtain a linear or linearized plant model, and state the operating region it is valid in
   (standards §1).
2. Choose a starting point: the Ziegler–Nichols closed-loop test (standards §4) if no trusted
   analytic model exists yet and the loop is stable in open loop; otherwise a synthesis method aimed
   at the margins in standards §2.
3. Simulate step response, disturbance rejection, **and actuator saturation together** — margins
   measured on a linear model do not see saturation, and a controller that looks fine on a small
   step can still wind up on a large one.
4. Record in the module's spec: the achieved gain/phase margins, the sample-rate ratio used and
   which side of the trade-off it favours (standards §3), the plant model's validity region, and the
   anti-windup scheme (standards §6).

## Procedure: sizing an LQR/LQG loop

1. Nondimensionalize states and inputs by their acceptable deviations before choosing weights —
   this is what Bryson's rule (standards §5) already does for you if you state the deviations first.
2. Set `Q`/`R` by Bryson's rule as a starting point; iterate for the desired settling
   time/control-effort trade-off, and record the acceptable deviations and the final weights
   together, not the weights alone.
3. If a state estimator (Kalman filter, observer) closes the loop, measure stability margins **on
   the estimator-plus-controller loop**, never on the full-state-feedback loop alone — the two are
   different systems with different (and for the combined loop, unguaranteed) margins (standards
   §2). This is the single most cited pitfall in LQR/LQG practice and is easy to get right by
   construction: simulate the loop you will actually run, not the one you designed the gains from.

## Antipatterns

- **Reporting margins measured on the wrong loop.** Continuous-time full-state-feedback LQR
  (diagonal `R`, loop broken at the plant input) carries a provable 60°/6 dB guarantee (standards
  §2); the same gains behind an observer, or run as a sampled controller, do not inherit it. A margin
  number with no statement of which loop it was measured on is not verifiable and should be
  challenged in review.
- **Tuning only at the nominal operating point.** A controller exercised only at the linearization
  point in simulation never tests the validity region it claims (standards §1).
- **Treating a Ziegler–Nichols result as a finished design.** The method's own target response is
  oscillatory by construction (standards §4); reporting its output unmodified as the final gains
  without further iteration is a known-weak result, not a mistake unique to this project.
- **Sizing actuators after the control design commits to a saturation-free assumption.** Discovering
  during mechanical/electrical sizing that the chosen actuator saturates under normal operation is
  far more expensive to fix than catching it in the control role's own simulation (standards §6).
- **Defaulting the sample rate to a round number with no stated ratio.** "100 Hz because that is
  what we always use" is not an argument against the aliasing/computation trade-off in standards §3;
  state the ratio to the closed-loop bandwidth actually achieved, not the number that was easy to
  pick.

---

## Procedure: recording a simulation's output as series records

1. Keep every script that produces a reported result under the module directory and run it from
   there. A record is refused when the session ends if any code that produced it ran from outside
   the module (a scratch script under `/tmp`, for instance): only the module is committed with the
   attempt, so only its code can stand behind a curve. Write the record from the script that ran
   the simulation, after it ran.
2. Record each run with the series writer, `series_writer.py`, at the path your prompt names.
   Its opening lines show how a script under the module finds and imports it, and how to call
   `series_writer.record`. One record per run: one time or frequency axis, every trace with its
   unit, the run's inputs as value-and-unit pairs, the seed included. Records land in the series
   outbox your prompt names; write there only through the writer, from a script's own run (the
   Write and Edit tools are refused there). When the session ends the harness collects the
   outbox and seals a record only if its script, and every file of code it loaded, lie in the
   module, are unchanged, and are committed with the attempt: a helper the module ignores or
   never adds refuses the record. Never commit a record into the module.
3. For a feedback loop, record at least:
   - the step response the specification asks for (time in `s`; position, tilt and command, each
     in its unit);
   - the loop's frequency response, broken where the margins are measured, one record per
     parameter case: angular frequency in `rad/s` (or `Hz`), the traces `loop_magnitude` as a
     plain ratio (`dimensionless`, never dB) and `loop_phase` in `rad` (or `deg`), on the grid the
     margins are read from;
   - every edge-of-region run, one record each, under one group (`edge_runs`).
4. A graph quantity computed from a record names it: `"series": {"record": "<id>", "extract":
   "<extractor>"}`, with `"trace": "<name>"` for a time trace. The extractors are
   `phase_margin`, `gain_crossover_frequency`, `delay_margin`, `gain_margin_upper`,
   `gain_margin_lower`, `stability_margin`, `sensitivity_peak` and
   `complementary_sensitivity_peak` on a frequency response, and `max`, `min`, `max_abs` and
   `final` on a time trace.
5. **Report the value you read off your own recorded samples with the published extractor:**
   `series_writer.extract("phase_margin", omega=ws, magnitude=mags, phase=phases)`, or
   `series_writer.extract("max_abs", values=xs)`, on exactly the samples you recorded. The harness
   reads the same value off the record with the same functions and refuses the attempt
   if the two differ by more than three significant figures; the repair then names
   both numbers. A value computed another way, or on a finer grid than the one recorded, can
   differ by more than that.
6. In a repair attempt, run the scripts again after any change: records belong to the attempt
   that produced them and never carry over.

## Antipatterns: simulation records

- **A reported margin with no record behind it.** A margin that exists only as printed text cannot
  be plotted or re-checked; one that names the frequency response it was read from can be both.
- **Analysis code outside the module.** Results computed by scratch scripts are visible only as
  tool calls in the transcript and are refused as records; put the script in the module and run
  it there.
- **A peak read off a coarse grid of a lightly damped loop.** A sensitivity peak is read at the
  recorded samples, so a grid that steps over a sharp resonance reports a lower peak than the
  loop has. Record the frequency response densely around the crossover and any resonance, and
  report what the extractor reads on that grid.
