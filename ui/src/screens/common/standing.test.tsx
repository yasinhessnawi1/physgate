// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { type RunStatus, runStatus } from "../../api/run";
import type { RunRead } from "../home/data";
import { activeRun } from "../home/data";
import { statusWords } from "../home/Home";
import { foldLedger, stateWords } from "../run-records/ledgerRows";
import { inProgress } from "./runs";
import { phaseOf, standingOf } from "../../words/standing";
import { runEnd, unsignedEnd } from "../home/runEnd";
import { dayAndMinute } from "../../words/runs";

const LAST = "2026-11-16T20:08:34.910143Z";
const MINUTE = 60;

/**
 * A run whose next step is attempt 1 of s1, whose log was last written ``silent`` seconds before
 * the server answered, by the server's clock, with ``bound`` the longest a living run goes without
 * a line after that one (``null`` where a stage with no bound of its own may be running).
 */
function attempting(silent: number | null, bound: number | null = 5400): RunStatus {
  return {
    kind: "attempt",
    subtask: "s1",
    halted: null,
    owedHalt: null,
    completion: { owner: false, modules: [] },
    waiting: [],
    superseded: {},
    lastLineAt: silent === null ? null : LAST,
    silentS: silent,
    silenceBoundS: bound,
  };
}

afterEach(() => {
  vi.useRealTimers();
});

describe("a run whose process is gone is never shown as running", () => {
  it("appears stopped when its log is silent past the bound after its last line and the margin", () => {
    const status = attempting(138 * MINUTE); // 2 h 18 min, past 90 min and half an hour more
    expect(phaseOf(status)).toBe("stopped");
    expect(inProgress(status)).toBe(false);
  });

  it("is going while the silence is within what a living run takes", () => {
    expect(phaseOf(attempting(10 * MINUTE))).toBe("going");
    expect(phaseOf(attempting(115 * MINUTE))).toBe("going");
    expect(inProgress(attempting(10 * MINUTE))).toBe(true);
  });

  it("claims nothing while a stage with no bound of its own may be running", () => {
    // The physics gate, the OS layer's start: the server sends no bound after their lines.
    expect(phaseOf(attempting(600 * MINUTE, null))).toBe("going");
    expect(phaseOf(attempting(10_000 * MINUTE, null))).toBe("going");
  });

  it("claims nothing where the last line is not sent", () => {
    expect(phaseOf(attempting(null))).toBe("going");
  });

  it("a run with short bounds reads stopped only past its own bound and the half hour", () => {
    // A 60 s session wall clock: a spawn's line, then 20 min of silence, is a session's end
    // still being settled; past 31 min, nothing has written.
    expect(phaseOf(attempting(20 * MINUTE, 60))).toBe("going");
    expect(phaseOf(attempting(32 * MINUTE, 60))).toBe("stopped");
  });

  it("the browser's clock is never read: a skewed clock changes nothing", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2030-01-01T00:00:00Z"));
    expect(phaseOf(attempting(10 * MINUTE))).toBe("going");
    vi.setSystemTime(new Date("2020-01-01T00:00:00Z"));
    expect(phaseOf(attempting(138 * MINUTE))).toBe("stopped");
  });

  it("is waiting for a person, never running, when its next step waits on a decision", () => {
    expect(phaseOf({ ...attempting(MINUTE), kind: "wait", subtask: null })).toBe("waiting-person");
    expect(phaseOf({ ...attempting(MINUTE), kind: "escalated", subtask: null })).toBe(
      "waiting-person",
    );
  });

  it("reads the last line's time, the server's clock and the bound from the route; the silence is theirs", () => {
    const raw = {
      next_step: { kind: "attempt", subtask_id: "s1", attempt: 1, point: "resolve" },
      halted: null,
      owed_halt: null,
      completion: { owner: false, modules: [] },
      waiting: [],
      superseded: {},
      last_line_at: LAST,
      server_now: "2026-11-16T22:26:35.410143Z",
    };
    const parsed = runStatus({ ...raw, silence_bound_s: 5400 });
    expect(parsed.lastLineAt).toBe(LAST);
    expect(parsed.silentS).toBe(8280.5);
    expect(parsed.silenceBoundS).toBe(5400);
    expect(runStatus({ ...raw, silence_bound_s: null }).silenceBoundS).toBeNull();
    expect(runStatus({ ...raw, server_now: null }).silentS).toBeNull();
  });
});

describe("the screens say a run appears stopped, as an inference with the last record's time", () => {
  const read = (status: RunStatus): RunRead =>
    ({
      run: { root: 0, name: "r", runId: "r", error: null },
      status: { ok: true, value: status },
      config: { ok: false, refusal: { error: "x" } },
      events: { ok: true, value: [] },
      queue: { ok: true, value: { open: [], decided: [] } },
    }) as unknown as RunRead;
  const since = dayAndMinute(LAST);

  it("the sentence names the last record's time and says the run appears to have stopped", () => {
    const standing = standingOf(attempting(138 * MINUTE), null);
    expect(standing.sentence).toBe(
      `No activity since ${since}. The run appears to have stopped; nothing has been recorded since.`,
    );
  });

  it("nothing is said as a fact that was not observed", () => {
    const standing = standingOf(attempting(138 * MINUTE), null);
    const said = `${standing.sentence ?? ""} ${standing.detail ?? ""}`;
    expect(said).not.toContain("nothing is running");
    expect(said).not.toContain("ended without recording why");
    expect(said).not.toContain("no process of it is running");
    expect(standing.detail ?? "").toContain("2 h 18 min");
  });

  it("Home's list says so, and never in progress", () => {
    const html = renderToStaticMarkup(<>{statusWords(read(attempting(138 * MINUTE)))}</>);
    expect(html).toContain(`No activity since ${since}. The run appears to have stopped`);
    expect(html).not.toContain("nothing is running");
    expect(html).not.toContain("In progress");
  });

  it("Home leads with no run still going when the only one appears stopped", () => {
    expect(activeRun([read(attempting(138 * MINUTE))])).toBeUndefined();
  });

  it("the ledger row says no activity since the last record, not that it is in progress", () => {
    const rows = foldLedger(
      [{ id: "s1", role: "firmware", attempts: 1, gate: null, review: null, mergeCommit: null }],
      { events: [], status: attempting(138 * MINUTE), queue: null, budget: 3 },
    );
    const words = rows[0] === undefined ? "" : stateWords(rows[0].state);
    expect(words).toBe(`No activity at attempt 1 since ${since}; the run appears to have stopped`);
  });
});

describe("a run that ended with a module that never ran names it", () => {
  const unrun: RunStatus = {
    ...attempting(MINUTE),
    kind: "unrun",
    subtask: null,
    neverRan: [
      {
        subtask: "fw-3d4e5f",
        why: "its designer drive-0a1b2c ended without a merge",
        ranWithout: ["el-4a5b6c"],
      },
    ],
  };

  it("reads as ended, not as going or waiting", () => {
    expect(phaseOf(unrun)).toBe("done");
    expect(inProgress(unrun)).toBe(false);
  });

  it("says which module never ran and why, and what merged without it", () => {
    const standing = standingOf(unrun, null);
    expect(standing.word).toBe("Ended");
    expect(standing.sentence).toBe(
      "Ended: the fw module never ran: its designer drive-0a1b2c ended without a merge.",
    );
    expect(standing.detail).toBe(
      "fw: its designer drive-0a1b2c ended without a merge; el merged without it",
    );
  });

  it("says that a module's ordered retry never ran, where that is what happened", () => {
    const retried: RunStatus = {
      ...unrun,
      neverRan: [
        {
          subtask: "fw-3d4e5f",
          why: "its ordered retry never ran: its designer drive-0a1b2c ended without a merge",
          ranWithout: [],
        },
      ],
    };
    expect(standingOf(retried, null).sentence).toBe(
      "Ended: the fw module's ordered retry never ran: its designer drive-0a1b2c ended without a merge.",
    );
  });

  it("is read from the route's never_ran list", () => {
    const read = runStatus({
      next_step: { kind: "unrun", subtask_id: null, attempt: null, point: null },
      halted: null,
      owed_halt: null,
      completion: { owner: false, modules: [] },
      never_ran: [{ subtask_id: "fw-3d4e5f", why: "its designer ended", ran_without: [] }],
    });
    expect(read.neverRan).toEqual([
      { subtask: "fw-3d4e5f", why: "its designer ended", ranWithout: [] },
    ]);
  });
});

describe("a halt on an incident says what the incident says", () => {
  const WAITS =
    "the run waits and no item is open to a person: fw is held on drive, which it reads from.";
  const halted: RunStatus = {
    ...attempting(MINUTE),
    kind: "halted",
    subtask: null,
    halted: {
      reason: "incident",
      detail: "waits_on_nothing",
      incident: { cause: "waits_on_nothing", detail: WAITS },
    },
  };

  it("shows what is held on what, beside the cause", () => {
    expect(phaseOf(halted)).toBe("halted");
    expect(standingOf(halted, null).detail).toBe(`incident: waits_on_nothing. ${WAITS}`);
  });

  it("shows the cause alone for a halt that rests on no incident line it can name", () => {
    const bare = { reason: "incident", detail: "waits_on_nothing" };
    expect(standingOf({ ...halted, halted: bare }, null).detail).toBe("incident: waits_on_nothing");
  });

  it("is read from the route's halt, with its incident", () => {
    const read = runStatus({
      next_step: { kind: "halted", subtask_id: null, attempt: null, point: null },
      halted: {
        seq: 9,
        reason: "incident",
        detail: "waits_on_nothing",
        incident: { cause: "waits_on_nothing", detail: WAITS },
      },
      owed_halt: null,
      completion: { owner: false, modules: [] },
    });
    expect(read.halted?.incident).toEqual({ cause: "waits_on_nothing", detail: WAITS });
    const none = runStatus({
      next_step: { kind: "halted", subtask_id: null, attempt: null, point: null },
      halted: { seq: 9, reason: "incident", detail: "no_progress", incident: null },
      owed_halt: null,
      completion: { owner: false, modules: [] },
    });
    expect(none.halted?.incident).toBeUndefined();
  });
});

describe("an escalated end that owes a sign-off names the module that never ran", () => {
  // As the route serves a run that acts: the sign-off is owed, and its item is decided or open.
  const escalated = (open: readonly string[]): RunStatus => ({
    ...attempting(MINUTE),
    kind: "escalated",
    subtask: null,
    acts: true,
    signaturesOwed: ["drive-0a1b2c"],
    signaturesOpenToDecide: open,
    endsOnSignaturesAlone: true,
    neverRan: [
      { subtask: "fw-3d4e5f", why: "its designer el-4a5b6c ended without a merge", ranWithout: [] },
    ],
  });
  const WORDS = "Also, the fw module never ran: fw: its designer el-4a5b6c ended without a merge.";
  const ended = (status: RunStatus) => runEnd([], 0, status.completion, null, unsignedEnd(status));

  it("ends where no decision left can give the sign-off: its sentence, and the module", () => {
    const status = escalated([]);
    expect(phaseOf(status)).toBe("done");
    const standing = standingOf(status, ended(status));
    expect(standing.sentence).toContain("sign-off was not given");
    expect(standing.detail).toContain("sign-off not given");
    expect(standing.detail).toContain(WORDS);
  });

  it("waits for a person where the sign-off's item is open, and still names the module", () => {
    const status = escalated(["drive-0a1b2c"]);
    expect(phaseOf(status)).toBe("waiting-person");
    expect(standingOf(status, null).detail).toBe(WORDS);
  });

  it("names nothing where no module never ran, or at a step that is not the escalated end", () => {
    expect(standingOf({ ...escalated([]), neverRan: [] }, null).detail).toBeNull();
    const done: RunStatus = { ...escalated([]), kind: "done", signaturesOwed: [] };
    expect(standingOf(done, null).detail).toBeNull();
  });
});
