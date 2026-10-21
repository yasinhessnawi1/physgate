import { describe, expect, it } from "vitest";

import type { RunEvent } from "../../api/events";
import type { ItemView, QueueItem, QueueListing } from "../../api/queue";
import { escalatedItemOf, repairsUsedUp } from "./usedUp";

function item(itemId: string, subtaskId: string, source: QueueItem["source"]): QueueItem {
  return {
    itemId,
    ts: "2026-10-11T09:00:00.000000Z",
    runId: "r",
    subtaskId,
    source,
    decisionRequired: "Decide.",
    artefactDiff: "",
    triggeringFinding: "",
    quantities: [],
    trajectories: [],
    consequence: null,
  };
}

function view(queueItem: QueueItem, open: boolean): ItemView {
  return { position: 0, itemSha256: "a".repeat(64), open, item: queueItem, trajectories: [] };
}

const EVENTS: RunEvent[] = [
  { seq: 1, ts: "t", kind: "subtask_planned", subtask: "s1", role: "electrical" },
  { seq: 7, ts: "t", kind: "escalated", subtask: "s1", itemId: "r-s1" },
];

describe("repairs used up is said only where the queue recorded it", () => {
  it("the escalated item is the log's, or none", () => {
    expect(escalatedItemOf(EVENTS, "s1")).toBe("r-s1");
    expect(escalatedItemOf(EVENTS, "s2")).toBeNull();
  });

  it("an open item whose source is the exhausted budget says so; another source does not", () => {
    const exhausted: QueueListing = {
      open: [item("r-s1", "s1", "repair_budget_exhausted")],
      decided: [],
    };
    expect(repairsUsedUp(exhausted, null, "r-s1", "s1")).toBe(true);
    const other: QueueListing = { open: [item("r-s1", "s1", "arbitration")], decided: [] };
    expect(repairsUsedUp(other, null, "r-s1", "s1")).toBe(false);
    expect(repairsUsedUp(null, null, "r-s1", "s1")).toBe(false);
  });

  it("stays once the item is decided, read from the decided item's own record", () => {
    const decided: QueueListing = {
      open: [],
      decided: [
        {
          itemId: "r-s1",
          ts: "t",
          decision: "approve",
          resolvedBy: "yasin",
          flag: null,
          taken: null,
        },
      ],
    };
    const views = [view(item("r-s1", "s1", "repair_budget_exhausted"), false)];
    expect(repairsUsedUp(decided, views, "r-s1", "s1")).toBe(true);
    // Not yet read: nothing is said until the record is.
    expect(repairsUsedUp(decided, null, "r-s1", "s1")).toBe(false);
    // Decided for another reason: nothing is said.
    expect(
      repairsUsedUp(decided, [view(item("r-s1", "s1", "arbitration"), false)], "r-s1", "s1"),
    ).toBe(false);
    // The log never escalated this subtask: nothing is said, whatever the queue holds.
    expect(repairsUsedUp(decided, views, null, "s1")).toBe(false);
  });
});
