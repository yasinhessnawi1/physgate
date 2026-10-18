# Per-role results: a fixture experiment

Every rate is a count of trials with its denominator, the design's tasks times its trials; any outcome but a pass is a fail. Intervals are 95 %: Wilson for counts; bootstrap over tasks, 2000 draws, seed 7, for rates, paired differences and gaps.

## Control

> The gate checks no control or firmware performance: on these tasks its catches can only be units and magnitudes.

### Control, own tasks, visible

`control_visible`: tier visible, 3 tasks × 2 trials per arm.

| Arm | Trials passed · Wilson 95 % | Task-cluster bootstrap 95 % | Tasks passed in any of 2 · Wilson 95 % | Fail | Flaky | Unscored |
|---|---|---|---|---|---|---|
| harness (gate on) | 4/6 · 66.7 % [30.0, 90.3] | [50.0, 100.0] | 3/3 · 100.0 % [43.9, 100.0] | 2 | 0 | 0 |
| harness (gate observes) | 2/6 · 33.3 % [9.7, 70.0] | [0.0, 50.0] | 2/3 · 66.7 % [20.8, 93.9] | 4 | 0 | 0 |
| raw agent | 1/6 · 16.7 % [3.0, 56.4] | [0.0, 50.0] | 1/3 · 33.3 % [6.1, 79.2] | 5 | 0 | 0 |

| Paired, per task | Difference | Task-cluster bootstrap 95 % |
|---|---|---|
| harness (gate on) − raw agent | +50.0 points | [+50.0, +50.0] points |
| harness (gate on) − harness (gate observes) | +33.3 points | [+0.0, +50.0] points |
| harness (gate observes) − raw agent | +16.7 points | [+0.0, +50.0] points |

| Arm | Gate checks run | Gate: artefacts caught | Caught after the reviewer passed | Reviews | Reviews failed | Reviews blocked |
|---|---|---|---|---|---|---|
| harness (gate on) | 48 | 2 | 0 | 12 | 3 | 1 |
| harness (gate observes) | 48 | 2 | 2 | 12 | 3 | 1 |
| raw agent | — | — | — | — | — | — |

| Arm | Tokens | USD | USD per trial | Wall-clock | Median per trial |
|---|---|---|---|---|---|
| harness (gate on) | 5406030 | 24.60 (estimate at list price) | 4.10 | 3.21 h | 32.1 min |
| harness (gate observes) | 5106030 | 23.70 (estimate at list price) | 3.95 | 3.21 h | 32.1 min |
| raw agent | 2406030 | ≥ 7.20 (estimate at list price) | ≥ 1.20 | 1.11 h | 11.1 min |

- Trials whose loop never crossed unity gain, so that the phase margin is infinite and passes (python-control's convention): harness (gate on) 0/6; harness (gate observes) 0/6; raw agent 2/6.

### Control, own tasks, held out

`control_held_out`: tier held_out, 3 tasks × 2 trials per arm.

| Arm | Trials passed · Wilson 95 % | Task-cluster bootstrap 95 % | Tasks passed in any of 2 · Wilson 95 % | Fail | Flaky | Unscored |
|---|---|---|---|---|---|---|
| harness (gate on) | 3/6 · 50.0 % [18.8, 81.2] | [50.0, 50.0] | 3/3 · 100.0 % [43.9, 100.0] | 3 | 0 | 0 |
| harness (gate observes) | 1/6 · 16.7 % [3.0, 56.4] | [0.0, 50.0] | 1/3 · 33.3 % [6.1, 79.2] | 5 | 0 | 0 |
| raw agent | 1/6 · 16.7 % [3.0, 56.4] | [0.0, 50.0] | 1/3 · 33.3 % [6.1, 79.2] | 5 | 0 | 0 |

| Paired, per task | Difference | Task-cluster bootstrap 95 % |
|---|---|---|
| harness (gate on) − raw agent | +33.3 points | [+0.0, +50.0] points |
| harness (gate on) − harness (gate observes) | +33.3 points | [+0.0, +50.0] points |
| harness (gate observes) − raw agent | +0.0 points | [-50.0, +50.0] points |

| Arm | Gate checks run | Gate: artefacts caught | Caught after the reviewer passed | Reviews | Reviews failed | Reviews blocked |
|---|---|---|---|---|---|---|
| harness (gate on) | 48 | 2 | 0 | 12 | 3 | 1 |
| harness (gate observes) | 48 | 2 | 2 | 12 | 3 | 1 |
| raw agent | — | — | — | — | — | — |

| Arm | Tokens | USD | USD per trial | Wall-clock | Median per trial |
|---|---|---|---|---|---|
| harness (gate on) | 5406030 | 24.60 (estimate at list price) | 4.10 | 3.21 h | 32.1 min |
| harness (gate observes) | 5106030 | 23.70 (estimate at list price) | 3.95 | 3.21 h | 32.1 min |
| raw agent | 2406030 | ≥ 7.20 (estimate at list price) | ≥ 1.20 | 1.11 h | 11.1 min |

- Trials whose loop never crossed unity gain, so that the phase margin is infinite and passes (python-control's convention): harness (gate on) 0/6; harness (gate observes) 0/6; raw agent 2/6.

### A published benchmark's category

`benchmark_category`: tier external, 4 tasks × 2 trials per arm.

| Arm | Trials passed · Wilson 95 % | Task-cluster bootstrap 95 % | Tasks passed in any of 2 · Wilson 95 % | Fail | Flaky | Unscored |
|---|---|---|---|---|---|---|
| harness (gate on) | 6/8 · 75.0 % [40.9, 92.9] | [50.0, 100.0] | 4/4 · 100.0 % [51.0, 100.0] | 2 | 0 | 0 |
| raw agent | 1/8 · 12.5 % [2.2, 47.1] | [0.0, 37.5] | 1/4 · 25.0 % [4.6, 69.9] | 7 | 0 | 0 |

| Paired, per task | Difference | Task-cluster bootstrap 95 % |
|---|---|---|
| harness (gate on) − raw agent | +62.5 points | [+50.0, +87.5] points |

| Arm | Gate checks run | Gate: artefacts caught | Caught after the reviewer passed | Reviews | Reviews failed | Reviews blocked |
|---|---|---|---|---|---|---|
| harness (gate on) | 68 | 2 | 0 | 16 | 4 | 1 |
| raw agent | — | — | — | — | — | — |

| Arm | Tokens | USD | USD per trial | Wall-clock | Median per trial |
|---|---|---|---|---|---|
| harness (gate on) | 7212040 | 32.80 (estimate at list price) | 4.10 | 4.41 h | 33.1 min |
| raw agent | 3212040 | ≥ 9.60 (estimate at list price) | ≥ 1.20 | 1.54 h | 11.6 min |

- Trials whose loop never crossed unity gain, so that the phase margin is infinite and passes (python-control's convention): harness (gate on) 0/8; raw agent 2/8.
- The secondary view, the headline plus the gain margin and overshoot the benchmark's record holds; the record gives the gain margin no unit, so it is read both ways:

| Arm | Gain margin as a ratio | Gain margin in dB |
|---|---|---|
| harness (gate on) | 5/8 · 62.5 % [30.6, 86.3] | 6/8 · 75.0 % [40.9, 92.9] |
| raw agent | 1/8 · 12.5 % [2.2, 47.1] | 1/8 · 12.5 % [2.2, 47.1] |

### Reward-hacking gap: visible minus held-out

| Arm | Visible | Held-out | Gap | Task-cluster bootstrap 95 % |
|---|---|---|---|---|
| harness (gate on) | 4/6 · 66.7 % [30.0, 90.3] | 3/6 · 50.0 % [18.8, 81.2] | +16.7 points | [+0.0, +50.0] points |
| harness (gate observes) | 2/6 · 33.3 % [9.7, 70.0] | 1/6 · 16.7 % [3.0, 56.4] | +16.7 points | [-16.7, +50.0] points |
| raw agent | 1/6 · 16.7 % [3.0, 56.4] | 1/6 · 16.7 % [3.0, 56.4] | +0.0 points | [-33.3, +33.3] points |

## Firmware

> The gate checks no control or firmware performance: on these tasks its catches can only be units and magnitudes.
> Firmware timing: unchecked by the gate.

### Firmware, own tasks, visible

`firmware_visible`: tier visible, 2 tasks × 2 trials per arm.

| Arm | Trials passed · Wilson 95 % | Task-cluster bootstrap 95 % | Tasks passed in any of 2 · Wilson 95 % | Fail | Flaky | Unscored |
|---|---|---|---|---|---|---|
| harness (gate on) | 3/4 · 75.0 % [30.1, 95.4] | [50.0, 100.0] | 2/2 · 100.0 % [34.2, 100.0] | 0 | 1 | 0 |
| harness (gate observes) | 2/4 · 50.0 % [15.0, 85.0] | [50.0, 50.0] | 2/2 · 100.0 % [34.2, 100.0] | 2 | 0 | 0 |
| raw agent | 1/4 · 25.0 % [4.6, 69.9] | [0.0, 50.0] | 1/2 · 50.0 % [9.5, 90.5] | 2 | 0 | 1 |

| Paired, per task | Difference | Task-cluster bootstrap 95 % |
|---|---|---|
| harness (gate on) − raw agent | +50.0 points | [+50.0, +50.0] points |
| harness (gate on) − harness (gate observes) | +25.0 points | [+0.0, +50.0] points |
| harness (gate observes) − raw agent | +25.0 points | [+0.0, +50.0] points |

| Arm | Gate checks run | Gate: artefacts caught | Caught after the reviewer passed | Reviews | Reviews failed | Reviews blocked |
|---|---|---|---|---|---|---|
| harness (gate on) | 30 | 2 | 0 | 8 | 2 | 0 |
| harness (gate observes) | 30 | 2 | 2 | 8 | 2 | 0 |
| raw agent | — | — | — | — | — | — |

| Arm | Tokens | USD | USD per trial | Wall-clock | Median per trial |
|---|---|---|---|---|---|
| harness (gate on) | 3602020 | 16.40 (estimate at list price) | 4.10 | 2.07 h | 31.1 min |
| harness (gate observes) | 3402020 | 15.80 (estimate at list price) | 3.95 | 2.07 h | 31.1 min |
| raw agent | 1602020 | ≥ 4.80 (estimate at list price) | ≥ 1.20 | 0.70 h | 10.6 min |

- Firmware timing: unchecked by the gate.
- An unscored answer, one the machine ended before its guest started on the first attempt and on the retry, counts as a fail for its arm; so does a flaky one, whose three executions split.
- Executions whose sandbox runtime wrote to its error stream, an upper bound on the runtime failing mid-run, which scores as the answer's fail: harness (gate on) 0/12; harness (gate observes) 0/12; raw agent 2/10.
- Executions ended by one of the emulator's own limits, the answer's fail under the same limits for both arms: harness (gate on) 0/12; harness (gate observes) 1/12; raw agent 0/10.
- Attempts the machine ended before the guest started, each run once more: harness (gate on) 0; harness (gate observes) 0; raw agent 2.

### Firmware, own tasks, held out

`firmware_held_out`: tier held_out, 2 tasks × 2 trials per arm.

| Arm | Trials passed · Wilson 95 % | Task-cluster bootstrap 95 % | Tasks passed in any of 2 · Wilson 95 % | Fail | Flaky | Unscored |
|---|---|---|---|---|---|---|
| harness (gate on) | 2/4 · 50.0 % [15.0, 85.0] | [50.0, 50.0] | 2/2 · 100.0 % [34.2, 100.0] | 1 | 1 | 0 |
| harness (gate observes) | 1/4 · 25.0 % [4.6, 69.9] | [0.0, 50.0] | 1/2 · 50.0 % [9.5, 90.5] | 3 | 0 | 0 |
| raw agent | 1/4 · 25.0 % [4.6, 69.9] | [0.0, 50.0] | 1/2 · 50.0 % [9.5, 90.5] | 2 | 0 | 1 |

| Paired, per task | Difference | Task-cluster bootstrap 95 % |
|---|---|---|
| harness (gate on) − raw agent | +25.0 points | [+0.0, +50.0] points |
| harness (gate on) − harness (gate observes) | +25.0 points | [+0.0, +50.0] points |
| harness (gate observes) − raw agent | +0.0 points | [-50.0, +50.0] points |

| Arm | Gate checks run | Gate: artefacts caught | Caught after the reviewer passed | Reviews | Reviews failed | Reviews blocked |
|---|---|---|---|---|---|---|
| harness (gate on) | 30 | 2 | 0 | 8 | 2 | 0 |
| harness (gate observes) | 30 | 2 | 2 | 8 | 2 | 0 |
| raw agent | — | — | — | — | — | — |

| Arm | Tokens | USD | USD per trial | Wall-clock | Median per trial |
|---|---|---|---|---|---|
| harness (gate on) | 3602020 | 16.40 (estimate at list price) | 4.10 | 2.07 h | 31.1 min |
| harness (gate observes) | 3402020 | 15.80 (estimate at list price) | 3.95 | 2.07 h | 31.1 min |
| raw agent | 1602020 | ≥ 4.80 (estimate at list price) | ≥ 1.20 | 0.70 h | 10.6 min |

- Firmware timing: unchecked by the gate.
- An unscored answer, one the machine ended before its guest started on the first attempt and on the retry, counts as a fail for its arm; so does a flaky one, whose three executions split.
- Executions whose sandbox runtime wrote to its error stream, an upper bound on the runtime failing mid-run, which scores as the answer's fail: harness (gate on) 0/12; harness (gate observes) 0/12; raw agent 2/10.
- Executions ended by one of the emulator's own limits, the answer's fail under the same limits for both arms: harness (gate on) 0/12; harness (gate observes) 2/12; raw agent 0/10.
- Attempts the machine ended before the guest started, each run once more: harness (gate on) 0; harness (gate observes) 0; raw agent 2.

### Reward-hacking gap: visible minus held-out

| Arm | Visible | Held-out | Gap | Task-cluster bootstrap 95 % |
|---|---|---|---|---|
| harness (gate on) | 3/4 · 75.0 % [30.1, 95.4] | 2/4 · 50.0 % [15.0, 85.0] | +25.0 points | [+0.0, +50.0] points |
| harness (gate observes) | 2/4 · 50.0 % [15.0, 85.0] | 1/4 · 25.0 % [4.6, 69.9] | +25.0 points | [+0.0, +50.0] points |
| raw agent | 1/4 · 25.0 % [4.6, 69.9] | 1/4 · 25.0 % [4.6, 69.9] | +0.0 points | [-50.0, +50.0] points |

## Beside, not against: published numbers

### A published agent: 96.8 % of 50 tasks × 5 trials

- Source: a paper, Table 2.
- Ours on the same split (`benchmark_category`): harness (gate on) 6/8 · 75.0 % [40.9, 92.9]; raw agent 1/8 · 12.5 % [2.2, 47.1].
- Split: the whole category, as ours
- Protocol: five trials, its own checker in the loop
- Scorer: its own checker
- How theirs differs from ours:
  - its checker reads no gain margin
  - another model
- Warning: its tasks are public
