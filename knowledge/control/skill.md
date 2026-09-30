# Control — skill

> **Status: DRAFT candidate, staged for review — not promoted.** Procedures and antipatterns,
> reusable across control tasks; every numbered standard it cites lives in
> `knowledge/control/standards.md`, drafted alongside this file and under the same review.

## Procedure: sizing a PID loop from a plant model

1. Obtain a linear or linearized plant model, and state the operating region it is valid in
   (standards §1).
2. Choose a starting point: the Ziegler–Nichols closed-loop test (standards §4) if no trusted
   analytic model exists yet; otherwise a synthesis method aimed at the margins in standards §2.
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

- **Reporting margins measured on the wrong loop.** Full-state-feedback LQR carries a provable
  60°/6 dB guarantee (standards §2); the same gains behind an observer do not inherit it. A margin
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
