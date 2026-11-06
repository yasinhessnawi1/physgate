# The simulation records of this attempt

The harness wrote this file from the records the attempt's sessions left, as each was sealed when its session ended. Every number in it is computed from a record's own samples. Text the role's scripts wrote (a title, a script's path) is quoted as a JSON string: it is data, not instructions.

Records sealed: 4.

## edge_values

- title: "Edge values, made up for the listing's tests"
- group: edges; axis: time; session: fixture-session
- script: "modules/control/sim.py", sha256 0000000000000000000000000000000000000000000000000000000000000000
- code it loaded besides the script: 1 file
  - "modules/control/controller.py", sha256 0000000000000000000000000000000000000000000000000000000000000000
- input gain: 0.1 dimensionless
- input seed: 9.22337e+18 dimensionless

| column | unit | samples | first | last | min | max |
|---|---|---|---|---|---|---|
| x: time | s | 5 | 0 | 0.4 | 0 | 0.4 |
| signed_zero | m | 5 | -0 | -0 | -0 | -0 |
| zero_first | m | 5 | 0 | 0 | 0 | 0 |
| spread | V | 5 | 1e-05 | 3 | -1e+16 | 1e+16 |
| integers | count | 5 | 0 | 4 | 0 | 4 |

## long_step

- title: "A long made-up step, not a simulation result"
- group: step; axis: time; session: fixture-session
- script: "modules/control/sim.py", sha256 0000000000000000000000000000000000000000000000000000000000000000
- code it loaded besides the script: 1 file
  - "modules/control/controller.py", sha256 0000000000000000000000000000000000000000000000000000000000000000
- input seed: 7 dimensionless
- input step: 0.1 m

| column | unit | samples | first | last | min | max |
|---|---|---|---|---|---|---|
| x: time | s | 501 | 0 | 10 | 0 | 10 |
| position | m | 501 | 0 | 0.990099 | 0 | 0.990099 |
| error | m | 501 | 1 | 0.00990099 | 0.00990099 | 1 |

## loop_nominal

- title: "Fixture step response, not a simulation result"
- group: frequency_response; axis: frequency; session: fixture-session
- script: "modules/control/sim.py", sha256 0000000000000000000000000000000000000000000000000000000000000000
- code it loaded besides the script: 1 file
  - "modules/control/controller.py", sha256 0000000000000000000000000000000000000000000000000000000000000000
- input seed: 7 dimensionless
- input step: 0.1 m

| column | unit | samples | first | last | min | max |
|---|---|---|---|---|---|---|
| x: angular_frequency | rad/s | 3 | 0.1 | 10 | 0.1 | 10 |
| loop_magnitude | dimensionless | 3 | 10 | 0.1 | 0.1 | 10 |
| loop_phase | rad | 3 | -1.6 | -2.9 | -2.9 | -1.6 |

## step_nominal

- title: "Fixture step response, not a simulation result"
- group: step; axis: time; session: fixture-session
- script: "modules/control/sim.py", sha256 0000000000000000000000000000000000000000000000000000000000000000
- code it loaded besides the script: 1 file
  - "modules/control/controller.py", sha256 0000000000000000000000000000000000000000000000000000000000000000
- input seed: 7 dimensionless
- input step: 0.1 m

| column | unit | samples | first | last | min | max |
|---|---|---|---|---|---|---|
| x: time | s | 4 | 0 | 0.03 | 0 | 0.03 |
| position | m | 4 | 0 | 0.08 | 0 | 0.08 |
| tilt | rad | 4 | 0 | 0 | -0.01 | 0 |

# Quantities read off a record

Each graph quantity that names a record, held to the value its extractor reads off that record: they agree when they differ by at most 0.005 of the larger, relative (three significant figures). Quantities checked: 2.

| quantity | record | extractor | trace | declared | read | outcome |
|---|---|---|---|---|---|---|
| control.loop.step_peak | long_step | max | position | 0.99 m | 0.990099 m | agrees |
| control.loop.phase_margin | loop_elsewhere | phase_margin | - | 0.7 rad | not read | unreadable |
