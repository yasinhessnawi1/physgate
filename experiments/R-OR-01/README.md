# R-OR-01 — how to run it

The pre-registration is `CRITERIA.md`. This file only says how the cycles are
driven and where their records go.

## The driver

`tests/integration/orchestrator/kill_cycles.py`, one invocation per arm:

| Arm | `--arm` | Machine | Needs |
|---|---|---|---|
| A, fake session | `fake` | laptop | nothing beyond `uv sync` |
| B, real binary, kill while a request is held | `real` | Linux server | `PHYSGATE_CLAUDE_BIN` = the pinned 2.1.272 binary |
| C, real binary, kill while the tool runs | `tool` | Linux server | the same |

```sh
uv sync
uv run python tests/integration/orchestrator/kill_cycles.py \
    --arm fake --seeds 21-30 --out <dir outside the repository>

export PHYSGATE_CLAUDE_BIN=<path to claude 2.1.272>
uv run python tests/integration/orchestrator/kill_cycles.py --arm real --seeds 21-30 --out <dir>
uv run python tests/integration/orchestrator/kill_cycles.py --arm tool --seeds 21-30 --out <dir>
```

Each invocation writes `<dir>/<arm>/results.json` (a summary and one record per
cycle), and prints the same records as JSON lines on standard output, which the
run keeps as the arm's log. Every cycle's run directory and target repository
stay under `<dir>/<arm>/seed-<k>/` for inspection.

The driver refuses to start, printing why, if the tree is not clean, if `src/`
is not `src/` at `5cb2a40`, if (arms B and C) the binary's sha256 is not the
pinned one, or if `<dir>/<arm>` already exists. It never calls a model: sessions
talk to a scripted endpoint on `127.0.0.1`, with a dummy key, and any other
credential in the environment is not passed on.

## On the server

The server runs a clone of the run's commit, made from a git bundle, in its own
directory; nothing is pushed:

```sh
git bundle create r-or-01.bundle HEAD          # on the laptop
scp r-or-01.bundle <server>:r-or-01/
git clone r-or-01.bundle src-<sha> && cd src-<sha> && uv sync   # on the server
```

## Evidence

- `evidence/shakedown/`: dry runs on seeds 901 and 902, before the registered
  cycles. Never counted.
- `evidence/registered/`: each arm's `results.json` and its log, copied from the
  machine that produced them unchanged, and `SHA256SUMS` over every file there.
  Server records are copied and committed before `RESULT.md` is written.
