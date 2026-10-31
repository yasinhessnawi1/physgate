/**
 * A rejected plan and its item, as the screens say them: the timeline names why the whole design
 * was not gated in words, and the plan's item says what deciding it does in a run that only
 * records decisions as well as in one that acts.
 */
import { describe, expect, it } from "vitest";

import { runEvent } from "../../api/events";
import { SOURCE_WORDS } from "../../words/queue";
import { rowsOf } from "../common/rows";

const MODELS = {
  roleModels: { electrical: "claude-sonnet-5" },
  decompositionModel: "claude-sonnet-5",
  reviewerModels: {},
};

describe("a rejected plan", () => {
  it("the timeline says a person rejected the plan, not the reason's code", () => {
    const skipped = runEvent({
      seq: 9,
      ts: "2026-10-31T09:00:09.000000Z",
      run_id: "r",
      gate_mode: "on",
      kind: "integration_gate_skipped",
      reason: "plan_rejected",
      subtasks: ["s1"],
    });
    const [row] = rowsOf([skipped], MODELS);
    expect(row?.sentence).toBe("The whole design was not gated: a person rejected the plan");
  });

  it("the plan's item says what a decision does under either decision mode", () => {
    const why = SOURCE_WORDS.plan_review.why;
    expect(why).toMatch(/in a run that acts on decisions, nothing is dispatched until a person/);
    expect(why).toMatch(/in one that only records them, the run ends with the item open/);
  });
});
