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

## Procedure: when the reference law cannot meet the margins

1. Read your specification: does it fix the controller's form, or only cite a reference for its
   numbers? Where it fixes the form, report a shortfall as standards §7's last paragraph says, and
   stop there.
2. Build the loop that runs: the plant with every estimated parameter at its nominal value, the
   law as the firmware will compute it, the hold, the time from sample to command, and each
   sensor's age (standards §2, §3, §7). Compute and print the margins of the reference law on it.
3. Where they miss, show it is the form that misses: the coefficients tried and the best margins
   found, printed.
4. Add the least structure that meets the margins: a direct term on a measured rate first, then
   lead, then full state feedback (standards §7). Choose its coefficients by a stated method
   (§4, §5), never by trial alone.
5. Compute the margins at the low end, nominal and high end of each estimated parameter's range,
   one at a time, and print a sweep across each range. Report the smallest of each margin over
   those as the design's (standards §7). Compute and record every combination of the ends too,
   beside it, never as the design's margin. A maker's stated tolerance (a no-load speed's ±20 %)
   is not an estimate: hold its typical value, and record its ends as a sensitivity.
6. Run the step, disturbance, saturation and recovery simulations again with the new law (skill,
   "sizing a PID loop", step 3; rubric D33), at the nominal plant and at each end of step 5, and
   record them at the tolerances' ends. Where the push fails at an estimate's end, compute its
   stated bound there (standards §7); below 1, record the conflict once, as standards §7 says, and
   go on with the law.
7. Write the law and every coefficient, with units and their integer form, on your own node, with
   the sample period and command limit restated from the interface or sizing node each comes from;
   name the node in what you report (standards §7). In an incremental (velocity-form) law, a direct
   term is added to the command after the accumulator and its clamp, never into it; the sum is then
   limited to the command limit, and that sum is what the margin script, the simulations and the
   node hold.
8. Print what a reviewer needs to redo the margins by reading: the plant's numbers with their
   sources and ranges, the law and its coefficients, each delay with its source, where the loop is
   broken, the frequency grid, and, for every parameter case, `ω_gc`, the phase margin, both gain
   margins and the delay margin, and, at the crossover that sets the reported phase margin, the
   phase margin of the same loop with its pure delays common to every fed-back output removed
   (the reported one is lower by `ω_gc·τ`: exactly for a pure delay; the hold's half sample is an
   approximation, standards §3; rubric D34).

## Antipatterns

- **A margin from a model without its delays.** Each delay subtracts `ω_gc·τ` of phase at
  crossover; the delay-free margin is the margin of a loop that never runs (standards §7).
- **The reference law kept because a brief cites it.** A cited reference supplies numbers; the form
  is control's unless the specification fixes it (standards §7).
- **Coefficients only in prose or in code.** Firmware implements what is on control's node; a law
  that is not there cannot be checked against what runs (standards §7).
- **Reporting margins measured on the wrong loop.** Continuous-time full-state-feedback LQR
  (diagonal `R`, loop broken at the plant input) carries a provable 60°/6 dB guarantee (standards
  §2); the same gains behind an observer, or run as a sampled controller, do not inherit it. A margin
  number with no statement of which loop it was measured on is not verifiable and should be
  challenged in review.
- **Tuning only at the nominal operating point.** A controller exercised only at the linearization
  point in simulation never tests the validity region it claims (standards §1).
- **Judging the design at every corner at once, or chasing a criterion the plant cannot meet.**
  The design's margin is the worst over each estimate's ends one at a time; the corners are
  recorded only. A criterion its stated bound shows unreachable at an end is a conflict to record, not a
  reason to keep retuning or to change a range (standards §7).
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

## Procedure: computing with the run's tool environment

1. Compute with the libraries, never by hand: python-control for transfer functions, state
   space, margins, step and frequency responses; numpy and scipy around them; MuJoCo for a
   nonlinear, contact or multibody model. Run them from a script under the module with the
   session's `python3`, the run's recorded tool environment. It is fixed for the run and has no
   network: never install a package, make an environment of your own or set `PYTHONPATH`. Name a
   missing library in the module's spec; never write a substitute.
2. The pinned version's conventions [python-control 0.10.1 reference; each checked by running it]:
   - `control.stability_margins(L)` returns `(gm, pm, sm, wpc, wgc, wms)`: the gain margin as a
     ratio (not dB), the phase margin in degrees (the extractor's `phase_margin` is in rad), the
     frequencies in rad/s. `L` is the loop broken where the margin is claimed (standards §2). On
     a loop unstable in open loop it returns one gain margin of several, and a `gm` below 1 is a
     lower margin: ask for all with `returnall=True`. Its `sm` misses a minimum of |1 + L|
     approached at ω → 0 or ω → ∞: report the extractor's `stability_margin`. A lower gain margin
     set at ω = 0 lies on no recorded grid: state it from the model, and say so.
   - `control.margin(L)` returns `(gm, pm, wcg, wcp)`: `wcg` is the phase crossover (where the
     gain margin is read), `wcp` the gain crossover.
   - `mag, phase, omega = control.frequency_response(L, w)` evaluates on `w`, in rad/s, given as a
     numpy array: a list of exactly two frequencies is read as the limits of a range of 1,000. The
     magnitude is a ratio and the phase is in rad, **wrapped to [−π, π]**: pass `.tolist()` of
     each, as returned, to `series_writer.extract`, which unwraps along the grid.
   - `control.step_info(T, T=t)` on the times given to `control.step_response(T, T=t)`; without
     them it picks its own. Rise time is 10–90 % and settling 2 % by default: state the
     thresholds with the numbers.
   - `control.c2d(G, Ts, method="zoh")` gives the sampled plant; a controller that runs sampled
     has its margins measured on the sampled loop (standards §2, §3).
3. MuJoCo [MuJoCo 3.17 XML reference, `option`]: load the model from a file in the module
   (`mujoco.MjModel.from_xml_path`) and state its `opt.timestep` (default 0.002 s, semi-implicit
   Euler). For a sampled controller, make the sample period a whole number of steps and apply the
   controller once every that many steps, or the loop simulated runs at another period than the
   one its margins were measured at. Never open the viewer or render; draw noise from
   `numpy.random.default_rng(seed)` and record the seed. matplotlib runs with the `Agg` backend:
   save figures into the module.

## The tool servers are working aids

The `control` server (`margins`, `step_response`, `frequency_response`, `poles_zeros`, on a system
given inline) and the `mujoco` server (`load_model` from a worktree file or text, `step`, `state`,
`reset`, `model_info`) answer quickly while exploring. **Nothing they return is evidence:** it has
no record behind it and cannot be re-checked. A number in the module's spec or the graph comes
from a module script that ran the library and recorded its output (the next procedure).

## Antipatterns: the tool environment

- **A margin copied from a tool server's answer.** Recompute it in a module script and report
  what the record shows.
- **A library reimplemented by hand** (a margin search, an integrator): the numbers then rest on
  code nobody reviewed instead of the pinned library.
- **A MuJoCo run quoted as confirming linear margins.** The two models are different systems:
  report each with the model it came from, and state where they disagree.

---

## Procedure: recording a simulation's output as series records

1. Keep every script that produces a reported result under the module directory and run it from
   there. A record is refused when the session ends if any code that produced it ran from outside
   the module (a scratch script under `/tmp`, for instance), the libraries of the run's recorded
   tool environment apart: only the module is committed with the attempt, so only its code and
   those libraries can stand behind a curve. Write the record from the script that ran
   the simulation, after it ran.
2. Record each run with the series writer, `series_writer.py`, at the path your prompt names.
   Its opening lines show how a script under the module finds and imports it, and how to call
   `series_writer.record`. One record per run: one time or frequency axis, every trace with its
   unit, the run's inputs as value-and-unit pairs, the seed included. Records land in the series
   outbox your prompt names; write there only through the writer, from a script's own run (the
   Write and Edit tools are refused there). When the session ends the harness collects the
   outbox and seals a record only if its script, and every file of code it loaded, either lie in the
   module, unchanged and committed with the attempt, or are library code of the run's recorded
   tool environment: a helper the module ignores or never adds refuses the record, and so does a
   library loaded from anywhere else. Never commit a record into the module.
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
