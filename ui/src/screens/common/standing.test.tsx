// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { type RunStatus, runStatus } from "../../api/run";
import type { RunRead } from "../home/data";
import { activeRun } from "../home/data";
import { statusWords } from "../home/Home";
import { foldLedger, stateWords } from "../run-records/ledgerRows";
import { inProgress } from "./runs";
import { phaseOf } from "../../words/standing";

const NOW = Date.parse("2026-11-16T22:26:00Z");
const MINUTE = 60_000;

/** A run whose next step is attempt 1 of s1, its log last written ``ago`` ms before ``NOW``. */
function attempting(ago: number | null, longest: number | null = 5400): RunStatus {
  return {
    kind: "attempt",
    subtask: "s1",
    halted: null,
    owedHalt: null,
    completion: { owner: false, modules: [] },
    waiting: [],
    superseded: {},
    lastLineAt: ago === null ? null : new Date(NOW - ago).toISOString(),
    longestStepS: longest,
  };
}

describe("a run whose process is gone is never shown as running", () => {
  it("is stopped when its log is silent past the run's own longest step and the margin", () => {
    const status = attempting(138 * MINUTE); // 2 h 18 min, past 90 min and half an hour more
    expect(phaseOf(status, NOW)).toBe("stopped");
    expect(inProgress(status, NOW)).toBe(false);
  });

  it("is going while the silence is within what a living run takes", () => {
    expect(phaseOf(attempting(10 * MINUTE), NOW)).toBe("going");
    expect(phaseOf(attempting(115 * MINUTE), NOW)).toBe("going");
    expect(inProgress(attempting(10 * MINUTE), NOW)).toBe(true);
  });

  it("claims nothing where the last line or the bound is not sent", () => {
    expect(phaseOf(attempting(null), NOW)).toBe("going");
    expect(phaseOf(attempting(600 * MINUTE, null), NOW)).toBe("going");
  });

  it("is waiting for a person, never running, when its next step waits on a decision", () => {
    expect(phaseOf({ ...attempting(MINUTE), kind: "wait", subtask: null }, NOW)).toBe(
      "waiting-person",
    );
    expect(phaseOf({ ...attempting(MINUTE), kind: "escalated", subtask: null }, NOW)).toBe(
      "waiting-person",
    );
  });

  it("reads the last line's time and the longest step from the status route", () => {
    const parsed = runStatus({
      next_step: { kind: "attempt", subtask_id: "s1", attempt: 1, point: "resolve" },
      halted: null,
      owed_halt: null,
      completion: { owner: false, modules: [] },
      waiting: [],
      superseded: {},
      last_line_at: "2026-11-16T20:08:34.910143Z",
      longest_step_s: 5400,
    });
    expect(parsed.lastLineAt).toBe("2026-11-16T20:08:34.910143Z");
    expect(parsed.longestStepS).toBe(5400);
  });
});

describe("the screens say a stopped run is stopped", () => {
  const read = (status: RunStatus): RunRead =>
    ({
      run: { root: 0, name: "r", runId: "r", error: null },
      status: { ok: true, value: status },
      config: { ok: false, refusal: { error: "x" } },
      events: { ok: true, value: [] },
      queue: { ok: true, value: { open: [], decided: [] } },
    }) as unknown as RunRead;

  it("Home's list says stopped, with nothing running, and never in progress", () => {
    const html = renderToStaticMarkup(<>{statusWords(read(attempting(138 * MINUTE)), NOW)}</>);
    expect(html).toContain("Stopped");
    expect(html).toContain("nothing is running");
    expect(html).not.toContain("In progress");
  });

  it("Home leads with no run still going when the only one is stopped", () => {
    expect(activeRun([read(attempting(138 * MINUTE))], NOW)).toBeUndefined();
  });

  it("the ledger row says the attempt stopped, not that it is in progress", () => {
    const rows = foldLedger(
      [{ id: "s1", role: "firmware", attempts: 1, gate: null, review: null, mergeCommit: null }],
      { events: [], status: attempting(138 * MINUTE), queue: null, budget: 3, now: NOW },
    );
    const words = rows[0] === undefined ? "" : stateWords(rows[0].state);
    expect(words).toBe("Stopped at attempt 1; nothing is running");
  });
});
