# Control — standards

> **Status: DRAFT candidate, staged for review — not promoted.** Researched and drafted by the
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

**For a linear-quadratic regulator with full state feedback**, tolerance to at least a 50% gain
reduction (−6 dB) with unbounded tolerance to a gain increase, and at least 60° of phase margin in
either direction, are *provable* properties of the optimal regulator itself, not a design target —
a mathematical guarantee, not a convention. **This is two separate results, correctly attributed,
not one paper covering both:** the positive guarantee is Safonov & Athans's extension of the
original (scalar) result to the multivariable case [M. G. Safonov and M. Athans, "Gain and phase
margin for multiloop LQG regulators," *IEEE Transactions on Automatic Control*, vol. 22, no. 2,
pp. 173–179, Apr. 1977]. It is *not* Doyle 1978's own result — Doyle's paper cites it as
background, verbatim: "the now well-known guarantee of 60° phase and 6 dB gain margin for such
controllers," crediting Safonov & Athans directly, before proving something else. What Doyle 1978
actually proves is the negative result this guarantee does **not** extend to: once a state
estimator (a Kalman filter) closes the loop with output feedback instead of full state feedback,
**no** margin is guaranteed at all [J. C. Doyle, "Guaranteed margins for LQG regulators," *IEEE
Transactions on Automatic Control*, vol. 23, no. 4, pp. 756–757, Aug. 1978,
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
10 ("Frequency Domain Analysis"), §10.3 "Stability Margins," Example 10.8; freely available at
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
5°–15° of phase margin with a filter damping ratio of 0.707. The authors state directly, a verbatim
quote and the only figure actually in the source: "this rule gives a Nyquist frequency that is
about 23 to 70 times higher than the crossover frequency" [B. Wittenmark, K.-E. Årzén, and
K. J. Åström, "Computer Control: An Overview," IFAC Professional Brief, International Federation of
Automatic Control, 2002, §"Selection of Sampling Interval and Antialiasing Filters" — freely
available via Lund University's publication repository]. **The following step is this draft's own
arithmetic, not the source's:** since the sampling frequency is by definition twice the Nyquist
frequency, the 23–70× Nyquist-to-crossover ratio implies a sampling-frequency-to-crossover ratio of
roughly **46 to 140 times** — arithmetically valid, but a number the cited authors never state, so
it is marked here as derived rather than quoted.

This is a *derivation under stated assumptions* (a specific phase-margin budget and filter damping),
not a universal law — state the assumptions actually used if a different phase-margin budget or
filter design changes the resulting ratio, rather than quoting 46–140× as if it applies unconditionally.
A lower multiple costs tracking performance and disturbance rejection; a higher one costs computation
without buying anything past what the phase-margin budget already required. The Nyquist rate itself
(twice the highest frequency of interest) is the theoretical floor below which information is lost
outright, not a design target on its own — the rule above is already well above it for exactly this
reason.

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
gate's check 4 already holds a declared source to what it can supply) and state the anti-windup
scheme used, or the specific reason none is needed (e.g. the actuator is never expected to
saturate in the stated operating region, per rule 1).

**Judgement-only** for the anti-windup design itself; the actuator's declared supply limit is
gate-checked the same way any other supply is (cross-domain standards §4).
