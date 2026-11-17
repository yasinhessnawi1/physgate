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
