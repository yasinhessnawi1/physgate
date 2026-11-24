# Control — standards

> Researched and drafted by an agent and approved by a person before use: every numeric threshold
> below is a widely corroborated convention or a provable result from the published control-systems
> literature, cited at first use, never a value chosen to make a fixture pass. Read
> `knowledge/cross/standards.md` first: this file does not repeat what it states.

## 1. State the plant model's validity region

A linear or linearized plant model, a small-signal model, or a fixed operating point is accurate
only near where it was derived. State the region explicitly in the module's spec (an angle range, a
load range, a speed range).

**Judgement-only** — no automated check evaluates model fidelity against the physical system.

## 2. A closed loop reports its stability margins, not "it converged in simulation"

**For a continuous-time linear-quadratic regulator with full state feedback** (all states measured,
`R` diagonal, loop broken at the plant input), tolerance to at least a 50% gain reduction (−6 dB)
with unbounded tolerance to a gain increase, and at least 60° of phase margin in either direction,
in each plant input channel, are *provable* properties of the optimal regulator itself, not a design
target [M. G. Safonov and M. Athans, "Gain and phase margin for multiloop LQG regulators," *IEEE
Transactions on Automatic Control*, vol. 22, no. 2, pp. 173–179, Apr. 1977]. They hold for the continuous-time loop [S. Skogestad
and I. Postlethwaite, *Multivariable Feedback Control*, Wiley, 2nd edition, 2005, §9.2.2]. **This draft's reading, not the source's:** they cover no sampled implementation; for
a discrete-time LQR, or a continuous design behind a zero-order hold or a computation delay,
measure the margins on the discrete loop. Doyle proves the negative
result: once a state estimator (a Kalman filter) closes the loop with output feedback
instead of full state feedback, **no** margin is guaranteed at all [J. C. Doyle, "Guaranteed
margins for LQG regulators," *IEEE Transactions on Automatic Control*, vol. 23, no. 4, pp. 756–757,
Aug. 1978, DOI: 10.1109/TAC.1978.1101812]: "modern LQG designers are obliged to test their margins
for each specific design". So with an estimator in the loop the margin is measured on that design,
not assumed from the LQR theorem.

**For any other design method** (classical loop-shaping, PID, pole placement without the LQR
structure), no such guarantee exists either. From a primary source: "reasonable values of the margins are phase margin φ_m = 30°–60°, gain margin
g_m = 2–5, and stability margin s_m = 0.5–0.8" [K. J. Åström and R. M. Murray, *Feedback Systems: An
Introduction for Scientists and Engineers*, Princeton University Press, 2nd edition, 2021, Chapter
10 ("Frequency Domain Analysis"), §10.3 "Stability Margins," p. 10-17, in the text following
Example 10.8]. **Gain and phase margins alone are not sufficient**: their Example 10.8 has a gain margin of 266
and a phase margin of 70° and is still highly oscillatory, because its **stability margin** `s_m`
(the shortest distance from the loop's Nyquist plot to the point −1) is only 0.27, under the
0.5–0.8 range. Report the stability margin alongside gain and phase margin where it can be
computed.

State which case applies (LQR's provable guarantee, or the practitioner target range for everything
else), and if a state estimator is in the loop, measure margins **on the loop that includes the
estimator**, not on the full-state-feedback loop alone.

**Judgement-only** — no closed-loop stability check exists in this gate.

## 3. A sampled/digital controller's sample rate is stated relative to its closed-loop bandwidth, and the ratio is argued, not defaulted

Choosing a sampling period by continuous-time arguments — approximating the hold circuit as a
half-sample time delay and budgeting how much phase margin an antialiasing filter and the hold are
allowed to cost a loop whose crossover frequency is `ω_c` — gives the rule of thumb `h·ω_c = 0.05`
to `0.14` (`h` the sampling period in seconds, `ω_c` in rad/s), from allowing the filter and hold together to
cost 5°–15° of phase margin (filter damping 0.707, gain 0.1 at the Nyquist frequency); the band is the source's eq. (36), and the authors add: "this rule gives a
Nyquist frequency that is about 23 to 70 times higher than the crossover frequency" [B. Wittenmark,
K.-E. Årzén, and K. J. Åström, "Computer Control: An Overview," IFAC Professional Brief, 2002,
§"Selection of Sampling Interval and Antialiasing Filters", eq. (36), via Lund University's
publication repository]. **This draft's own arithmetic, not the source's:** the sampling frequency
is twice the Nyquist frequency, so the ratio to crossover is roughly **46 to 140 times**
(*derived*).

This is a derivation under stated assumptions, not a universal law: state the assumptions used if
a different budget or filter changes the ratio, rather than quoting 46–140× unconditionally.
The Nyquist rate (twice the highest frequency of interest) is the floor, not a design target. For a
controller designed directly in discrete time the same brief gives `ω·h = 0.1` to `0.6`, `ω` the
desired closed-loop natural frequency [same brief, §"Sampling Period Selection"].

**Judgement-only.**

## 4. A PID controller's gains are derived from a stated method, not guessed

The Ziegler–Nichols closed-loop method gives a reproducible starting point from two measured
numbers — the ultimate gain `K_u` and ultimate period `P_u` at which the loop first sustains
constant-amplitude oscillation under proportional-only control — with the classic three-term
setting `Kp = 0.6 K_u`, integral time `Ti = 0.5 P_u`, derivative time `Td = 0.125 P_u`
[J. G. Ziegler and N. B. Nichols, "Optimum Settings for Automatic Controllers," *Transactions of the
ASME*, vol. 64, pp. 759–768, 1942]. It gives an aggressive, oscillatory ("quarter-amplitude decay") response and is a
**starting point**, not a finished tuning: state the method that produced the reported gains and
why, if it was not this one.
Neither Ziegler–Nichols experiment is available for a balancing robot's tilt loop (the step method
needs "the open loop unit step response", which diverges [Åström and Murray, *Feedback Systems*,
2nd edition, §11.3]): for the normalised inverted pendulum `1/(s² − 1)` [same book, Example 10.5]
proportional gain `k` gives `s² + (k − 1)`, unstable for k < 1 and undamped for every k > 1, so
there is no ultimate gain (*this draft's derivation*). Use it only on a stable inner loop (motor
speed).

**Judgement-only.**

## 5. An LQR design's Q/R weights are derived from a stated tolerance, not tuned blind

Bryson's rule sets the diagonal of the state-cost matrix `Q` and input-cost matrix `R` from the
largest deviation of each state or input considered acceptable: `Q_ii = 1 / (max acceptable
deviation of state i)²`, `R_jj = 1 / (max acceptable value of input j)²` —
[A. E. Bryson Jr. and Y.-C. Ho, *Applied Optimal Control: Optimization, Estimation, and Control*,
Hemisphere Publishing, 1975, as given in J. P. Hespanha's LQR/LQG lecture notes]. It is a starting point, not a proof that the design is correct: state the acceptable deviations that produced the weights, not only the final matrices.

**Judgement-only.**

## 6. Actuator limits are declared, and the design accounts for saturation

Declare the actuator's limits as part of the module's quantities (the
gate's check 4 covers declared draw against what a declared source can supply) and state the
anti-windup scheme used, or the specific reason none is needed (e.g. the actuator is never
expected to saturate in the stated operating region, per rule 1).

The time runs (cruise, the push, every run at an end) report each run's largest motor current,
`|V_applied − K_e·ω| / R` per motor, from the applied voltage (the duty times the brief's voltage where it fixes one, else the supply's top: sizing standards §7), `K_e` and `R` as sizing states them, `ω` on the shaft `K_e` is stated for, beside the driver's peak rating sizing
states. A controller that exceeds it says so, and what would avoid it (a bound on reversal), and relaxes no criterion of the brief for it. The reversal current is
sizing's open point, which control examines (sizing standards §7). Control records a conflict, with
its runs as the evidence, only where it shows that it cannot meet a criterion of the brief while
every run's largest current stays within the rating; it goes to a person from there.

**Judgement-only** for the anti-windup design itself; the actuator's declared supply limit is
gate-checked the same way any other supply is (cross-domain standards §4).

## 7. When the reference controller cannot meet the margins, add the least structure that can, and show its margins on the loop that runs

A brief or specification may cite a reference controller as a source of
numbers: a sample period, a command limit, a coefficient's scale. Unless the issued specification
fixes the controller's form, the form is control's decision, and a cited reference does not fix it
(design standards §7). When the work shows that the reference form cannot meet the specified
margins at any coefficients it tried (the set tried and the best result, printed), control may add
structure, the least that meets them:
- **a direct term on a measured rate** (the tilt rate from a gyro, added to the command): state
  feedback on a measured state, which adds phase lead at crossover without differentiating a noisy
  signal [Åström and Murray, *Feedback Systems*, 2nd edition, Ch. 7 "State Feedback", section
  "Stabilization by State Feedback"; first edition §6.2];
- **lead compensation**, a pole/zero pair that adds phase around crossover [same book, Ch. 12
  "Frequency Domain Design", section "Feedback Design via Loop Shaping"; first edition §11.4]. One
  lead section `(s/a + 1)/(s/b + 1)`, `b > a > 0`, adds at most `arcsin((b − a)/(b + a))` rad at
  `ω = √(ab)` (*derived*);
- **state feedback** on every state the firmware measures or estimates, with the weights from §5
  where it is an LQR design.

Three conditions hold whatever is added.

**The margins are those of the loop that runs, every delay included.** The loop's margins are
computed with each delay the implementation has: the time from sample to command, the age of each
sensor's reading at the sample, the delay of the sensor's own digital filter, and the hold (half a
sample at crossover, §3; or exactly, on the discrete loop). A pure delay `τ` leaves the gain
unchanged and subtracts `ω·τ` rad of phase at every `ω` (*derived*). The filter's delay is the plan's value (design standards §13); where
the plan gives none, control reads it from the maker's document or measures it, and says so. Where
only its cutoff `f_c` is given, a first-order low-pass adds `1/(2π·f_c)` at low frequency
(*derived*) and a higher order more, so the order assumed is
stated, with the range it implies. A margin from a model without its delays does not meet a margin criterion, and is not reported as the
design's.

**The margins hold across the stated spread.** Each plant parameter that is an estimate, a quantity
no maker publishes that the work had to estimate (a rotor inertia, a centre-of-mass height, a body
inertia, a friction the work itself estimated; one taken from the maker's no-load current is a
maker's figure, below), carries a range from where it was sourced (sizing standards §5, §8); so
does a range the brief states (a fall time's). **A range's ends are of three classes.** (1) An end with a basis other than a maker's tolerance is
judged: a tolerance the brief states, a spread measured on the part, or the spread of a named
comparable [JCGM 100:2008, §4.3.1]. (2) A maker's stated tolerance on a figure it publishes (a
no-load speed's ±20 %, a no-load current's ±50 %), quoted from the maker's document in the quantity's
source, is not an estimate (*this project's rule*, as in sizing standards §12): every criterion is
judged with the figure at its typical value, and the results at the tolerance's ends are computed
and recorded as a sensitivity, not judged; without that quote the range is an estimate, its ends class 1 only on a basis of their own. (3) A bound
that only limits what is physically possible (a point mass and a body's outline bound its pitch
inertia), with no source that states a tolerance or a spread for the quantity, is no end: nothing
says the value is near it, and no criterion is failed or blocked for it. The work states the numeric
range the design holds over. The range is the widest over which the design's criteria hold, found by a sweep whose record is named; it contains the nominal value, and no floor is set. The work lists the sources it searched for a tolerance or a spread (the brief, the maker's page or data sheet, the part's own documents). A narrow range is information for the person who settles the measurement, not a pass or a fail by itself. It asks for the measurement that settles
it and records the quantity as an estimate to be resolved (design standards §8). A quantity any
source states a tolerance or a spread for is never put in class 3, and a multiple of the nominal
("×2") is in no class. A body's pitch inertia: swung from a pivot at `d` from its centre of mass, period `T`, `I = T²·m·g·d/(4π²) − m·d²` (*derived*, the physical pendulum). Where the brief fixes a combination (a fall time fixes
the motors-off pole, which depends on the inertia and the centre-of-mass height together), the
quantities in it are not ranged alone: the range of one is stated along the combination, the others
solved so it holds across its tolerance (sizing standards §12), and an end with no solution inside
the body's stated geometry is no end. The margins are computed at the low end, the nominal value and
the high end of each range with a judged end (class 1), one at a time, with the others nominal; the smallest value of each
margin over those cases is the design's margin, the one compared with the criterion. This is the
parametric form of model uncertainty [same book, Ch. 13 "Robust Performance", sections "Modeling
Uncertainty" and "Stability in the Presence of Uncertainty"; first edition §12.1, §12.2]. A check
at points is not a proof between them: the work also prints a sweep across each range, one at a
time, and its smallest value is the design's where it is lower than the end points'. The work also
computes the margins at every combination of the ranges' ends and records them beside the design's;
they are not compared with the criterion, and a combination that misses is not a shortfall. *This
project's rule:* every range at its worst end at once assumes every estimate wrong together, which no basis states. A supply voltage a criterion of the brief pins is a condition, not an estimate, and is
held at that value.

**A criterion not met at an end.** Where a criterion is not met at an estimate's end with the values
the work was given, the work states, for each quantity another module owns (sizing's command limit,
a mass, a supply), the value it would need there and whether that value lies inside the bound its
owner stated (sizing standards §12 records one). This applies only to a criterion with a stated
bound: the push, with sizing standards §12's bound, §12's inputs and the delivered command limit, in
control's own plant at the end's values. Where the bound is 1 or more at an end where the law fails,
the shortfall is the law's. Where it is below 1 and a value owned upstream, inside its owner's
bound, would bring it to 1 or more, the shortfall is a request to that owner, not a conflict: the
work records it once in its module's record, with the criterion, each end, the value needed against
the value written (a command limit also against the full scale) and the owner's bound; the owner's
closing pass takes it up (sizing standards §11). Until it has, and this work has followed the new
value, the criterion is not met at those ends, request recorded, never met. Where no value
inside an owner's bound brings it to 1 (the value needed lies outside the bound, the owner states
none, or the bound is below 1 at the owner's own limit), the shortfall is the plant's: the work
records it once as a conflict in its module's record (as sizing standards §3 does), with the
criterion, each end, the value needed and the bound's numbers. Either way it delivers its law,
meeting every criterion it can, and changes no criterion, range or limit for it. A criterion that
fails only at a tolerance's end is recorded with that sensitivity, not as a request or a conflict.

**The law that firmware runs is written on control's own node.** Control writes the law in the form
the firmware will run (the update equation, its sample period, its command limit, the speed
reference it follows (the plan's speed command, value and unit), every coefficient as a value with
its unit, and the conversion to the firmware's integer units where the firmware uses integers) on a
node of its own, named in its specification. No coefficient is on an interface node (design
standards §3); the node restates the sample period and command limit, each with the interface or
sizing node it comes from. The firmware's criteria compare its code with that node as merged. The same law is stated as `law.json`
at the top of the control module's directory, in the form the skill gives.

Where the issued specification does fix the controller's form and that form cannot meet a
criterion, the work does not substitute another: it reports the shortfall with its evidence, and
the least structure that would meet it, computed the same way and labelled as evidence for a fix,
for a person to decide.

**Judgement-only** — no check in the gate computes a loop's margins, and none reads a controller's
form; the delivered margins are read by review against the recorded frequency responses (skill,
"recording a simulation's output as series records").
