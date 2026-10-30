// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it } from "vitest";

import type { RunEvent } from "../../api/events";
import type { QueueListing } from "../../api/queue";
import type { LedgerLine } from "../../api/records";
import type { RunStatus } from "../../api/run";
import { bannedIn } from "../../words/queue";
import { LedgerTable } from "./Ledger";
import { attemptsWords, foldLedger, stateWords, subtaskLabel } from "./ledgerRows";

/** A status with no halt owed, in a run that plans no subtask declaring completion. */
const NOT_DECLARING = { owedHalt: null, completion: { owner: false, modules: [] } } as const;

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const line = (
  id: string,
  attempts: number,
  gate: LedgerLine["gate"] = null,
  review: LedgerLine["review"] = null,
  mergeCommit: string | null = null,
): LedgerLine => ({
  id,
  role: id.startsWith("control") ? "control" : "firmware",
  attempts,
  gate,
  review,
  mergeCommit,
});

const MERGE = "e1b49b3dbb1f27f09a168b2db35cb29e788fc1fe";
const ITEM = "run-control-1";

/**
 * Shaped like a recorded run: the control subtask rejected by its review at attempt 1, its
 * attempt 2 gated and then reviewed with no verdict and escalated; the firmware subtask merged
 * at attempt 1. Eleven ledger lines in the order the loop wrote them.
 */
const LEDGER: readonly LedgerLine[] = [
  line("control-1", 0),
  line("firmware-2", 0),
  line("control-1", 1),
  line("control-1", 1, "pass"),
  line("control-1", 1, "pass", "fail"),
  line("control-1", 2),
  line("control-1", 2, "pass"),
  line("firmware-2", 1),
  line("firmware-2", 1, "pass"),
  line("firmware-2", 1, "pass", "pass"),
  line("firmware-2", 1, "pass", "pass", MERGE),
];

let seq = 0;
const at = <T extends object>(e: T) => ({ seq: seq++, ts: "t", ...e });
const EVENTS: readonly RunEvent[] = [
  at({ kind: "subtask_planned", subtask: "control-1", role: "control" } as const),
  at({ kind: "subtask_planned", subtask: "firmware-2", role: "firmware" } as const),
  at({
    kind: "attempt_rejected",
    subtask: "control-1",
    attempt: 1,
    findingSource: "review",
    finding: "f",
  } as const),
  at({
    kind: "review_unavailable",
    subtask: "control-1",
    attempt: 2,
    cause: "invalid_verdict",
    detail: null,
    reviewerModel: null,
  } as const),
  at({ kind: "escalated", subtask: "control-1", itemId: ITEM } as const),
  at({ kind: "merged", subtask: "firmware-2", attempt: 1, mergeCommit: MERGE } as const),
];

const OPEN: QueueListing = {
  open: [
    {
      itemId: ITEM,
      ts: "t",
      runId: "run",
      subtaskId: "control-1",
      source: "review_unavailable",
      decisionRequired: "d",
      artefactDiff: "",
      triggeringFinding: "f",
      quantities: [],
      trajectories: [],
      consequence: null,
    },
  ],
  decided: [],
};
const DONE: RunStatus = { kind: "escalated", subtask: null, halted: null, ...NOT_DECLARING };

const fold = (
  over: Partial<Parameters<typeof foldLedger>[1]> = {},
  lines: readonly LedgerLine[] = LEDGER,
) => foldLedger(lines, { events: EVENTS, status: DONE, queue: OPEN, budget: 3, ...over });

describe("the ledger folds to one row per subtask, read from its latest record", () => {
  it("one row per subtask, in plan order, each with every one of its lines as history", () => {
    const rows = fold();
    expect(rows.map((r) => r.id)).toEqual(["control-1", "firmware-2"]);
    expect(rows.map((r) => [r.position, r.of])).toEqual([
      [1, 2],
      [2, 2],
    ]);
    expect(rows[0]?.history.map((h) => h.position)).toEqual([1, 3, 4, 5, 6, 7]);
    expect(rows[1]?.history.map((h) => h.position)).toEqual([2, 8, 9, 10, 11]);
    expect(rows.flatMap((r) => r.history).length).toBe(LEDGER.length);
  });

  it("orders rows by the plan, not by the ledger's first line", () => {
    const planned = [...EVENTS].reverse().filter((e) => e.kind === "subtask_planned");
    const rows = foldLedger(LEDGER, { events: planned, status: DONE, queue: null, budget: 3 });
    expect(rows.map((r) => r.id)).toEqual(["firmware-2", "control-1"]);
  });

  it("reads the state, the attempts and the stages from the latest line, never the first", () => {
    const [control, firmware] = fold();
    expect(control?.attempts).toBe(2);
    expect(firmware?.attempts).toBe(1);
    expect(firmware?.state).toEqual({ kind: "merged", commit: MERGE });
    expect(firmware?.mergeCommit).toBe(MERGE);
    expect(firmware?.gate).toEqual({ kind: "recorded", result: "pass" });
    expect(firmware?.review).toEqual({ kind: "recorded", result: "pass" });
    // Attempt 2's gate passed; attempt 1's review failed, and is not attempt 2's.
    expect(control?.gate).toEqual({ kind: "recorded", result: "pass" });
    expect(control?.review).toEqual({ kind: "no-verdict", cause: "invalid_verdict" });
  });

  it("counts attempts as k of n where the server sent the budget, and k alone where not", () => {
    const [control] = fold();
    expect(control === undefined ? "" : attemptsWords(control)).toBe("2 of 3");
    const [bare] = fold({ budget: null });
    expect(bare === undefined ? "" : attemptsWords(bare)).toBe("2");
  });

  it("says not run only for an attempt that is over, and not yet while the run is on it", () => {
    const lines = [
      line("control-1", 0),
      line("control-1", 1, "pass", "fail"),
      line("control-1", 2),
    ];
    const events = EVENTS.filter((e) => e.kind !== "escalated" && e.kind !== "review_unavailable");
    const on: RunStatus = { kind: "attempt", subtask: "control-1", halted: null, ...NOT_DECLARING };
    const [running] = foldLedger(lines, { events, status: on, queue: null, budget: 3 });
    expect(running?.state).toEqual({ kind: "repairing", rejected: 1, attempt: 2 });
    expect(running?.gate).toEqual({ kind: "not-yet" });
    expect(running?.review).toEqual({ kind: "not-yet" });
    const halted: RunStatus = {
      kind: "halted",
      subtask: null,
      halted: { reason: "r", detail: "d" },
      ...NOT_DECLARING,
    };
    const [stopped] = foldLedger(lines, { events, status: halted, queue: null, budget: 3 });
    expect(stopped?.state).toEqual({ kind: "attempted", attempt: 2 });
    expect(stopped?.gate).toEqual({ kind: "not-run" });
    expect(stopped?.review).toEqual({ kind: "not-run" });
  });

  it("a rejected latest attempt reads rejected, and repairing when the run's next step is it", () => {
    const lines = [line("control-1", 0), line("control-1", 1, "pass", "fail")];
    const events = EVENTS.filter((e) => e.kind !== "escalated" && e.kind !== "review_unavailable");
    const [rejected] = foldLedger(lines, { events, status: DONE, queue: null, budget: 3 });
    expect(rejected?.state).toEqual({ kind: "rejected", attempt: 1 });
    const on: RunStatus = { kind: "attempt", subtask: "control-1", halted: null, ...NOT_DECLARING };
    const [next] = foldLedger(lines, { events, status: on, queue: null, budget: 3 });
    expect(next?.state).toEqual({ kind: "repairing", rejected: 1, attempt: 2 });
    // The rejected attempt's own results stay: they are the latest attempt's.
    expect(next?.review).toEqual({ kind: "recorded", result: "fail" });
  });

  it("an escalated subtask waits for a person while its item is open, and names the item", () => {
    const [control] = fold();
    expect(control?.state).toEqual({ kind: "waiting", itemId: ITEM });
    expect(control === undefined ? "" : stateWords(control.state)).toBe(
      "Escalated: waiting for a person's decision",
    );
  });

  it("an escalated subtask a person decided says who and what, and that it is not merged", () => {
    const decided: QueueListing = {
      open: [],
      decided: [
        {
          itemId: ITEM,
          ts: "t",
          decision: "approve",
          resolvedBy: "yasin",
          flag: null,
          taken: null,
        },
      ],
    };
    const [control] = fold({ queue: decided });
    expect(control?.state).toEqual({
      kind: "decided",
      itemId: ITEM,
      decision: "approve",
      by: "yasin",
    });
    expect(control === undefined ? "" : stateWords(control.state)).toBe(
      "Decided by yasin: approved. Not merged.",
    );
  });

  it("an escalation whose queue was not read claims neither waiting nor decided", () => {
    const [control] = fold({ queue: null });
    expect(control?.state).toEqual({ kind: "sent", itemId: ITEM });
  });

  it("a subtask with no attempt is not started, with no stage result", () => {
    const [only] = foldLedger([line("firmware-2", 0)], {
      events: EVENTS.slice(0, 2),
      status: DONE,
      queue: null,
      budget: 3,
    });
    expect(only?.state).toEqual({ kind: "not-started" });
    expect(only?.gate).toEqual({ kind: "no-attempt" });
  });
});

describe("the folded ledger as drawn", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  const table = () => <LedgerTable rows={fold()} lines={LEDGER.length} mode="on" run="0/run" />;

  it("draws one row per subtask, its name first and its id after it", () => {
    const html = renderToStaticMarkup(table());
    expect(html.match(/data-subtask=/g)?.length).toBe(2);
    const cell = html.slice(html.indexOf('<span class="pg-ledger-name">'));
    expect(cell.indexOf("Control module")).toBeLessThan(cell.indexOf("control-1"));
    expect(subtaskLabel({ role: "control" })).toBe("Control module");
    expect(html).toContain("2 of 3");
    expect(html).toContain("no verdict: its answer was not a valid verdict");
    expect(html).not.toMatch(/>not run</);
  });

  it("links the waiting subtask to its queue item, and says nothing the record does not", () => {
    const html = renderToStaticMarkup(table());
    expect(html).toContain("waiting for a person&#x27;s decision");
    expect(html).toContain(`href="#/collaboration/approval-queue?run=0%2Frun&amp;item=${ITEM}"`);
    expect(bannedIn(html)).toEqual([]);
  });

  it("opens a row's history with every ledger line of that subtask, and closes it again", () => {
    const host = document.createElement("div");
    document.body.append(host);
    act(() => {
      createRoot(host).render(table());
    });
    expect(host.querySelector("table.pg-ledger-history")).toBeNull();
    const button = host.querySelector<HTMLButtonElement>(
      'tr[data-subtask="control-1"] td:last-child button',
    );
    expect(button?.getAttribute("aria-expanded")).toBe("false");
    act(() => {
      button?.click();
    });
    expect(button?.getAttribute("aria-expanded")).toBe("true");
    const history = host.querySelector("table.pg-ledger-history");
    expect(history?.getAttribute("aria-label")).toBe("History of Control module");
    expect(history?.querySelectorAll("tbody tr").length).toBe(6);
    act(() => {
      button?.click();
    });
    expect(host.querySelector("table.pg-ledger-history")).toBeNull();
  });
});
