# R-OR-01 — pre-registration

**Status:** frozen before any registered cycle ran.
**Written:** 2026-09-26
**Rule:** nothing in this file may change after the first metric is produced. If
a measurement turns out to be impossible as specified, that fact is recorded in
`RESULT.md` as a deviation, with its reason, and the criterion is scored as
failed rather than rewritten. An amendment is a new experiment (`R-OR-02`) that
cites this one; this file stays as it is.

> Git-tracked and public. `ARCH-nnn` and experiment IDs only.

---

## 1. Question

Can a run of the deterministic orchestrator (`ARCH-001`, `ARCH-030`) that is
killed mid-task be resumed with no state lost? This feeds the pre-registered
risk table's row "Session tooling cannot resume": *kill and resume ten
coding-agent sessions mid-task; write a session wrapper if fewer than nine
resume with no state loss.* The threshold, nine of ten, is the risk table's. It
is not set here and nothing in this experiment changes it.

## 2. What is under test

`physgate resume`, the orchestrator's own resume, as its code states it
(`src/physgate/orchestrator/loop.py`, `resume`):

> Take over a run a previous process left, then drive it.
>
> The interrupted attempt restarts at its checkpoint with a fresh session,
> never the binary's own resume, and keeps its attempt number.

Before anything else, a resume stops every session a killed orchestrator left
running, found from the pid and start time recorded when it was spawned, by
collecting the session's whole process tree by parent pid, sending the session
SIGTERM, and then SIGKILL to every collected process still alive
(`src/physgate/orchestrator/processes.py`, `stop_tree`).

- **Orchestrator code:** `src/physgate/` exactly as at commit `5cb2a40`. The
  registered cycles run from a later commit that changes only the harness and
  this directory; the driver checks that the `src/` tree at the run's commit is
  the `src/` tree of `5cb2a40` and refuses to run otherwise.
- **Harness:** `tests/integration/orchestrator/kill_cycles.py` and the scripted
  endpoint `tests/integration/orchestrator/scripted_endpoint.py`, at the run's
  commit. Their sha256 are stamped into every output.
- **Agent runtime (arms B and C):** Claude Code `2.1.272`, the linux-x64 release
  binary with sha256
  `d81396a668eb76fbddb49a2a5841f1b5d7af96b4c1f6500ced92f2c988f5bcd4`, as the
  release manifest lists it. Auto-update off (`DISABLE_AUTOUPDATER=1`). The
  driver records the binary's sha256 and refuses a mismatch.

## 3. The arms

Three arms, each with its own count out of ten, **reported separately and never
pooled.**

**A. Fake session.** The orchestrator with its real git plumbing, real graph
store, real change check and real merge; the session is a stand-in that pauses
0.5 s, writes its module file and its proposal into the worktree, and lets the
orchestrator commit. Kills are anchored on event lines (§5). Measures the
orchestrator's own resume, with no runtime underneath it.

**B. Real binary, kill while a request is held.** Each session is a real Claude
Code process under the hook layer's generated settings, talking to a scripted
local Messages endpoint that the harness serves. The kill lands while the
endpoint holds one of the session's requests open, so the binary is waiting on
the model (§5). Measures the resume against the runtime's real kill behaviour
when a session outlives its orchestrator.

**C. Real binary, kill while the session's tool process runs.** As B, except
that the endpoint answers the session's Bash request with a long-running command,
and the orchestrator is killed once that command's process is seen in the
session's process tree (§5). Measures the resume when the killed orchestrator
leaves a session with a live tool process under it.

Common to all three arms: a test gate that passes and a test reviewer, because
no physics gate or reviewer is registered yet; gate mode `on`. Pinned model
strings, recorded in each run's configuration: role `claude-sonnet-5`, reviewer
`claude-opus-5-5`, decomposition `claude-sonnet-5` (decomposition is outside the
kill window, and no decomposition request is made). Auth mode `api_key`, with a
dummy key.

**No model is called in any arm.** Arm A has no runtime. In arms B and C every
Messages request goes to the scripted endpoint on `127.0.0.1`; the driver
removes any other credential from the environment it passes on, and the
endpoint records, per request, whether any credential other than the dummy key
came with it. That count is reported per arm.

**Machines.** Arm A on the development laptop (macOS). Arms B and C on the Linux
server, from a clone of the run's commit. Host, load average and runtime version
are recorded with each arm.

## 4. Rules of fair play

- **R1 Fresh state.** Each cycle starts from a fresh run directory and a fresh
  target repository.
- **R2 Judged from the files.** Everything judged is read from the files and the
  process table after the resume, never from any process's memory.
- **R3 First honest version.** Neither the orchestrator nor the harness is
  changed after the first registered cycle's number is seen. The orchestrator
  code is never changed inside this experiment. If a defect of the *harness*
  (not the orchestrator) is found after a number is seen, it is recorded in
  `RESULT.md` as a deviation with its reason, every registered cycle of every
  arm is rerun at the corrected commit, and both runs are reported.
- **R4 A miss is not re-drawn.** A cycle whose kill did not land as §5 defines
  is a harness miss: it is reported as one, counted as not clean, and its seed
  is never replaced by another.
- **R5 Interrupted arm.** If an arm's run stops before writing its results (a
  machine or connection failure), its partial output is kept and reported, and
  the arm is rerun once, in full, on the same seeds and commit. A second
  interruption leaves that arm unmeasured, reported as such.
- **R6 Same workload.** All three arms run the same plan (§5). Each arm has its
  own kill anchor rule, fixed below.

## 5. Workload, generated by a seeded script

**Plan, every cycle, every arm.** One run of two subtasks (`s1`, `s2`), each in
its own module directory, each proposing one node owned by its role, plus one
interface node written at the run's start. No rejection is scripted, so every
subtask should be merged at attempt 1. In arms B and C every session follows the
same four-request script: read its specification; a Bash command that writes
its module file; write its proposal; stop.

**Seeds.** Registered: **21 to 30**, for each arm. Seeds 1 to 10 and 101 to 103
were used by earlier runs of this harness and are not reused. Shakedown: 901
and 902, run before the registered cycles and kept as shakedown evidence; they
are never counted.

**Reference run.** Each arm first runs the same workload once with no kill. Its
event-line count `T` and its journal payloads are what the cycles are compared
with.

**Kill anchor, arm A.** For seed `k`, `N = random.Random(40_000 + k).randint(4, T - 1)`.
The orchestrator process is sent SIGKILL as soon as its event log holds at
least `N` lines. The line count actually reached at the kill is recorded beside
`N`. The kill *landed* if the orchestrator was alive when the signal was sent
and the run had not finished (fewer than `T` lines).

**Kill anchor, arm B.** For seed `k`, `rng = random.Random(50_000 + k)` picks the
subtask (`rng.randrange(2)`, of the two in plan order) and the request
`r = rng.randint(1, 4)` of that subtask's first session. When the endpoint
receives request `r` of that session, it holds it open; the harness checks that
the session's recorded pid is alive with its recorded start time, sends the
orchestrator SIGKILL, and checks the pid again. The held request is released only
once the session is dead. The kill *landed mid-session* if the anchored request
was reached, the orchestrator was alive at the signal, and the session's pid was
alive with its recorded start time just before and just after the kill.

**Kill anchor, arm C.** For seed `k`, `rng = random.Random(60_000 + k)` picks the
subtask (`rng.randrange(2)`) and a delay `d = rng.randint(0, 20) / 10` seconds.
When the endpoint receives request 2 of that subtask's first session (the Bash
step), it answers with a long-running command instead of the scripted one: a
foreground shell loop that appends a timestamp line to a heartbeat file every
0.1 s, for at most about five minutes. The heartbeat file lies outside the
worktree and its path is unique to the cycle, so it marks the command's process.
The request is not held. The harness watches the session's process tree (by
parent pid, from the recorded session pid) until a process whose command line
carries the cycle's marker appears, waits `d`, checks the session and every
process then in its tree, sends the orchestrator SIGKILL, and checks them again.
The kill *landed mid-tool* if the served Bash response was reached, the
orchestrator was alive at the signal, the session's pid was alive with its
recorded start time just before and just after the kill, and a process carrying
the marker was alive, with the same start time, just before and just after the
kill. Arm C's anchor is fixed at request 2 because that is the script's only
Bash step.

*Measured on the server before this file was written, outside any cycle and
with no orchestrator:* on 2.1.272 the Bash tool's shell runs in a session and
process group of its own, with the command in its command line, and its
children are descendants of the binary by parent pid. So the tool is found by
walking the tree, and a check of the binary's own session group would not see
it; arm C checks the tool's processes by pid and start time (C1, points 10 and
11).

**Recorded per cycle.** Arm A: `T`, `N`, the line count at the kill. Arm B: the
subtask and `r`, when the request was held and the kill sent, the session's pid
and recorded start, its liveness just before and just after the kill, the number
of processes in its tree at the kill, and when it was seen dead. Arm C: the
subtask and `d`, when the Bash response was served, when the marker process was
first seen and when the kill was sent, every process in the session's tree at
the kill (pid, start time, whether it carries the marker), their liveness just
before and just after the kill, the heartbeat line count at the kill, and the
heartbeat's last line and size after the resume. All arms: torn bytes at the
kill, the resume's exit and printed step, and the events the resume wrote.

## 6. Measurements

### C1 Clean resume — boolean per cycle; the arm's count out of ten

A cycle is clean only if **all** of:

1. the kill landed as §5 defines it for the arm (arm A: landed; arm B:
   mid-session; arm C: mid-tool);
2. `physgate resume`, run as its own process through the command's code with
   the same registrations, exits 0 and prints the run's step as `done`;
3. every event line, task-ledger line and graph-journal record whole on disk at
   the kill is still present after the resume, byte for byte, as a prefix of its
   file;
4. the attempt count is unchanged: no subtask has an attempt beyond 1;
5. the graph journal holds each planned node written exactly once, with the same
   payloads as the reference run;
6. the run branch holds exactly one merge per subtask;
7. nothing is left running: every session the run recorded is marked ended, no
   recorded session's pid is alive with its recorded start time, and no process
   of any recorded session's own session group is alive.

**Arms B and C, additionally:**

8. `LeftoverStopped` is recorded, by the resume, exactly once for the session
   that was alive at the kill;
9. a fresh session, not the killed one, completes on the same subtask with
   attempt number 1, so no attempt is charged for the kill.

**Arm C, additionally (the tool's processes are gone, and wrote nothing after
the stop):**

10. every process in the session's tree at the kill (the binary, the tool's
    shell and its children) is gone after the resume: no such pid is alive with
    its recorded start time;
11. no process on the machine carries the cycle's marker after the resume;
12. no heartbeat line is stamped later than the resume's `LeftoverStopped` event
    for the killed session;
13. the heartbeat file's size is the same at the resume's exit and three seconds
    later.

A cycle that is not clean is reported with every point that failed.

### C2 Resume outcome per cycle — recorded, not scored

The event lines the resume wrote: sessions stopped as leftovers (and how many of
their processes needed SIGKILL), the checkpoint the attempt resumed at,
incidents, infrastructure outcomes.

### C3 Harness misses — counted per arm, not scored separately

Each is also a not-clean cycle under C1, point 1.

## 7. Acceptance

For **each arm separately**, the resume holds if **at least nine of ten**
registered cycles are clean (C1). Fewer than nine clean in an arm means the risk
row's kill criterion has fired for that arm, and a session wrapper becomes a new
task. That is reported as the result. It is not fixed, retried or re-drawn inside
this experiment.

## 8. Out of scope, declared here so it cannot be claimed later

- A real model. Arms B and C show the runtime's process behaviour under a
  scripted endpoint, not a model's behaviour.
- Time to resume. Recorded where the output carries times; not scored.
- Machine crashes and power loss: a SIGKILL of a process shows process-crash
  durability only.
- A tool process that detached from its parent before the stop collected the
  tree. The hook layer refuses backgrounding in a session's shell; this
  experiment's command does not detach, so it does not test that case.
- The earlier runs of this harness on seeds 1 to 10, whose criteria were not
  committed before they ran. They are not this experiment's evidence and are
  not pooled with it.

## 8b. The driver — what it records and refuses

- It stamps into every output: the run's commit and whether the tree was clean,
  the sha256 of the harness and of the scripted endpoint, whether `src/` equals
  `src/` at `5cb2a40`, the binary's sha256 (arms B and C), the host, and the load
  average.
- It refuses to run if `src/` differs from `5cb2a40`, if the tree is not clean,
  if the binary's sha256 is not the pinned one (arms B and C), or if the output
  directory already exists.
- It seeds every kill anchor from the seed, per arm as §5 says. Nothing else in a
  cycle is random.
- Records produced on the server are copied into this directory's evidence
  unchanged, with their sha256, and committed before `RESULT.md` is written.

## 9. Provenance to attach to any summary

Written by an agent of the same model family that built the orchestrator, after
reading the earlier runs of this harness: 10/10 clean with a fake session and
10/10 clean with the real binary on a scripted endpoint, on seeds 1 to 10. In
that real-binary run every kill landed while the session waited on the model,
with one process in its tree; none landed while a tool ran. Arm C was added
because of that, so its question was formed with those results in hand. Arms A
and B repeat the earlier arms on fresh seeds under criteria committed first. The
scripted endpoint in place of a real model was chosen when the orchestrator's
plan was approved.
