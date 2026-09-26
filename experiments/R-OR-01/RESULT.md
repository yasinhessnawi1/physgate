# R-OR-01 — result

> **Preface, 2026-09-26, added after an independent review. It changes no number;
> everything below it is as first committed.**
>
> - **What was killed.** Each cycle killed the **orchestrator**, not the coding-agent
>   session. In arms B and C the session survived the kill. The resume stopped it and
>   replaced it with a fresh session at the attempt's checkpoint. The session's own
>   progress is not carried over; it is redone. In arm A the stand-in session runs
>   inside the orchestrator process and dies with it.
> - **Why the verdict holds.** "No session wrapper is called for" holds because the
>   orchestrator *is* the session wrapper, by design (`CRITERIA.md` §2). The 10/10 counts
>   show that the orchestrator's **run** resumes with no project state lost. An
>   interrupted session is replaced at its checkpoint, not resumed.
> - **What was not measured.** A kill of the session process while its orchestrator
>   lives.
> - **Three points of scope the verdict does not state:**
>   - In arm C the records carry the liveness just before and after the kill for the
>     binary and the marker shell, but not for the third process in the tree (the
>     shell's `sleep 0.1` child). `CRITERIA.md` §5 promised it for every process in
>     the tree. No scored point depends on it, so "no deviation" below is slightly too
>     strong on this one record.
>   - C1 point 7 (nothing left running) cannot fail in arm A. The stand-in writes no
>     session record and runs inside the orchestrator process, so there is no recorded
>     session for the check to find.
>   - Torn lines were untested by construction, not by chance. In arms B and C every
>     kill lands while the orchestrator waits on a session, with nothing being written:
>     the event count at the kill is 7 or 27 in all twenty cycles. In arm A the kill
>     fires as soon as a newline count is reached (2 ms polling), so it lands just
>     after a whole line.
> - **The SIGKILL fallback, measured further by the reviewer.** A tool shell that
>   ignores TERM, HUP and INT (`trap '' TERM HUP INT`, reviewer's seeds 41–42, outside
>   the registered range) was still removed by the binary's own shutdown, with 0
>   processes needing SIGKILL. The stop came about 2.0 s after the kill instead of
>   about 0.56 s, and both cycles were clean. So on 2.1.272, under the hook layer, the
>   resume's SIGKILL of surviving collected processes is exercised only by its unit test
>   (`tests/unit/orchestrator/test_a_stop_leaves_nothing_running.py`), not by this
>   experiment.

**Pre-registration:** `CRITERIA.md` frozen at commit `c22c0b4` (2026-09-26),
sha256 `9c509385296d71ddcc1c558abd7ab713baf43ea3796784bc9f050afb8a26806e`.
The harness change the third arm needs is at `4dd5b1c`. The shakedown on seeds
901 and 902 is at `340b1d0`.
**Run:** all three arms from commit `340b1d0`, with a clean tree, on
2026-09-26. The driver checked that `src/` at that commit is `src/` at
`5cb2a40`. Harness sha256 `1ed2e137…b172469`, scripted endpoint sha256
`6f8a4f03…90d2b2`, identical in all three arms. The records are at `5d67c3a`.

---

## Verdict

**The criterion did not fire in any arm.** Every arm has 10/10 clean resumes,
with no harness miss. The risk table's threshold, nine of ten per arm, is met by
each arm separately. No session wrapper is called for.

| Arm | Kill anchored on | Kills landed | C3 harness misses | **C1 clean** |
|---|---|--:|--:|--:|
| A, fake session (laptop) | event lines | 10/10 | 0 | **10/10** |
| B, real binary, request held (server) | the endpoint, a held request | 10/10 mid-session | 0 | **10/10** |
| C, real binary, tool running (server) | the session's live tool process | 10/10 mid-tool | 0 | **10/10** |

Every one of the thirteen C1 points passed in every cycle where it applies:
points 1 to 7 in all arms, 8 and 9 in arms B and C, and 10 to 13 in arm C. No
Messages request carried a credential other than the dummy key: 0 of 116 in
arm B and 0 of 108 in arm C. The endpoint refused no step. No model was called.

## Arm A — fake session

- Reference run: `T = 38` event lines.
- Kills landed at event lines 13 to 36 (anchors `N` 12 to 35), with the
  orchestrator alive and the run unfinished each time.
- No file had a torn line at any kill (0 bytes past the last newline in the
  events, ledger and journal).
- C2: nine resumes restarted the interrupted attempt at `verify_reading`. For
  seed 26 the kill fell at line 36 of 38, between attempts, so no attempt was
  interrupted; the resume found none to restart and drove the run to done.

## Arm B — real binary, kill while a request is held

- Reference run: `T = 47`.
- The seeds drew request 1 once, request 2 three times, request 3 three times
  and request 4 three times. Five kills were in each subtask's first session.
- In every cycle the session's pid was alive with its recorded start time just
  before and just after the kill, with one process in its tree (the binary
  itself).
- The kill came 14 to 19 ms after the request was held. The session was seen
  dead 0.41 to 0.47 s after the kill, stopped by the resume.
- C2: in every cycle the resume recorded `LeftoverStopped` for the killed
  session, with 0 processes needing SIGKILL. It restarted the attempt at
  `resolve`, and a fresh session completed the subtask at attempt 1.
- `real.err` holds one BrokenPipe per cycle: the held request is answered after
  its session is gone, as designed.

## Arm C — real binary, kill while the tool process runs

- Reference run: `T = 47`.
- Seeded delays were 0.2 to 1.9 s. Five kills were in each subtask.
- At every kill the session's tree held three processes: the binary, the Bash
  tool's shell carrying the cycle's marker, and the shell's child (`sleep 0.1`,
  or one just exiting).
- The session, and the marker-carrying process, were each alive with the same
  start time just before and just after the kill.
- The heartbeat held 3 to 20 lines at the kill and kept growing after it: 3 to
  5 more lines, written by the orphaned tool, before the resume stopped the
  session 0.55 to 0.82 s after the kill. So each kill left a live, writing tool
  process behind, which is the case this arm exists for.
- After the resume, every cycle showed:
  - no process of the tree at the kill alive;
  - no process on the machine carrying the marker;
  - the heartbeat's last line 0.25 to 0.34 s *before* the `LeftoverStopped`
    stamp;
  - the heartbeat file the same size at the resume's exit and three seconds
    later.
- C2: `LeftoverStopped` once per cycle, with **0 processes needing SIGKILL**. It
  restarted at `resolve`, and a fresh session completed at attempt 1.

## What this shows, and what it does not

- **The orchestrator's resume holds in all three kill positions:**
  - between or inside orchestrator steps (A);
  - with a session left waiting on the model (B);
  - with a session left running a tool that keeps writing after its
    orchestrator is gone (C).

  No event, ledger or journal line was lost. No attempt was charged for a kill,
  no node was written twice, and nothing was left running.
- **Arm C's stop was always the SIGTERM step.** In all ten cycles, SIGTERM to
  the binary brought down its tool shell before the grace period ended, and the
  resume's SIGKILL of surviving collected processes had nothing to do. This run
  therefore does not exercise that SIGKILL path, which catches a tool process
  that survives its session's SIGTERM. It only shows the path was not needed
  here.
- **No kill tore a line.** Every file ended on a newline at every kill in all
  three arms. So point 3 (the prefix at the kill survives) was checked on whole
  lines only, never on a torn tail.
- **Out of scope, as declared:** a real model, time to resume, machine crashes,
  and a tool process that detaches from its parent.

## Deviations and notes

- **No deviation from `CRITERIA.md`.** Nothing under this directory was changed
  after the first registered number. The harness was not changed after the
  shakedown.
- **The binary's location on the server.** The server ran a byte-identical copy
  of the pinned binary, placed in the experiment's own directory:
  `claude_bin_sha256` in both server arms is
  `d81396a668eb76fbddb49a2a5841f1b5d7af96b4c1f6500ced92f2c988f5bcd4`, the
  pinned sha256, and the driver refuses any other. The original install's
  directory name is internal and would otherwise appear in every record. A
  first server shakedown that ran from the original path is kept off the
  repository for that reason; its counts were the same (2/2 and 2/2).
- **Machines.** The two machines did not share state. Arm A ran on the laptop
  (macOS 26.2, arm64), load average 21.0 at the start and 16.3 at the end,
  20:12:26 to 20:13:21 UTC. Arms B and C ran on the server (Linux 6.8.0,
  x86_64, glibc 2.39), load average 3.0 to 3.9, 20:12:18 to 20:16:59 UTC, B
  then C. No timing is scored, so the load is context only.

## Reproducing it

- `README.md` in this directory gives the commands per arm.
- The seeds are 21 to 30. Every kill anchor is a function of the seed alone
  (§5 of `CRITERIA.md`), and each record states the anchor it drew beside what
  the kill hit.
- Evidence in `evidence/registered/`, with `SHA256SUMS` over every file. The
  server-side sha256 of each file copied from the server matched:

| File | sha256 |
|---|---|
| `fake_results.json` | `3cf871ef38128aaed2d4fee1b7d45ab58ebb9e3169f9d01e84a9e2865b62a25d` |
| `real_results.json` | `6ad181f04a06dfebe4d53baa342af257a2207c781929fa072e184d0f64b404df` |
| `tool_results.json` | `bb4a53af52ee67647856c57a56286c0f676f519d5b02b473b3b598eb40ef2597` |
| `fake.log` | `50bf05bdbc61c43353ea70c78119fbd53f4c5d8856078113164004feb9f624c8` |
| `real.log` | `f5d6df7adeb0c17d8535d3412ec6e72ca00b3381532ac101ca6fa4bf9ad6359a` |
| `tool.log` | `8b3cb5eeb5f00db0aa1e1f8c2cc02d70cc5d8d75e1d95f7eadbe2ea77a419ab8` |

- Shakedown (never counted): `evidence/shakedown/`, 2/2 clean in each arm.
