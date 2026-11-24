# Control — skill

> Procedures and antipatterns for control tasks; each §N cited is in `knowledge/control/standards.md`.

## Procedure: sizing a PID loop from a plant model

1. Obtain a linear or linearized plant model, and state the region it is valid in (standards §1).
2. Choose a starting point: the Ziegler–Nichols closed-loop test (standards §4) only if no trusted
   analytic model exists and the loop is stable in open loop; otherwise a synthesis aimed at the
   margins of standards §2.
3. Simulate step response, disturbance rejection, **and actuator saturation together**: margins on
   a linear model do not see saturation, and a controller that looks fine on a small step can wind
   up on a large one.
4. Record in the module's spec: the achieved margins, the sample-rate ratio and the side of the
   trade-off it favours (standards §3), the validity region, and the anti-windup scheme (§6).

## Procedure: sizing an LQR/LQG loop

1. Set `Q`/`R` by Bryson's rule (standards §5), stating the acceptable deviations first; iterate
   for the settling time/control-effort trade-off, and record the deviations and the final weights
   together.
2. If a state estimator closes the loop, measure the margins **on the estimator-plus-controller
   loop**, never on the full-state-feedback loop alone: they are different systems, and the
   combined one is unguaranteed (standards §2).

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
5. Compute the margins at the low end, nominal and high end of each estimated range, one at a time,
   with a sweep across each range, each judged end with its basis (standards §7).
   The design's margin is the smallest of each over those; every combination of the ends is
   recorded beside it, never as the design's margin. A maker's stated tolerance is held at its
   typical value and its ends recorded as a sensitivity; a bound that only limits what is possible
   is no end: state the range the design holds over, with the nominal in it, and the measurement
   that settles it.
6. Run the step, disturbance, saturation and recovery simulations again with the new law (rubric D33) at the nominal plant and at each end of step 5, and
   record them at the tolerances' ends, each with its largest motor current against the driver's
   rating (standards §6): a conflict over this current is yours to record, with these runs, only
   where you show a criterion cannot be met while within the rating. Where
   the push fails at an estimate's end, compute its stated bound there (standards §7); below 1,
   state the value of each quantity another module owns that would bring it to 1 and whether it
   lies inside its owner's bound; record a request to the owner if so, else the conflict, once; the
   criterion stays not met at that end, the request or conflict named. Go on with the law.
7. Write the law and every coefficient, with units and their integer form, on your own node,
   restating the sample period and command limit from the interface or sizing node each comes from;
   name the node in what you report, and state the law as a file too (the next procedure). In an
   incremental (velocity-form) law a direct term is added after the accumulator and its clamp,
   never into it; the sum is limited to the command limit, and that sum is what the margin script,
   the simulations and the node hold.
8. Print what a reviewer needs to redo the margins by reading: the plant's numbers with sources and
   ranges, the law and its coefficients, each delay with its source (the sensor's filter delay among
   them), where the loop is broken, the frequency grid, and, for every parameter case, `ω_gc`, the
   phase margin, both gain margins and the delay margin, and, at the crossover that sets the
   reported phase margin, the phase margin of the same loop with its pure delays common to every
   fed-back output removed (the reported one is lower by `ω_gc·τ`; rubric D34).

## Procedure: stating the law as a file

`law.json` at the top of the control module's directory, for the law the firmware runs, in JSON,
names in lowercase letters, digits and `_`: the law as the firmware computes it (standards §7).
1. `form` `"sampled_law_file"`, `version` 1. `memory`: `{name, unit, next, applied}`, `next` the line
   giving the state's next value, `applied` true for the command as applied. `lines`, in the order
   computed: `{name, unit, terms}`, a term `{sign (1 or -1), number, coefficients [names], per
   [names], of}` with one variable `of`: `tilt` rad, `tilt_rate` rad/s, `wheel_angle` rad,
   `wheel_speed` rad/s or `wheel_reference` rad (converted from counts first), `previous.<state>` or
   `line.<name>`. `command`: the line with the duty before the limit, unit `1`. Units balance in
   every line. A product of two variables, a function, a comparison or another signal cannot be
   written: state the law in full with that term in it, never without it. A memory state no term reads
   is refused.
2. `coefficients`: each name a term uses, mapped to the node quantity that holds its number (no
   number in the file). Top-level keys of their own, not inside `coefficients`: `period`
   `{"reciprocal_of": <update rate>}`; `command_limit`, `sensor_delay` and `compute_delay`, each
   `{"quantity": name}` or `{"sum_of": [names]}` of interface or sizing quantities: the interface's period, a sensor delay no smaller than 1/(the gyro's output
   data rate), a limit no larger than the interface's duty cycle.
3. `vectors`: `{name, start, rows}`, a row the signals set, the `duty` before the limit, the `counts`
   out and the `memory` after: at least ten rows, written by a module script from the node's
   numbers, each term's variable non-zero somewhere, a 2 % change in any one coefficient breaking
   some row (duty to 1e-5, counts to 1).

## Antipatterns

- **A margin from a model without its delays.** Each delay subtracts `ω_gc·τ` of phase at
  crossover; the delay-free margin is the margin of a loop that never runs (standards §7).
- **The reference law kept because a brief cites it.** A cited reference supplies numbers; the form
  is control's unless the specification fixes it (standards §7).
- **Coefficients only in prose or in code.** Firmware implements what is on control's node (standards §7).
- **Reporting margins measured on the wrong loop.** Continuous-time full-state-feedback LQR
  with diagonal R carries a provable 60°/6 dB guarantee (standards §2); the same gains behind an observer, or run
  sampled, do not inherit it. A margin with no statement of which loop it was measured on is not
  verifiable.
- **Tuning only at the nominal operating point.** It never tests the validity region claimed (standards §1).
- **Judging the design at every corner at once, or chasing a criterion the plant cannot meet.**
  The design's margin is the worst over each estimate's ends one at a time; the corners are
  recorded only. A criterion its stated bound shows unreachable at an end is a request or a
  conflict to record (standards §7), not a reason to keep retuning.
- **Treating a Ziegler–Nichols result as a finished design.** Its response is oscillatory
  by construction (standards §4).
- **Sizing actuators after the control design commits to a saturation-free assumption.** An
  actuator found to saturate in normal operation is cheaper to catch in control's own simulation
  (standards §6).
- **Defaulting the sample rate to a round number with no stated ratio.** "100 Hz because that is
  what we always use" is no argument (standards §3); state the ratio to the closed-loop bandwidth
  achieved.

---

## Procedure: computing with the run's tool environment

1. Compute with the libraries, never by hand: python-control (transfer functions, state space,
   margins, responses), numpy and scipy around them, MuJoCo for a nonlinear, contact or multibody
   model. Run them from a script under the module with the session's `python3 -B`, the run's
   recorded tool environment, fixed and without network: never install a package, make an
   environment or set `PYTHONPATH`. `-B` writes no bytecode, which a script importing another
   module's code would otherwise put in that module's folder, and the attempt is refused for it;
   set no cache prefix either, which the recording writer refuses. Name a missing library in the module's spec; never write a
   substitute.
2. The pinned version's conventions [python-control 0.10.1 reference; each checked by running it]:
   - `control.stability_margins(L)` returns `(gm, pm, sm, wpc, wgc, wms)`: the gain margin as a
     ratio (not dB), the phase margin in degrees (the extractor's `phase_margin` is in rad), the
     frequencies in rad/s; `L` is the loop broken where the margin is claimed (standards §2). On a
     loop unstable in open loop it returns one gain margin of several, and a `gm` below 1 is a lower
     margin: ask for all with `returnall=True`. Its `sm` misses a minimum of |1 + L| approached at
     ω → 0 or ω → ∞: report the extractor's `stability_margin`. A lower gain margin set at ω = 0
     lies on no recorded grid: state it from the model, and say so.
   - `control.margin(L)` returns `(gm, pm, wcg, wcp)`: `wcg` is the phase crossover (where the
     gain margin is read), `wcp` the gain crossover.
   - `mag, phase, omega = control.frequency_response(L, w)` evaluates on `w`, in rad/s, given as a
     numpy array: a list of exactly two frequencies is read as the limits of a range of 1,000. The
     magnitude is a ratio and the phase is in rad, **wrapped to [−π, π]**: pass `.tolist()` of
     each, as returned, to `series_writer.extract`, which unwraps along the grid.
   - `control.step_info(T, T=t)` on the times given to `control.step_response(T, T=t)`. Rise time
     is 10–90 % and settling 2 % by default: state the thresholds with the numbers.
   - `control.c2d(G, Ts, method="zoh")` gives the sampled plant; a controller that runs sampled
     has its margins measured on the sampled loop (standards §2, §3).
3. MuJoCo [MuJoCo 3.17 XML reference, `option`]: load the model from a file in the module
   (`mujoco.MjModel.from_xml_path`) and state its `opt.timestep` (default 0.002 s, semi-implicit
   Euler). For a sampled controller, make the sample period a whole number of steps and apply the
   controller once every that many steps, or the loop simulated runs at another period than the
   one its margins were measured at. Never open the viewer or render; draw noise from
   `numpy.random.default_rng(seed)` and record the seed. matplotlib runs with `Agg`: save figures
   into the module.

## The tool servers are working aids

The `control` server (`margins`, `step_response`, `frequency_response`, `poles_zeros`, on a system
given inline) and the `mujoco` server (`load_model`, `step`, `state`, `reset`, `model_info`) return
quickly while exploring. **Nothing they return is evidence:** it has no record behind it and cannot
be re-checked. A number in the module's spec or the graph comes from a module script that ran the
library and recorded its output (the next procedure).

## Antipatterns: the tool environment

- **A margin copied from a tool server's output.** Recompute it in a module script and report
  what the record shows.
- **A library reimplemented by hand** (a margin search, an integrator): the numbers rest on code
  nobody reviewed instead of the pinned library.
- **A MuJoCo run quoted as confirming linear margins.** They are different systems: report each
  with its model, and where they disagree.

---

## Procedure: recording a simulation's output as series records

0. Record each analysis as it finishes, the design first (law, coefficients, nominal margins), then
   each sweep, end and corner run. A session ends at its time limit with
   what is written, and the next starts from it: a cut session should leave a design to judge.
1. Keep every script that produces a reported result under the module directory and run it from
   there: a record is refused if any code that produced it ran from outside the module (a scratch
   script under `/tmp`, say), the libraries of the run's recorded tool environment apart, since only
   the module is committed with the attempt. Write the record from the script that ran the
   simulation, after it ran.
2. Record each run with the series writer, `series_writer.py`, at the path your prompt names; its
   opening lines show how a script under the module imports it and calls `series_writer.record`.
   One record per run: one time or frequency axis, every trace with its unit, the run's inputs as
   value-and-unit pairs, the seed included. Write to the series outbox only through the writer, from
   a script's own run (the Write and Edit tools are refused there). At the session's end the harness
   seals a record only if its script and every file of code it loaded lie in the module, unchanged
   and committed with the attempt, or are library code of the run's tool environment. Never commit a
   record into the module.
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

- **A reported margin with no record behind it.** One that exists only as printed text cannot be
  plotted or re-checked.
- **Analysis code outside the module.** Results from scratch scripts are refused as records: put
  the script in the module and run it there.
- **A peak read off a coarse grid of a lightly damped loop.** A grid that steps over a sharp
  resonance reports a lower peak than the loop has: record densely around the crossover and any
  resonance, and report what the extractor reads on that grid.
