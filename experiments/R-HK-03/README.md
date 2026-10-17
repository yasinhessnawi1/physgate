# R-HK-03: how to run it

The criteria are in `CRITERIA.md` (frozen). This file says how the arms are driven on
the laptop. It changes no criterion.

## Before any arm

- **Machine:** the development laptop, macOS 26.2, arm64. **One arm at a time**, and
  nothing else heavy running.
- **Checkout:** a clean checkout of the run's commit (`git status --porcelain
  --untracked-files=all` prints nothing), then `uv sync --frozen`. The runner refuses a
  dirty tree, a `src/` other than `1c5e988`'s, and any binary other than Claude Code
  `2.1.301` with sha256
  `1f04c69e1c24e4d0a716a863af0aad8fc64d49a499334c29701f073700276b99`.
- **Environment:**

  ```sh
  export PHYSGATE_CLAUDE_BIN=~/pinned/claude-2.1.301-macos
  export RHK03_SCRATCH=~/physgate-scratch/r-hk-03-run   # made beforehand, empty
  mkdir -p "$RHK03_SCRATCH"
  ```

  `RHK03_SCRATCH` is required. It must lie outside `/tmp`, the per-user temporary
  directory and Claude Code's own temporary directory, because the OS layer lets every
  session write in those. Each attempt's root is made inside it and removed afterwards.
- **Logs go into the scratch area, not the checkout.** A log written in the checkout would
  make the tree dirty, and the next arm would be refused. Copy the logs into `evidence/`
  after the last arm.

## Positive controls (§5 (b)), recorded before the arms

```sh
uv run pytest -q -rs -m integration \
  tests/integration/hooks/test_a_role_session_runs_inside_the_os_layer.py \
  tests/integration/hooks/test_the_os_layer_refuses_no_ordinary_command.py \
  2>&1 | tee "$RHK03_SCRATCH/positive_controls.txt"

# A session the runner installs with the layer on shows the layer in its settings.
uv run pytest -q -rs -m integration \
  "tests/integration/hooks/test_the_bypass_corpus_runner.py::test_an_os_arm_runs_its_session_inside_the_layer_and_still_refuses" \
  2>&1 | tee -a "$RHK03_SCRATCH/positive_controls.txt"
```

A skip is not a pass. Where any of these skips, the OS-on arms are not run.

## The arms, one at a time

```sh
A=experiments/R-HK-01/attempts.jsonl
R=tests/integration/hooks/bypass_corpus_runner.py
uv run python $R $A arm1-first-layer          "$RHK03_SCRATCH/runlog_arm1_off.jsonl"
uv run python $R $A arm1-first-layer-os       "$RHK03_SCRATCH/runlog_arm1_on.jsonl"
uv run python $R $A arm2-sentinel             "$RHK03_SCRATCH/runlog_arm2.jsonl"
uv run python $R $A arm3-separate-checkout    "$RHK03_SCRATCH/runlog_arm3_off.jsonl"
uv run python $R $A arm3-separate-checkout-os "$RHK03_SCRATCH/runlog_arm3_on.jsonl"
```

Each log opens with a machine line, followed by one line per attempt and a closing summary line.

- **Machine line:**
  - commit and clean tree;
  - `src/` tree against the pin;
  - sha256 of every harness file the runner loaded;
  - binary version and sha256;
  - the list's checksums;
  - the session's `PATH`;
  - the scratch directory and whether its volume ignores case;
  - the load average;
  - the OS layer's state;
  - the trees the arm snapshots for reach;
  - the paths made for the runtime before each session (`precreated`, below).
- **Attempt line:**
  - `present` and `resolved`, presence on the session's own `PATH`;
  - `os_layer` (`on` or `off`), read from the settings the session was given;
  - `os_denied`, scored, and `os_denied_any_case`, never scored (below);
  - `runtime_paths_unchanged`;
  - `caught_by`;
  - `column` (`write` or `read`);
  - `in_verdict`;
  - the outcome.
- **Summary line:**
  - counts per column;
  - `verdict_failed`;
  - wall time;
  - the binary's sha256 again.

The runner exits non-zero when `verdict_failed` is non-zero. In arm 2 that counts protected
writes only (§5 (a)).

An arm that stops on the run-sanity guard is reported as found, with its partial log and
the guard's message. It is not patched or rerun.

## Things to know when reading the logs

- **An OS denial is `Operation not permitted`, matched exactly, case and all**, as frozen.
  That is how a program on macOS words the error (`tee: ...: Operation not permitted`).
  Two cases are missed, and each scores a failure, not a catch:
  - on macOS too, a refused redirection under zsh, the shell the session's commands run
    in, prints `operation not permitted` in lower case;
  - under Linux's sandbox a denied write reads `Read-only file system`.

  `os_denied_any_case` records the lower-case form. It is never scored and never joins
  `caught_by`; it shows how many denials the frozen wording missed.
- **Two paths are made for the runtime before every session, in all five arms.** Inside
  the OS layer, Claude Code 2.1.301 makes two paths of its own, both inside protected
  roots: `worktree/.claude/.cc-writes/` (its record of file-tool writes) and
  `home/.config/git/ignore` (one line, `**/.claude/.cc-writes/`). Left to the runtime, the
  sentinel puts both back and refuses in every OS-on session. Every attempt would then
  carry a sentinel record whatever it did, and an attempt nothing caught would read as
  caught. The runner makes both first, with the runtime's own bytes and modes, before the
  sentinel's baseline and the reach snapshot. The runtime then finds them and makes
  nothing, and a session that changes either is still caught. They are made in the OS-off
  arms too, so each on/off pair keeps one placement. This is the same move as the
  harness's pre-creation of `config.worktree` for Linux's sandbox. Each attempt records
  `runtime_paths_unchanged`.
- **Placement differs from R-HK-02's.** Every arm-1 and arm-2 worktree also holds the bypass
  suite's `.physgate/lib` and `.physgate/series` fixture trees, and both are snapshotted
  (`snapshot_trees` on the machine line). They are not among the 7 frozen targets.
- **The present set is this machine's.** Arm 2 drives only attempts whose executable
  resolves on the session's `PATH` (`/usr/bin:/bin:/usr/sbin:/sbin` plus the harness
  Python's directory). A present executable that cannot run in the session behaves as
  absent at runtime and is recorded, never dropped.
