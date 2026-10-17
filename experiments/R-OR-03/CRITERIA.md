# R-OR-03 — pre-registration

> Git-tracked and public. `ARCH-nnn` and experiment IDs only.

---

**Status:** frozen at this commit, before any runner change and before any number.
**Written:** 2026-10-17
**Rule:** nothing in this file may change after the first metric is produced. If
a measurement turns out to be impossible as specified, that fact is recorded in
`RESULT.md` as a deviation, with its reason, and the criterion is scored as
failed rather than rewritten. An amendment is a new experiment that cites this
one; this file stays as it is. Nothing under `experiments/R-OR-01/` is edited.

## 1. Question

R-OR-01 found 10/10 clean resumes in each of its three arms. Its verdict is
narrower than it reads, and its own preface says so:

- what was killed was always the **orchestrator**, never the session;
- **no kill tore a line**: every kill landed while nothing was being written;
- the resume's **SIGKILL of surviving processes was never needed**: in all
  twenty real-binary cycles the session's SIGTERM brought its tool down first;
- a tool that **detaches** from its parent was out of scope;
- it measured `src/` at `5cb2a40`. The orchestrator and state code have changed
  by about 6,100 lines since, including the change that makes a role session
  leave nothing running before the orchestrator's next git call (`8e08dbd`).

R-OR-03 asks the same question as R-OR-01, *can a run killed mid-task go on with
no state lost?*, at the current commit and in the four places R-OR-01 left
untested. It feeds the same row of the pre-registered risk table, "Session
tooling cannot resume", whose threshold (nine of ten) is the table's and is not
set here. The decisions on trial are `ARCH-001` (the deterministic orchestrator)
and `ARCH-030` (its loop stages and repair budget, which an infrastructure end
must not charge).

*Numbering.* R-OR-01's criteria name `R-OR-02` as the place for an amendment.
That ID was already planned for a different measurement, of how often repair
loops use up the three-attempt budget, so this amendment of R-OR-01 is R-OR-03.

## 2. What is under test

- **Orchestrator code:** `src/physgate/` exactly as at commit `1c5e988`, the
  `origin/master` when this file was frozen. The
  registered cycles run from a later commit that changes only the harness and
  `experiments/R-OR-03/`. The driver checks that `src/` at the run's commit is
  `src/` at the pinned commit and refuses to run otherwise.
- **Recovery paths on trial:**
  - `physgate resume` (`src/physgate/orchestrator/loop.py`, `resume`) and its
    stop of leftover sessions (`src/physgate/orchestrator/processes.py`,
    `stop_tree`), for arms A, B, C, E and F, as in R-OR-01;
  - the live orchestrator's handling of a session that dies under it: the stop
    and its confirmation from a fresh process table, the sentinel's check after
    the stop, the session's end classified as an infrastructure end, and an
    infrastructure retry that does not charge an attempt
    (`src/physgate/orchestrator/dispatch.py`, `src/physgate/orchestrator/loop.py`,
    `_infra_failed`; `src/physgate/orchestrator/budget.py`,
    `classify_session_end`), for arm D.
- **Harness:** `tests/integration/orchestrator/kill_cycles.py` and the scripted
  endpoint `tests/integration/orchestrator/scripted_endpoint.py`, at the run's
  commit. Their sha256, and the sha256 of every harness file the arms import,
  are stamped into every output.
- **Agent runtime (arms B, C, D1, D2 and F):** Claude Code `2.1.301`, the
  darwin-arm64 release binary with sha256
  `1f04c69e1c24e4d0a716a863af0aad8fc64d49a499334c29701f073700276b99`.
  Auto-update off (`DISABLE_AUTOUPDATER=1`). The driver records the binary's
  sha256 and refuses a mismatch.
- **OS layer:** every run goes through `physgate run` and
  `physgate resume`, which measure the OS layer on the machine and record it
  (`OsLayerChecked`). On the laptop with 2.1.301 it is expected to be present,
  so role sessions' shell commands run inside Seatbelt, as real dispatch runs
  them there. The state found is recorded per cycle. An arm whose cycles find
  the layer in different states is reported as such, not pooled. *R-OR-01 ran
  before the OS layer existed, so this is a difference from it, chosen because
  it is the configuration real runs use on this machine.*

## 3. The arms

Seven arms, each with its own count out of ten, **reported separately and never
pooled.** A, B and C repeat R-OR-01's arms. D1, D2, E and F are new.

**A. Fake session, orchestrator killed.** As R-OR-01's arm A: the orchestrator
with its real git plumbing, store, change check and merge; the session is a
stand-in that pauses 0.5 s, writes its module file and proposal, and lets the
orchestrator commit. Kills anchored on event lines.

**B. Real binary, orchestrator killed while a request is held.** As R-OR-01's
arm B.

**C. Real binary, orchestrator killed while the session's tool process runs.**
As R-OR-01's arm C.

**D1. Real binary, the session killed while a request is held; the orchestrator
lives.** As B, except that the harness sends
SIGKILL to the **session's binary** (its recorded pid, checked against its
recorded start time), not to the orchestrator. The orchestrator keeps running
and must recover the attempt itself. No `physgate resume` is run.

**D2. Real binary, the session killed while its tool process runs; the
orchestrator lives.** As C, except that the
session's binary is sent SIGKILL instead of the orchestrator. Measures whether a
tool process the dead session leaves is stopped by the live orchestrator before
its next git call.

**E. Fake session, orchestrator killed with a torn line on disk.** As A, except that the kill lands while one of
the three append-only files (the event log, the task ledger, the graph journal)
holds part of a line and no newline: the writer has written a seeded prefix of
the line, flushed and synced it, and is blocked. Measures that the resume drops
the torn tail and keeps every whole line before it.

**F. Real binary, orchestrator killed while a detached tool that ignores TERM
runs.** As C, except that the long-running
tool is a process that has left its shell's process group and session and
ignores TERM, HUP and INT, so that neither the session's own shutdown nor the
resume's SIGTERM can stop it, and only the resume's SIGKILL of surviving
collected processes can. Measures that fallback, which R-OR-01 never exercised.

Common to all arms, as R-OR-01: a test gate that passes and a test reviewer, gate
mode `on`. Pinned model strings, recorded in each run's configuration: role
`claude-sonnet-5`, reviewer `claude-opus-5-5`, decomposition `claude-sonnet-5`
(decomposition is outside the kill window, and no decomposition request is
made). Auth mode `api_key`, with a dummy key.

**No model is called in any arm.** Arms A and E have no runtime. In the other
arms every Messages request goes to the scripted endpoint on `127.0.0.1`; the
driver removes any other credential from the environment it passes on, and the
endpoint records, per request, whether any credential other than the dummy key
came with it. That count is reported per arm.

**Machine.** Every arm on the development laptop (macOS 26.2, arm64), from a
clean checkout of the run's commit, **one arm at a time**. Host, load average,
runtime version and OS-layer state are recorded with each arm.
*This differs from R-OR-01, whose arms B and C ran on the Linux server with
2.1.272. Re-running B and C here changes the machine, the runtime version and
the commit at once, so a difference between R-OR-01's B or C and R-OR-03's
cannot be put down to any one of the three.*

## 4. Rules of fair play

R-OR-01's rules R1 to R6 apply unchanged, with "three arms" read as "seven arms":

- **R1 Fresh state.** Each cycle starts from a fresh run directory and a fresh
  target repository.
- **R2 Judged from the files.** Everything judged is read from the files and the
  process table after the recovery, never from any process's memory.
- **R3 First honest version.** Neither the orchestrator nor the harness is
  changed after the first registered cycle's number is seen. The orchestrator
  code is never changed inside this experiment. A defect of the *harness* found
  after a number is seen is recorded in `RESULT.md` as a deviation with its
  reason, every registered cycle of every arm is rerun at the corrected commit,
  and both runs are reported.
- **R4 A miss is not re-drawn.** A cycle whose kill did not land as §5 defines is
  a harness miss: reported as one, counted as not clean, its seed never replaced.
- **R5 Interrupted arm.** If an arm's run stops before writing its results, its
  partial output is kept and reported, and the arm is rerun once, in full, on the
  same seeds and commit. A second interruption leaves that arm unmeasured.
- **R6 Same workload.** All arms run the same plan (§5). Each arm has its own
  kill anchor rule, fixed below.

## 5. Workload, generated by a seeded script

**Plan, every cycle, every arm.** As R-OR-01: one run of two subtasks (`s1`,
`s2`), each in its own module directory, each proposing one node owned by its
role, plus one interface node written at the run's start. No rejection is
scripted, so every subtask should be merged at attempt 1.

**The session's script, at this commit.** Every real session follows the same
script: read the always-loaded knowledge files for its role (three files at
`1c5e988`); read its specification; one Bash command that writes its module
file; write its proposal; stop. The number of requests, `R`, and the position of
the Bash step, `b`, are read from the script at the run's commit and recorded in
every output. At `1c5e988`, `R = 7` and `b = 5`. *R-OR-01's script had four
requests and its Bash step at 2; the knowledge reads were added after it ran.*

**Seeds.** Registered: **31 to 40**, for each arm. Seeds 1 to 10, 21 to 30, 41,
42 and 101 to 103 were used by earlier runs of this harness and are not reused.
Shakedown: **903 and 904**, run before the registered cycles and kept as
shakedown evidence; never counted.

**Reference run.** Each arm first runs the same workload once with no kill. Its
event-line count `T`, its journal payloads, and (arm E) the number and length of
the lines each file receives from the orchestrator's process, are what the
cycles are compared with.

**Kill anchor, arms A, B and C.** R-OR-01's rules, unchanged except for `R` and
`b`:

- **A:** `N = random.Random(40_000 + k).randint(4, T - 1)`; the orchestrator is
  sent SIGKILL as soon as its event log holds at least `N` lines.
- **B:** `rng = random.Random(50_000 + k)` picks the subtask (`rng.randrange(2)`)
  and the request `r = rng.randint(1, R)` of that subtask's first session; the
  endpoint holds request `r` open and the orchestrator is sent SIGKILL.
- **C:** `rng = random.Random(60_000 + k)` picks the subtask and a delay
  `d = rng.randint(0, 20) / 10` s; the endpoint answers request `b` of that
  subtask's first session with the long-running command; once the marked process
  is seen in the session's tree, the harness waits `d` and sends the orchestrator
  SIGKILL.

The landing rules are R-OR-01's: A *landed*, B *mid-session*, C *mid-tool*.

**The long-running command (arms C and D2).** As R-OR-01's: a foreground shell
loop that appends a time stamp line to a heartbeat file every 0.1 s, for at most
about five minutes; the file's path is unique to the cycle and marks the
command's process. Two things change, both because the OS layer is on and the
laptop runs macOS:

- the heartbeat file lies where a sandboxed shell may write (the session's own
  temporary directory), still outside the worktree, so nothing it writes is
  committed;
- each stamp carries sub-second time. macOS's `date` has no `%N`, so the stamp
  comes from a source that has one, checked in the shakedown.

**Kill anchor, arm D1.** For seed `k`,
`rng = random.Random(70_000 + k)` picks the subtask (`rng.randrange(2)`) and the
request `r = rng.randint(1, R)` of that subtask's first session. When the
endpoint receives request `r` of that session it holds it open; the harness
checks that the session's recorded pid is alive with its recorded start time and
that the orchestrator is alive, sends **the session's pid** SIGKILL, and checks
again. The held request is released once the session is dead. The kill *landed
mid-session* if the anchored request was reached, the session's pid was alive
with its recorded start time just before the kill and not alive within 5 s
after it, and the orchestrator was alive just before the kill, just after it,
and until it exited by itself.

**Kill anchor, arm D2.** For seed `k`,
`rng = random.Random(80_000 + k)` picks the subtask and a delay
`d = rng.randint(0, 20) / 10` s. When the endpoint receives request `b` of that
subtask's first session it answers with the long-running command. Once a process
carrying the cycle's marker is seen in the session's tree, the harness waits
`d`, records every process in the tree, and sends **the session's pid** SIGKILL.
The kill *landed mid-tool* if the served Bash response was reached; the session
was alive with its recorded start time just before the kill and not alive within
5 s after it; a marked process was alive with the same start time just before
and just after the kill; and the orchestrator was alive throughout, as in D1.

**Infrastructure retries, arm D only.** R-OR-01's rig sets an
empty infrastructure-retry schedule. With it, the first session the orchestrator
sees die ends the run as `infrastructure_exhausted`, and arm D could not show a
recovery at all. Arms D1 and D2 therefore run with a schedule of **one retry
after 1.0 s**, set in the run's configuration and recorded. Every other arm
keeps the empty schedule, so arms A, B and C stay R-OR-01's configuration.

**Kill anchor, arm E.** For seed `k`,
`rng = random.Random(90_000 + k)` draws:

- the file, `f = rng.randrange(3)`, from (event log, task ledger, graph journal);
- the write, `n = rng.randint(1, W_f)`, where `W_f` is the number of lines the
  orchestrator's process appended to file `f` in the reference run;
- the cut, `c = rng.randint(1, L)`, where `L` is the byte length, without its
  newline, of the line actually being written at that point in the cycle.

In the orchestrator's child process only, the harness wraps file `f`'s writer
handle, the way arm A replaces the session dispatcher: `src/` is unchanged. At
the `n`-th append to `f`, the wrapper writes the line's first `c` bytes and no
newline, flushes and syncs them, writes a marker file outside the run
directory, and blocks. When the marker appears, the harness sends the
orchestrator SIGKILL. The kill *landed torn* if the marker appeared, the
orchestrator was alive at the signal, and file `f` ended, on disk after the kill,
in exactly `c` bytes past its last newline. The torn bytes found in the other two
files are recorded.

**Kill anchor, arm F.** For seed `k`,
`rng = random.Random(100_000 + k)` picks the subtask and a delay
`d = rng.randint(0, 20) / 10` s. Before the cycle the harness writes a fixture
program at a path unique to the cycle (the marker), where the sandboxed shell
may read and run it, outside the worktree. When the endpoint receives request
`b` of that subtask's first session, it answers with a Bash command that runs the
fixture in the foreground. The fixture, once started:

1. records its pid, process group, session id and ignored signals to a side
   file beside it;
2. starts a new session, leaving its shell's process group and session;
3. ignores TERM, HUP and INT;
4. appends a stamp to its heartbeat file every 0.1 s, for at most about five
   minutes.

The shell waits for it, so it stays a descendant of the binary by parent pid
until the binary goes. Once a process carrying the marker is seen in the
session's tree, the harness waits `d`, records every process in the tree, and
sends the orchestrator SIGKILL. The kill *landed mid-detached-tool* if C's
landing conditions hold and, in addition, the marked process was in a process
group and a session other than the binary's and its shell's, with TERM among
its ignored signals, as its side file and the process table agree.

*Why the fixture is a program.* The hook layer refuses `setsid`, `nohup` and
backgrounding in a session's command line. A fixture that detaches from inside
a program is not seen by that check. This is the hook layer's own stated
residual for programs (its README), not a new bypass, and it writes only its
own heartbeat, outside every protected path. What is on trial in arm F is the
orchestrator's stop, not the hook layer's refusal.

**Recorded per cycle.** Everything R-OR-01 recorded for the matching arm (A for
E; B for D1; C for D2 and F), plus:

- all arms: the OS-layer state the command recorded, `R` and `b`;
- D1 and D2: the killed session's `session_ended` line (outcome, cause), every
  infrastructure retry line, the fresh session's id, whether the stop was
  confirmed, the sentinel's check after the stop, and the orchestrator's exit and
  printed step;
- E: `f`, `n`, `c`, `L`, the torn bytes in all three files at the kill, and the
  same file's size and last bytes after the resume;
- F: the fixture's side file, the process groups and sessions of every process in
  the tree at the kill, and how many processes the resume's stop needed SIGKILL
  for.

## 6. Measurements

### C1 Clean recovery: boolean per cycle; the arm's count out of ten

Points 1 to 13 are R-OR-01's. Where an arm needs a different wording, the
replacement is given under that arm and marked.

A cycle is clean only if **all** of the points that apply to its arm hold:

1. the kill landed as §5 defines it for the arm (A: landed; B, D1: mid-session;
   C, D2: mid-tool; E: torn; F: mid-detached-tool);
2. `physgate resume`, run as its own process through the command's code with the
   same registrations, exits 0 and prints the run's step as `done`;
3. every event line, task-ledger line and graph-journal record whole on disk at
   the kill is still present after the resume, byte for byte, as a prefix of its
   file;
4. the attempt count is unchanged: no subtask has an attempt beyond 1;
5. the graph journal holds each planned node written exactly once, with the same
   payloads as the reference run;
6. the run branch holds exactly one merge per subtask;
7. nothing is left running: every session the run recorded is marked ended, no
   recorded session's pid is alive with its recorded start time, and no process
   of any recorded session's own session is alive.

**Arms B, C and F, additionally:**

8. `LeftoverStopped` is recorded, by the resume, exactly once for the session
   that was alive at the kill;
9. a fresh session, not the killed one, completes on the same subtask with
   attempt number 1, so no attempt is charged for the kill.

**Arms C, D2 and F, additionally (the tool's processes are gone, and wrote
nothing after the stop):**

10. every process in the session's tree at the kill is gone after the recovery:
    no such pid is alive with its recorded start time;
11. no process on the machine carries the cycle's marker after the recovery;
12. no heartbeat line is stamped later than the stop (B, C and F: the resume's
    `LeftoverStopped` for the killed session; D2: see below);
13. the heartbeat file's size is the same at the recovery's exit and three
    seconds later.

**Arms D1 and D2: points 2, 3, 8, 9 and 12 replaced.** There is no resume in arm D; the orchestrator that was running at the
kill does the recovery, so:

- **2-D.** The orchestrator process that was running at the kill (`physgate run`)
  exits 0 by itself and prints the run's step as `done`. No `physgate resume` is
  run.
- **3-D.** Every event line, task-ledger line and graph-journal record whole on
  disk at the kill is still present after that process exits, byte for byte, as
  a prefix of its file.
- **8-D.** The killed session's end is recorded exactly once, as a
  `session_ended` line with outcome `infrastructure` (its cause is recorded, not
  scored), followed by exactly one `infra_retry_scheduled` line for the same
  subtask and attempt; and the run records no `attempt_rejected`, `escalated` or
  `halted` line.
- **9-D.** A fresh session, not the killed one, completes on the same subtask
  with attempt number 1, after that retry, so no attempt is charged for the
  kill.
- **12-D (arm D2).** No heartbeat line is stamped later than the killed
  session's `session_ended` line, which the orchestrator writes only after its
  stop of that session, and the sentinel's check after it, have settled.

Points 4 to 7 apply to D unchanged; points 10, 11 and 13 apply to D2 unchanged.

**Arm E, additionally.**

14. after the resume, file `f` holds, past the whole-line prefix it had at the
    kill, only whole lines: none of the `c` torn bytes is left as a line of its
    own or joined to another;
15. every line of all three files parses as a record of its file after the
    resume.

Point 7 cannot fail in arms A and E. The stand-in session writes no session
record and runs inside the orchestrator process, so there is no recorded session
for the check to find. Points 8 to 13 do not apply to them.

**Arm F, additionally.**

16. the SIGKILL fallback ran: the resume's `LeftoverStopped` for the killed
    session records at least one process that needed SIGKILL. A cycle in which
    it records none, with the fixture gone anyway, did not exercise what arm F
    exists for. It is counted as a harness miss under R4, not clean, and never
    re-drawn.

**How point 7 is read on macOS.** R-OR-01's harness read each process's session from `ps -o sess`,
which prints 0 for every process on macOS, so on the laptop the session part of
point 7 could never fail. R-OR-03's harness reads each process's session id
with `getsid`. Before the registered cycles, a positive control must find a
known process in a known session: a child started in a session of its own,
alive, must be reported as left running. If `getsid` cannot be read for other
processes on this machine, the harness falls back to the process group, records
that it did, and `RESULT.md` states that point 7 was checked on the process
group only. A process that left the group but stayed in the session would then
go unseen by that point.

A cycle that is not clean is reported with every point that failed.

### C2 Recovery outcome per cycle: recorded, not scored

As R-OR-01's C2, for every arm: the event lines the recovery wrote. These are
sessions stopped as leftovers and how many of their processes needed SIGKILL,
the checkpoint the attempt resumed at, incidents and infrastructure outcomes.
Arm D adds the session's cause and whether its stop was confirmed. Arm E adds
the torn-tail bytes each file's reader dropped at the resume.

### C3 Harness misses: counted per arm, not scored separately

Each is also a not-clean cycle under C1 point 1 (or, in arm F, point 16).

## 7. Acceptance

For **each arm separately**, recovery holds if **at least nine of ten**
registered cycles are clean (C1). Fewer than nine clean in an arm means the risk
row's kill criterion has fired for that arm, and a session wrapper, or the
change that arm points to, becomes a new task. That is reported as the result.
It is not fixed, retried or re-drawn inside this experiment.

## 8. Out of scope, declared here so it cannot be claimed later

- A real model. The arms show the orchestrator's and the runtime's process
  behaviour under a scripted endpoint.
- Time to recover. Recorded where the output carries times; not scored.
- Machine crashes and power loss. A SIGKILL shows process-crash durability only.
  A torn line in arm E is one the writer synced; a write the disk lost is not
  tested.
- **A tool that detaches *and* outlives its parent before the stop collects the
  tree.** Arm F keeps its fixture a descendant until the kill, so the stop can
  collect it. A process that leaves the group and is reparented before the
  collection is the stop's stated residual. Only the OS layer bounds what such a
  process can write; this experiment does not test that bound.
- Whether the hook layer refuses a detaching command. Arm F's detach is inside
  a program on purpose (§5).
- Linux. R-OR-01's arms B and C remain the Linux evidence, at `5cb2a40` and
  2.1.272.
- A torn line in any file other than the three named, and a torn line while a
  real session runs.
- The earlier runs of this harness on seeds outside 31 to 40, and the shakedown.

## 8b. The driver: what it records and refuses

- It stamps into every output:
  - the run's commit and whether the tree was clean;
  - the sha256 of the harness, of the scripted endpoint and of every harness
    file the arm imports (the arm E wrapper, the arm F fixture);
  - whether `src/` equals `src/` at the pinned commit;
  - the binary's sha256 (real-binary arms);
  - `R` and `b`;
  - the OS-layer state;
  - the host and the load average.
- It refuses to run if `src/` differs from the pinned commit, if the tree is not
  clean, if the binary's sha256 is not the pinned one (real-binary arms), if the
  output directory already exists, or if the point-7 positive control fails
  without the recorded fallback.
- It seeds every kill anchor from the seed, per arm as §5 says. Nothing else in
  a cycle is random.
- Its records are written on the laptop and copied into this directory's
  evidence unchanged, with `SHA256SUMS`, and committed before `RESULT.md` is
  written.

## 8c. Runner changes this needs (listed here, made in their own pull request after this file)

All in `tests/integration/orchestrator/`; none in `src/`. R-OR-01 stays
reproducible from its own commit (`340b1d0`), as its RESULT says.

1. **Pins.** `SRC_COMMIT` → the commit §2 names. `BINARY_SHA256` → the
   darwin-arm64 2.1.301 hash in §2. The comments naming 2.1.272 and linux-x64 are
   corrected.
2. **Session check on macOS (point 7).** `left_running` reads `ps -axo
   pid=,sess=,stat=`; `sess` is 0 for every process on macOS. Read the session id
   with `getsid`, behind the positive control in §6, with the recorded fallback
   to the process group.
3. **The Bash step's position.** `TOOL_REQUEST = 2` is now a knowledge read,
   because the session script gained three knowledge reads after R-OR-01. Derive
   `b` from the script, and record `R` and `b` in every output. Arm B's draw
   already uses the script's length.
4. **Heartbeat under the OS layer and on macOS.** Move the heartbeat file to
   where a sandboxed shell may write (the session's own temporary directory),
   outside the worktree. Stamp it with sub-second time from a source macOS has
   (`date +%s.%N` prints a literal `N` there). Make points 12 and 13 fail, not
   pass, when the heartbeat has no line that parses. Today a heartbeat with no
   parsable stamp passes point 12 by default.
5. **Arm D (`--arm session-request`, `--arm session-tool`).** Kill the session's
   pid instead of the orchestrator's. Keep the orchestrator running to its own
   exit, with no resume. Set the one-retry schedule of §5 in D's configuration
   only (the rig's `infra_retry_delays_s=()` would halt the run as
   `infrastructure_exhausted`). Score points 2-D, 3-D, 8-D, 9-D and 12-D.
6. **Arm E (`--arm torn`).** In the child process only, a wrapper over the chosen
   writer's handle that writes `c` bytes, syncs, writes the marker and blocks.
   The reference run counts each file's lines written by the orchestrator's
   process. Score points 14 and 15.
7. **Arm F (`--arm detached`).** The fixture program and its side file, placed
   where the sandboxed shell may run it. The landing checks on process group,
   session and ignored signals. Point 16 from `LeftoverStopped.killed`.
8. **Stamps.** OS-layer state per cycle from the run's `OsLayerChecked` line; the
   sha256 of every imported harness file.
9. **A README for R-OR-03** (`experiments/R-OR-03/README.md`): the commands per
   arm, on the laptop, one arm at a time.

## 9. Provenance to attach to any summary

Written by an agent of the same model family that built the orchestrator, after
reading R-OR-01's result, its preface, and an integrity review of the earlier
results that set out these four gaps. What the author knew before writing it:

- **Arm D2's expected outcome.** The stop's own documentation records a
  measurement on 2.1.272: the Bash tool runs each command in a process group of
  its own, and a SIGKILL of the session alone left its tool shell running,
  reparented to init. The live orchestrator's stop confirms the dead session's
  tree and process group, and the tool's shell is in neither. So the author
  expects D2 may fail points 7, 10, 11 or 12. This has not been re-measured on
  2.1.301 or under Seatbelt. D2 is kept because it is the case the risk row
  names: a coding-agent session killed mid-task.
- **Arm F's expected outcome.** The reviewer's extra cycles in R-OR-01 (seeds 41
  and 42) showed a tool that ignores TERM but does not detach is removed by the
  binary's own shutdown, so arm F's fixture also detaches.
- **Arms A, B, C.** R-OR-01 found 10/10 in each, at `5cb2a40` on 2.1.272, with B
  and C on Linux.

The scripted endpoint in place of a real model is kept from R-OR-01.

## 10. Order

1. This file is committed unchanged as `experiments/R-OR-03/CRITERIA.md`, before
   any runner change and before any number.
2. The runner changes in §8c, in their own pull request.
3. The shakedown (seeds 903 and 904, every arm, plus the point-7 positive
   control), kept as shakedown evidence.
4. The registered run, one arm at a time on the laptop, whose `RESULT.md` cites
   all three commits.

**Cost:** no model call in any arm; the scripted endpoint on `127.0.0.1` and a
dummy key. 70 registered cycles, 7 reference runs and 14 shakedown cycles, on
the laptop.
