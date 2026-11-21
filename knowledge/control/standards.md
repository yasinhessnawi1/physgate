# Control — standards

> Researched and drafted by the
> implementing agent (Yasin's content-authorship correction, 29.09.2026): every numeric threshold
> below is a widely corroborated convention or a provable result from the published control-systems
> literature, cited at first use, never a value chosen to make a fixture pass. Read
> `knowledge/cross/standards.md` first — this file does not repeat what it already states.

## 1. State the plant model's validity region

A linear or linearized plant model, a small-signal model, or a fixed operating point is accurate
only near where it was derived. State the region explicitly in the module's spec (an angle range, a
load range, a speed range) — a controller proven stable at one operating point makes no claim about
another.

**Judgement-only** — no automated check evaluates model fidelity against the physical system; the
gate's checks are about declared quantities, not about whether a linearization is valid where it is
used.

## 2. A closed loop reports its stability margins, not "it converged in simulation"

**For a continuous-time linear-quadratic regulator with full state feedback** (all states measured,
`R` diagonal, loop broken at the plant input), tolerance to at least a 50% gain reduction (−6 dB)
with unbounded tolerance to a gain increase, and at least 60° of phase margin in either direction,
in each plant input channel, are *provable* properties of the optimal regulator itself, not a design
target — a mathematical guarantee, not a convention. **This is two separate results, correctly
attributed, not one paper covering both:** the positive guarantee is Safonov & Athans's extension
of the original (scalar) result to the multivariable case [M. G. Safonov and M. Athans, "Gain and phase
margin for multiloop LQG regulators," *IEEE Transactions on Automatic Control*, vol. 22, no. 2,
pp. 173–179, Apr. 1977]. Its conditions are part of the result: it holds for the continuous-time
loop "if the weight R is chosen to be diagonal", "in each plant input control channel"
[S. Skogestad and I. Postlethwaite, *Multivariable Feedback Control*, Wiley, 2nd edition, 2005,
§9.2.2]. **This draft's reading, not the source's:** the result is stated for the continuous-time
loop, so it covers no sampled implementation; for a discrete-time LQR, or a continuous design behind
a zero-order hold or a computation delay, measure the margins on the discrete loop. The guarantee is
*not* Doyle 1978's own result — Doyle's paper cites it as background, verbatim: "the now well-known
guarantee of 60° phase and 6 dB gain margin for such controllers," crediting Safonov & Athans
directly, before proving something else. What Doyle 1978 actually proves is the negative result
this guarantee does **not** extend to: once a state estimator (a Kalman filter) closes the loop with
output feedback instead of full state feedback, **no** margin is guaranteed at all [J. C. Doyle,
"Guaranteed margins for LQG regulators," *IEEE Transactions on Automatic Control*, vol. 23, no. 4,
pp. 756–757, Aug. 1978,
DOI: 10.1109/TAC.1978.1101812]. That negative result is a worst-case, adversarial construction — a
noise/weight parameter choice engineered to drive the margin to zero — not a claim that every real
LQG design has small margins in practice; Doyle's own paper says so directly ("modern LQG designers
are obliged to test their margins for each specific design"). The practical conclusion is the same
either way: **no guarantee exists once an estimator is in the loop**, so the margin has to be
measured on that design, not assumed from the LQR theorem.

**For any other design method** (classical loop-shaping, PID, pole placement without the LQR
structure), no such guarantee exists either. Read directly from a primary source rather than a
secondary paraphrase: "reasonable values of the margins are phase margin φ_m = 30°–60°, gain margin
g_m = 2–5, and stability margin s_m = 0.5–0.8" [K. J. Åström and R. M. Murray, *Feedback Systems: An
Introduction for Scientists and Engineers*, Princeton University Press, 2nd edition, 2021, Chapter
10 ("Frequency Domain Analysis"), §10.3 "Stability Margins," p. 10-17, in the text following
Example 10.8; freely available at
https://www.cds.caltech.edu/~murray/amwiki]. Note the gain margin `g_m` there is a **ratio**, not
decibels — 2–5 corresponds to roughly 6–14 dB. The same section is worth reading for **why gain and
phase margins alone are not sufficient**: it gives a worked example (their Example 10.8) of a system
with a good gain margin (266) and a good phase margin (70°) that is still highly oscillatory in
practice, because the Nyquist curve passes close to the critical point between the two — its
**stability margin** `s_m` (the shortest distance from the loop's Nyquist plot to the point −1, a
single number that gain and phase margins do not by themselves guarantee against) is only 0.27,
well under the 0.5–0.8 reasonable range. Report the stability margin alongside gain and phase
margin where it can be computed, not gain and phase margin alone.

State which case applies (LQR's provable guarantee, or the practitioner target range for everything
else), and if a state estimator is in the loop, measure margins **on the loop that includes the
estimator**, not on the full-state-feedback loop alone — measuring the wrong loop is the single most
common way this rule is satisfied on paper and violated in practice.

**Judgement-only** — no closed-loop stability check exists in this gate; a static, single-artefact
gate cannot run the simulation a margin measurement needs.

## 3. A sampled/digital controller's sample rate is stated relative to its closed-loop bandwidth, and the ratio is argued, not defaulted

**Verified directly against a primary source, not a secondary paraphrase**, after an initial draft
of this rule had to be flagged as unverified and was corrected on review. Choosing a sampling period
by continuous-time arguments — approximating the hold circuit as a half-sample time delay and
budgeting how much phase margin an antialiasing filter and the hold are allowed to cost a loop whose
crossover frequency is `ω_c` — gives the rule of thumb `h·ω_c = 0.05` to `0.14` (`h` the sampling
period in seconds, `ω_c` in rad/s), derived from allowing the filter and hold together to cost
5°–15° of phase margin with a filter damping ratio of 0.707 and a filter gain of 0.1 at the Nyquist
frequency. The band is the source's own eq. (36), and the authors add, verbatim: "this rule gives a
Nyquist frequency that is about 23 to 70 times higher than the crossover frequency"
[B. Wittenmark, K.-E. Årzén, and K. J. Åström, "Computer Control: An Overview," IFAC Professional
Brief, International Federation of Automatic Control, 2002, §"Selection of Sampling Interval and
Antialiasing Filters", eq. (36) — freely available via Lund University's publication repository].
**The following step is this draft's own arithmetic, not the source's:** since the sampling
frequency is by definition twice the Nyquist frequency, the 23–70× Nyquist-to-crossover ratio
implies a sampling-frequency-to-crossover ratio of roughly **46 to 140 times** — arithmetically valid, but a number the cited authors never state, so
it is marked here as derived rather than quoted.

This is a *derivation under stated assumptions* (a specific phase-margin budget, filter damping and
filter gain at the Nyquist frequency), not a universal law — state the assumptions actually used if
a different phase-margin budget or filter design changes the resulting ratio, rather than quoting
46–140× as if it applies unconditionally.
A lower multiple costs tracking performance and disturbance rejection; a higher one costs computation
without buying anything past what the phase-margin budget already required. The Nyquist rate itself
(twice the highest frequency of interest) is the theoretical floor below which information is lost
outright, not a design target on its own — the rule above is already well above it for exactly this
reason. The rule applies when a continuous-time design is translated into a digital controller; for
a controller designed directly in discrete time, the same brief gives a separate rule from
experience and simulations, `ω·h = 0.1` to `0.6` with `ω` the desired closed-loop natural frequency [same brief,
§"Sampling Period Selection"].

**Judgement-only.**

## 4. A PID controller's gains are derived from a stated method, not guessed

The Ziegler–Nichols closed-loop method gives a reproducible starting point from two measured
numbers — the ultimate gain `K_u` and ultimate period `P_u` at which the loop first sustains
constant-amplitude oscillation under proportional-only control — with the classic three-term
setting `Kp = 0.6 K_u`, integral time `Ti = 0.5 P_u`, derivative time `Td = 0.125 P_u`
[J. G. Ziegler and N. B. Nichols, "Optimum Settings for Automatic Controllers," *Transactions of the
ASME*, vol. 64, pp. 759–768, 1942]. It is well known to produce an aggressive, oscillatory
("quarter-amplitude decay") response and is a documented **starting point**, not a finished tuning —
state whichever method actually produced the reported gains and why, if it was not this one.
Neither Ziegler–Nichols experiment is available for a balancing robot's tilt loop: the step method
needs "the open loop unit step response", which diverges, and the frequency method raises a
proportional gain "until the system starts to oscillate" [Åström and Murray, *Feedback Systems*,
2nd edition, §11.3]. **This draft's own derivation, not the source's:** for the normalised inverted
pendulum `1/(s² − 1)` [same book, Example 10.5], proportional gain `k` gives the closed loop
`s² + (k − 1)`, which is unstable for k < 1 and undamped for every k > 1, so there is no ultimate
gain to find. Use Ziegler–Nichols only on a stable inner loop (e.g. motor speed).

**Judgement-only.**

## 5. An LQR design's Q/R weights are derived from a stated tolerance, not tuned blind

Bryson's rule sets the diagonal of the state-cost matrix `Q` and input-cost matrix `R` from the
largest deviation of each state or input considered acceptable: `Q_ii = 1 / (max acceptable
deviation of state i)²`, `R_jj = 1 / (max acceptable value of input j)²` — a normalization that
matters especially when the states have very different units and natural scales
[A. E. Bryson Jr. and Y.-C. Ho, *Applied Optimal Control: Optimization, Estimation, and Control*,
Hemisphere Publishing, 1975, as given consistently in graduate control course notes deriving it,
e.g. J. P. Hespanha's LQR/LQG lecture notes]. It is a documented starting point for further
iteration on the time-response/control-effort trade-off, not a proof that the resulting design is
correct — state the acceptable deviations that produced the weights, not only the final matrices.

**Judgement-only.**

## 6. Actuator limits are declared, and the design accounts for saturation

Integrator windup during actuator saturation is a named, well-documented failure mode of every
integral-action controller. Declare the actuator's limits as part of the module's quantities (the
gate's check 4 covers declared draw against what a declared source can supply) and state the
anti-windup scheme used, or the specific reason none is needed (e.g. the actuator is never
expected to saturate in the stated operating region, per rule 1).

**Judgement-only** for the anti-windup design itself; the actuator's declared supply limit is
gate-checked the same way any other supply is (cross-domain standards §4).

## 7. When the reference controller cannot meet the margins, add the least structure that can, and show its margins on the loop that runs

A brief or specification may cite a reference controller (a maker's example program) as a source of
numbers: a sample period, a command limit, a coefficient's scale. Unless the issued specification
fixes the controller's form, the form is control's decision, and a cited reference does not fix it
(design standards §7). When the work shows that the reference form cannot meet the specified
margins at any coefficients it tried (the set tried and the best result, printed), control may add
structure, the least that meets them:
- **a direct term on a measured rate** (the tilt rate from a gyro, added to the command): state
  feedback on a measured state, which adds phase lead at crossover without differentiating a noisy
  signal [K. J. Åström and R. M. Murray, *Feedback Systems: An Introduction for Scientists and Engineers*, Princeton University Press, 2nd edition, 2021, Ch. 7 "State Feedback", section "Stabilization by State Feedback"; in the 2008
  first edition, §6.2];
- **lead compensation**, a pole/zero pair that adds phase around crossover [same book, Ch. 12
  "Frequency Domain Design", section "Feedback Design via Loop Shaping"; first edition §11.4]. One
  lead section `C(s) = (s/a + 1)/(s/b + 1)`, `b > a > 0`, adds at most `arcsin((b − a)/(b + a))` rad
  of phase, at `ω = √(ab)` (*derived*: its phase is `arctan(ω/a) − arctan(ω/b)`);
- **state feedback** on every state the firmware measures or estimates, with the weights from §5
  where it is an LQR design.

Three conditions hold whatever is added.

**The margins are those of the loop that runs, every delay included.** The loop's margins are
computed with each delay the implementation has: the time from sample to command, the age of each
sensor's reading at the sample, and the hold (half a sample at crossover, §3; or exactly, on the
discrete loop). A pure delay `τ` leaves the gain unchanged and subtracts `ω·τ` rad of phase at every
`ω` (*derived*: `|e^(−jωτ)| = 1`, `arg e^(−jωτ) = −ωτ`). So a delay common to the whole loop at its
break point (`τ_common`, as the control rubric defines it) lowers the phase margin by
`ω_gc·τ_common` (exactly for a pure delay; the hold's half sample is an approximation, §3) at an
unchanged crossover, and a margin computed without the delays overstates the margin of the loop
that runs. A margin from a model without its delays does not
meet a margin criterion, and is not reported as the design's.

**The margins hold across the stated spread.** Each plant parameter that is an estimate, a quantity
no maker publishes that the work had to estimate (a rotor inertia, a centre-of-mass height, a body
inertia, a friction the work itself estimated; one taken from the maker's no-load current is a
maker's figure, below), carries a range from where it was sourced (sizing standards §5, §8); so
does a range the brief states (a fall time's). The margins are computed at the low end, the nominal value
and the high end of each such range, one at a time, with the others nominal; the smallest value of
each margin over those cases is the design's margin, the one compared with the criterion. This is
the parametric form of model uncertainty [same book, Ch. 13 "Robust Performance", sections "Modeling
Uncertainty" and "Stability in the Presence of Uncertainty"; first edition §12.1, §12.2]. A check at
points is not a proof between them: the work also prints a sweep across each range, one at a time,
and its smallest value is the design's where it is lower than the end points'. The work also
computes the margins at every combination of the ranges' ends and records them beside the design's;
they are not compared with the criterion, and a combination that misses is not a shortfall. *This
project's rule, not the source's:* each range is a separate estimate with its own basis, and every
range at its worst end at once assumes every estimate wrong in its worst direction together, which
no basis states; the combinations are kept for a person to see. A maker's stated tolerance on a
figure it publishes (a no-load speed's ±20 %, a no-load current's ±50 %), quoted from the maker's
document in the quantity's source, is not an estimate (*this project's rule*, as in sizing
standards §12); without that quote the range is an estimate. Every criterion is judged with the
figure at its typical value, and the results at the tolerance's ends are computed and recorded as a
sensitivity, not judged. A supply voltage a criterion of the brief pins is a condition, not an
estimate, and is held at that value.

**A criterion no design can meet at an end.** This applies only to a criterion with a stated
bound: the push, with sizing standards §12's bound, §12's inputs and the delivered command limit,
in control's own plant at the end's values. Where it fails at an estimate's end and that bound is
below 1 there, the shortfall is the plant's, not the law's. The work records it once, as a conflict
in its module's record (as sizing standards §3 does): the criterion, each such end, the command
limit the bound needs there against the limit written and the full scale, and the bound's numbers.
It delivers its law, meeting every criterion it can, and changes no criterion, range or limit for
it. Where the bound is 1 or more at an end where the law fails, the shortfall is the
law's. A criterion that fails only at a tolerance's end is recorded with that sensitivity, not as
a conflict.

**The law that firmware runs is written on control's own node.** Control writes the law in the form
the firmware will run (the update equation, its sample period, its command limit, every coefficient
as a value with its unit, and the conversion to the firmware's integer units where the firmware
uses integers) on a node of its own, named in its specification. No coefficient is on an
interface node (design standards §3); the node restates the sample period and command limit, each
with the interface or sizing node it comes from. The firmware's criteria compare its code with
that node as merged.

Where the issued specification does fix the controller's form and that form cannot meet a
criterion, the work does not substitute another: it reports the shortfall with its evidence, and
the least structure that would meet it, computed the same way and labelled as evidence for a fix,
for a person to decide.

**Judgement-only** — no check in the gate computes a loop's margins, and none reads a controller's
form; the delivered margins are read by review against the recorded frequency responses (skill,
"recording a simulation's output as series records").
