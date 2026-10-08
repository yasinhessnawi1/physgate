# Control module specification: balance loop for the Pololu Balboa 32U4

## 1. Purpose and scope

Design the balance controller for a Pololu Balboa 32U4 two-wheeled self-balancing robot, prove it
by analysis and simulation, and record the result as one design-state node.

The task is one loop: keep the robot upright and on station with a single command, the motor
voltage applied equally to both motors. Steering and the difference between the two motors are
out of scope (section 11).

You choose the controller structure and the tilt estimator. This specification gives the plant,
actuator, sensors, timing, operating region and the evidence expected, but no gains or margins
to copy. Every value below is an input: use it as given and change no parameter, limit, range,
disturbance or acceptance criterion. If you think one is wrong, say so in your summary and still
design against it.

## 2. What you deliver

1. The node JSON at `.physgate/proposals/control.loop_gain.json`, in the form of section 10.
2. Under `modules/control/`:
   - `controller.py`: the discrete-time controller and estimator exactly as they would run on the
     robot: every coefficient, the sample period, the voltage clamp, the conversion to PWM
     counts and any anti-windup logic, and nothing else;
   - analysis scripts that import `controller.py` (not a copy of its numbers) and print every
     result the acceptance criteria ask for;
   - `results.txt`: the printed output of the final run of those scripts.
3. A short summary in your final reply: the design route, the loop where margins were measured,
   and each acceptance criterion with the line of `results.txt` that shows it.

Only Python 3 with its standard library is available: write the matrix exponential, eigenvalues,
frequency sweep and integrator you need. Use explicit random seeds and print them.

## 3. The robot

The configuration Pololu's own balancing example is tuned for:

- Balboa 32U4 control board and chassis, with the bumper cage fitted;
- two 50:1 Micro Metal Gearmotors HPCB 6V with extended motor shaft (gear ratio 51.45:1);
- the plastic gear stage set to 45:21, so motor shaft to wheel is 51.45 x 45/21 = 110.25;
- two Pololu 80 x 10 mm wheels;
- six AA NiMH cells, nominal 7.2 V;
- level, hard ground; the wheels roll without slipping.

## 4. Plant model

### 4.1 Coordinates and equations of motion

Planar model, both wheels lumped.

- `phi`: wheel rotation angle relative to the ground, rad, positive rolling forward. Ground
  position `x = r * phi`.
- `theta`: body pitch from vertical, rad, positive leaning forward.
- `u`: the voltage applied to each motor, V, positive for forward wheel torque.

The motors are fixed to the body, so the motor shafts turn at `N * (dphi - dtheta)` relative to
the body. Neglecting friction, gear-mesh inertia and the 1/N part of the rotor's own body rate,
Lagrange's equations give:

```
(M_t*r^2 + J_w + J_r) * ddphi + (m_b*r*l*cos(theta) - J_r) * ddtheta
      - m_b*r*l*sin(theta) * dtheta^2 = tau

(m_b*r*l*cos(theta) - J_r) * ddphi + (J_b + m_b*l^2 + J_r) * ddtheta
      - m_b*g*l*sin(theta) = -tau

tau = (2*K_tau/R) * (u_applied - K_e * (dphi - dtheta))
```

with `M_t = m_b + m_w`, `J_r = 2 * N^2 * J_m` and `u_applied` the clamped, quantised voltage of
section 5. Linearise about upright at rest for design and margins. Use the nonlinear equations
for every time-domain run.

### 4.2 Motor model

Fit a linear DC-motor model to the gearmotor's two published 6 V operating points, per motor, at
the gearmotor output shaft: `R = 6 V / stall current`; torque constant `= stall torque / stall
current`; back-EMF constant `= (6 V - no-load current * R) / no-load speed`. Multiply both
constants by 45/21 to get `K_tau` and `K_e` at the wheel, and state the values. The driver brakes
(both low-side switches on) when the PWM output is low, so the motor sees the average voltage
`duty * V_batt` and its back-EMF acts through `R` at all times.

### 4.3 Parameters

| Symbol | Meaning | Value | Unit | Status |
|---|---|---|---|---|
| `g` | gravity | 9.81 | m/s^2 | fixed by this specification |
| `r` | wheel radius (80 mm diameter) | 0.040 | m | Pololu |
| `m_w` | both wheels with tyres (2 x 0.7 oz) | 0.0397 | kg | Pololu |
| `J_w` | both wheels about the axle, uniform discs | 3.18e-5 | kg*m^2 | fixed by this specification |
| `m_b` | body: robot without batteries 0.200 kg (Pololu) - `m_w` + six cells of 0.027 kg (Panasonic eneloop) | 0.3223 | kg | derived |
| `l` | axle to body centre of mass | 0.040 | m | fixed by this specification |
| `J_b` | body pitch inertia about its centre of mass | 2.9e-4 | kg*m^2 | fixed by this specification |
| `J_m` | rotor inertia of one motor | 2.0e-8 | kg*m^2 | fixed by this specification |
| `N` | motor shaft to wheel, 51.45 x 45/21 | 110.25 | 1 | Pololu |
| | gearmotor no-load speed at 6 V | 650 | rpm | Pololu |
| | gearmotor no-load current at 6 V | 0.15 | A | Pololu |
| | gearmotor stall current at 6 V | 1.5 | A | Pololu |
| | gearmotor stall torque at 6 V | 0.74 | kg*cm | Pololu (1 kg*cm = 0.0980665 N*m) |
| `V_batt` | battery voltage, 6 x 1.2 V | 7.2 | V | Pololu |

Pololu does not publish `l`, `J_b` or `J_m`, so this specification fixes them; the design must
hold over their ranges in section 7. As a check, `l` and `J_b` give a rigid-roll fall rate
`sqrt(m_b*g*l / (J_b + m_b*(l+r)^2 + m_w*r^2 + J_w))` of 7.19 rad/s (0.139 s), against Pololu's
measured 0.140 s (`ANGLE_RATE_RATIO = 140`).

## 5. Actuator

| Item | Value | Unit | Source |
|---|---|---|---|
| Motor driver | TI DRV8838 per motor, PWM/direction mode; brakes when the PWM input is low | | Pololu, TI |
| PWM frequency | 20 | kHz | Balboa32U4Motors.cpp |
| PWM counts at full duty | 400 | count | Balboa32U4Motors.cpp |
| Command limit | +/-300 of 400 counts (library default, turbo off) | count | Balboa32U4Motors.h, Balance.h |
| Voltage limit | +/-5.4 (= 300/400 x 7.2 V) | V | derived |
| Command resolution | 0.018 (= 7.2 V / 400) | V | derived |
| Voltage rate limit | 2.16e5 (10.8 V within one 50 us PWM period); does not bind at 10 ms, but declare and include it | V/s | derived from the PWM period |
| Driver current rating | 1.8 | A | TI DRV8838 datasheet |
| Motor electrical bandwidth | at least 1800 (`R / L`, `R` = 4.0 ohm, `L` at most 2.2 mH) | rad/s | Pololu forum, derived |

The firmware converts the voltage `u` to `round(u / 7.2 V * 400)` counts, clamped to +/-300
(nominal 7.2 V, no battery compensation). Stall current at 5.4 V is 1.35 A, below the driver
rating. The motors' back-EMF and rotor inertia stay in the plant model of section 4.

## 6. Sensing and timing

### 6.1 Sensors

**Gyro**: ST LSM6DS33 as in Pololu's balancing example (`CTRL2_G = 0b01011000`): 208 Hz output
data rate, +/-1000 deg/s, high-performance mode (power-on default). Pitch rate is the y axis.

| Item | Value | Unit |
|---|---|---|
| Sensitivity (one LSB) | 35 mdeg/s = 6.109e-4 rad/s | rad/s |
| Rate noise density | 7 mdeg/s/sqrt(Hz) = 1.222e-4 rad/s/sqrt(Hz) | rad/s/sqrt(Hz) |
| Digital low-pass cutoff at 208 Hz output rate | 66.7 Hz high-performance, 60.2 Hz normal mode | Hz |
| Zero-rate level before calibration | +/-10 deg/s typical | deg/s |
| Zero-rate change with temperature | +/-0.05 deg/s per degree C typical | deg/s/K |

ST publishes the filter's cutoff, not its order: model it as a first-order low-pass at 60.2 Hz
(low-frequency group delay 2.64 ms). The firmware averages 100 readings at start-up to remove the
zero-rate offset; state how your estimator handles what remains.

**Accelerometer** (same chip, if your estimator uses it): +/-2 g, 1.66 kHz output rate,
0.061 mg per LSB, noise density 90 ug/sqrt(Hz), analogue anti-aliasing cutoff 400 Hz.

**Encoders**: on each motor shaft, 12 counts per motor revolution, interrupt-driven, no delay.
They measure the wheel's rotation relative to the body, `phi - theta`: 1323 counts per wheel
revolution, 4.749e-3 rad per count.

The fed-back measurements are the tilt rate `dtheta` and the encoder angle `phi - theta` (plus the
accelerometer if used). Neither `theta` nor `phi` is measured; your estimator is part of the loop.

### 6.2 Sample rate and delay budget

This specification fixes the sample rate at 100 Hz, `h` = 10 ms, the rate of Pololu's example
("The balancing code is all based on a 100 Hz update rate"). The firmware module is dispatched
after this one. Your node's `constrains` edge to `firmware.main_loop` carries this rate and the
requirements of requirement 12 to it: the firmware's main loop must run at 100 Hz and meet the
computation and I/O budget below.

| Part | Value | Basis |
|---|---|---|
| Computation and I/O, start of sensor read to PWM register write | 3 ms (a requirement on the firmware) | fixed by this specification |
| Age of the gyro sample when read | up to 4.81 ms (one 208 Hz period); use 4.81 ms | gyro and loop are not synchronised |
| Gyro low-pass filter | first-order, 60.2 Hz | section 6.1 |
| Zero-order hold | `h/2` = 5 ms | from `h` |
| Loop timing jitter | up to 1 ms late | Pololu's loop flags an update as delayed only past `UPDATE_TIME_MS + 1` ms |

The computation delay and the hold act on the input, so on every path; the gyro age and filter
act only on the gyro path. The jitter is not modelled: the delay margin must cover it. State
which parts of the budget your loop model contains.

### 6.3 Numerical representation

The controller runs on an ATmega32U4 in 32-bit IEEE floating point (Arduino `float`; `double` is
also 4 bytes there). Other quantisation: gyro LSB, encoder count, 0.018 V command step.

## 7. Design case and operating region

**Design case**: balance upright at rest and hold the starting wheel position (station keeping),
on level ground, at nominal battery voltage, with no payload.

**Operating region** that the design, its stated validity region and its runs must cover:

| Quantity | Range |
|---|---|
| Body tilt `theta` | -0.175 to +0.175 rad (+/-10 deg) |
| Ground speed `r * dphi` | -0.3 to +0.3 m/s |
| `l` | 0.030 to 0.050 m (`J_b` fixed at 2.9e-4 kg*m^2) |
| `J_m` | 1.0e-8 to 4.0e-8 kg*m^2 |

The five parameter cases are the nominal one and the four corners `(l, J_m)`: (0.030, 1.0e-8),
(0.030, 4.0e-8), (0.050, 1.0e-8), (0.050, 4.0e-8).

**Largest disturbance to withstand** (fixed by this specification): a push that raises `dtheta`
by 1.0 rad/s instantly, in either direction, leaving `phi`, `dphi` and `theta` unchanged.

**Reference step**: 0.10 m in the wheel-position set-point.

**Estimator at t = 0**: in every time-domain run the estimator starts at the true state just
before the run's push or step is applied.

## 8. Requirements

1. Derive the linearised plant for each parameter case and print its open-loop eigenvalues.
   State the unstable pole `p` in rad/s for each case.
2. Print, for each case, the transfer-function zeros from `u`:
   - for each fed-back measurement separately (tilt rate; encoder angle `phi - theta`;
     accelerometer if used): those in the open right half-plane, and separately those on the
     imaginary axis;
   - the zeros common to all fed-back measurements (the zeros of the column of transfer
     functions from `u` to all of them).

   Expect: the tilt-rate channel has a double zero at the origin; the encoder channel has a real
   pair at `+/-sqrt(m_b*g*l / (J_b + m_b*(l+r)^2 + m_w*r^2 + J_w))`, the fall rate of section
   4.3 (about 7.0 to 7.3 rad/s), which is smaller than `p`. Explain what each does to the loop as
   you have closed it. A system with several outputs has a zero only where all its outputs vanish
   together, so the common zeros are the plant's own (Skogestad and Postlethwaite, section 4.5.2).
3. State whether you designed in continuous or discrete time. Either way, all poles and margins
   are computed on the sampled loop: plant discretised with a zero-order hold at `h`, the
   computation delay, the gyro age and filter, and the estimator and controller exactly as in
   `controller.py`. For a continuous design, name the discretisation method.
4. Break the loop at the commanded voltage `u`, clamp removed, to measure margins, and say so
   where the margins are reported.
5. Report for each case: gain crossover frequency in rad/s, phase margin, upper and lower gain
   margins (ratio and dB), stability margin (shortest distance from the loop's Nyquist curve to
   -1), sensitivity and complementary sensitivity peaks, and delay margin.
6. Report the total loop delay (computation, gyro age and filter lag, `h/2`) and `p` times it.
   Then, on the sampled loop `L` of requirement 4 (negative-feedback sign convention), at every
   gain crossover `w_gc` (every frequency up to `pi/h` where `|L| = 1`), compute and print in rad:
   - `lag_p = 2*atan(p/w_gc)`, the lag of the unstable pole's all-pass factor;
   - `lag_d = w_gc * (3 ms + h/2)`, the lag of the delay common to every path;
   - `phase_rest = arg L(exp(i*w_gc*h)) + lag_p + lag_d`, with `arg L` taken in (-pi, pi]: the
     computed phase of everything else (controller, estimator, gyro age and filter,
     minimum-phase plant dynamics).

   Where `arg L` lies in (-pi, 0], the phase margin at that crossover is
   `pi + phase_rest - lag_p - lag_d`; show the arithmetic. Where it lies in (0, pi], report the
   phase margin there as `pi - arg L` (the angle from `L` to -1) and say so. The phase margin of
   the loop is the smallest over its crossovers.
7. Give, with a source for each, the bandwidths of: the motor with its driver; the gyro with its
   filter; and the sampling, taken as `f_s / 3` = 33.3 rad/s (Stein 2003: good fidelity at two
   to three samples per radian; take three). Compare each with the crossover and with `p`.
8. State the ratio of the sample rate to the crossover frequency and the product of `h` and the
   closed-loop natural frequency, and argue that 100 Hz is adequate for your loop.
9. If the controller has integral action, name its anti-windup scheme. If it has an observer,
   feed the observer the clamped voltage.
10. State the region where your linear model holds, as ranges with units; claim nothing outside.
11. Simulate the nonlinear model with the controller of `controller.py`, the clamp, command
    quantisation, the delays of section 6.2, the gyro filter, quantisation and noise, and the
    encoder quantisation, all in one model.
12. Put in the node's `requirements` what the firmware must meet: 100 Hz, the 3 ms computation
    and I/O budget, sensors read before computing and PWM written after, and the count
    conversion and clamp of section 5.
13. Print the poles of the controller (estimator and control law together, from measurements to
    `u`) and say whether the controller is stable.
14. Also state, as numbers or plain statements: the slope of `|L|` at each crossover, in decades
    of gain per decade of frequency; the delay shared by both measurement paths (3 ms + `h/2` =
    8 ms) as its own quantity (node quantity `loop_delay_common`), next to the total of
    requirement 6; how the open-loop pole at the origin (wheel angle) is treated in your
    analysis; whether any guaranteed-margin result applies to your design, and why or why not;
    and the coefficient word length and the quantisation steps (gyro, encoder, command) you
    assumed.

## 9. Allowance

This allowance is the only relaxation this specification grants.

**Allowance 1: ratio of available bandwidth to the unstable pole.** Stein (2003) gives as a rule
of thumb a factor of at least ten between available bandwidth and unstable pole. With the
sampling-limited 33.3 rad/s that is out of reach. This specification accepts a ratio of **at
least 3** between the smallest bandwidth of requirement 7 and `p`, in every case. Reason: Stein
reads the factor off one aircraft's sensitivity chart for its own performance goal; it is a rule
of thumb. This loop must meet criteria 2 to 4 on the full sampled loop instead, and Pololu's
example balances this robot at the same 100 Hz.

## 10. The node

Write exactly one node. Every quantity is `{value, unit, source, written_by}`, `written_by` =
`"control"`, with exactly the unit strings below. Values from this specification cite it (for
example "issued control specification, section 5"); computed values cite the script and the
line of `results.txt`. Keep gains, matrices and per-case tables in `modules/control/`.

```
{
  "id": "control.loop_gain",
  "kind": "component",
  "domain": "control",
  "owner_role": "control",
  "quantities": {
    "sample_rate": {"unit": "Hz", ...},
    "sample_period": {"unit": "s", ...},
    "unstable_pole": {"unit": "rad/s", ...},
    "gain_crossover_frequency": {"unit": "rad/s", ...},
    "phase_margin": {"unit": "rad", ...},
    "gain_margin_upper": {"unit": "dimensionless", ...},
    "gain_margin_lower": {"unit": "dimensionless", ...},
    "stability_margin": {"unit": "dimensionless", ...},
    "sensitivity_peak": {"unit": "dimensionless", ...},
    "complementary_sensitivity_peak": {"unit": "dimensionless", ...},
    "loop_delay_total": {"unit": "s", ...},
    "loop_delay_common": {"unit": "s", ...},
    "delay_margin": {"unit": "s", ...},
    "actuator_voltage_limit": {"unit": "V", ...},
    "actuator_voltage_rate_limit": {"unit": "V/s", ...},
    "available_bandwidth": {"unit": "rad/s", ...}
  },
  "requirements": ["...what the firmware must meet (requirement 12)..."],
  "constrains": ["firmware.main_loop"],
  "model": "plain-text summary: plant, estimator, controller structure, loop-breaking point",
  "geometry_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
  "updated": "<UTC time in ISO 8601, e.g. 2026-10-08T12:00:00Z>"
}
```

Report margins and peaks for the worst of the five cases (say which in the source text).
`sample_rate` is 100 Hz and `sample_period` 0.01 s.

## 11. Out of scope

Steering and the left/right difference loop; standing up and the start and stop logic; battery
compensation and discharge; motor friction; wheel slip; the firmware code itself.

## Acceptance criteria

Each criterion is met only by printed output in the session or a file in `modules/control/`
produced by the final version of the code. A statement in the summary is not evidence.

1. **Plant, unstable pole and zeros.** The open-loop eigenvalues of the linearised plant of
   section 4 are printed for all five cases, with `p` stated for each. The zeros of
   requirement 2 are printed, per measurement and common to all; the common ones include none in
   the closed right half-plane.
2. **Closed-loop stability.** For all five cases, every eigenvalue of the closed-loop state
   matrix of the sampled loop (plant, delay states, gyro filter, estimator and controller
   together) is printed and has magnitude strictly below 1. The controller poles of
   requirement 13 are printed.
3. **Stability margins.** On the loop of criterion 2, broken at `u`, for all five cases: phase
   margin at least 30 deg (0.524 rad); upper gain margin at least 2 (6.0 dB), or none; lower gain
   margin at most 0.5 (-6.0 dB); stability margin at least 0.5 (sensitivity peak at most 2);
   complementary sensitivity peak at most 2. Each value comes from a computation shown in the
   session.
4. **Unstable pole and delay.** The total loop delay is stated with its parts, and `p` times it
   is below 0.5 in every case. The computed delay margin exceeds the part of the delay budget
   left out of the loop model, the 1 ms jitter included. The three phases of requirement 6 are
   printed for every crossover in every case; at each crossover where `arg L` lies in (-pi, 0],
   `pi + phase_rest - lag_p - lag_d` equals the phase margin there to within 0.01 rad; and the
   smallest phase margin over the crossovers is the one judged in criterion 3.
5. **Bandwidths.** The three bandwidths of requirement 7 are given with sources. Each is above the
   crossover frequency, or that element's dynamics are in the loop of criteria 2 and 3. The
   smallest is at least 3 times `p` in every case (Allowance 1).
6. **Saturation.** `controller.py` clamps the command to +/-300 counts (+/-5.4 V), and every
   simulation applies that clamp and the voltage rate limit of section 5. At least one
   simulation holds the command in the clamp for at least 5 consecutive samples and, if the
   controller has an integrator or an observer, shows its state staying bounded meanwhile. That
   run may start outside the operating region (for example from a larger push), and its
   estimator starts as section 7 says.
7. **Step and disturbance.** In the nonlinear simulation of requirement 11, at the nominal
   parameters: after the 0.10 m set-point step, the ground position is within 0.01 m of the new
   set-point by 5 s and stays there, with `|theta|` within 0.175 rad throughout; after the
   1.0 rad/s push from rest, the robot recovers (as defined in criterion 8).
8. **Recovery from the edges of the region.** For each of the five cases, the nonlinear
   simulation starts from each edge in turn (`theta` = +0.175 and -0.175 rad at rest; ground
   speed +0.3 and -0.3 m/s upright), with the 1.0 rad/s push applied at t = 0, once in each
   direction (40 runs). Every run recovers: by t = 5 s, `|theta|` is below 0.0175 rad and
   `|r * dphi|` below 0.05 m/s, and both stay there to the end of a 10 s run.
9. **Noise and quantisation.** The simulation of criterion 7 includes gyro noise and
   quantisation, encoder quantisation and command quantisation, with the seed printed. At rest
   for 10 s, the root-mean-square command is below 0.54 V (10 % of the limit). The eigenvalues of
   criterion 2, recomputed with the controller and estimator coefficients rounded to 32-bit
   floating point, are still inside the unit circle, and their largest deviation from the
   unrounded eigenvalues is printed and lies within a tolerance you state beforehand.
10. **Same loop everywhere.** The analysis and simulations import their coefficients, sample
    period and clamp from `controller.py`; its sample period is 0.01 s.
11. **Node.** The node of section 10 is valid JSON with every listed quantity, each with a value,
    the listed unit, a source and `written_by`; `constrains` is `["firmware.main_loop"]`; and
    `requirements` carries the firmware requirements of requirement 12.
