/**
 * A sign-off's lines on the timeline, and what a decision on a sign-off item did, in its own words:
 * a reject that reopened the module for its one fix, one that records only because the module was
 * reopened since or a later item replaced it, and each of the four lines a sign-off writes, built
 * from the fields its line names.
 */
import { describe, expect, it } from "vitest";

import { runEvent } from "../../api/events";
import { notMergedWords, rowsOf } from "../common/rows";
import { supersededOutcome, supersededWords, takenWords } from "../../words/queue";

const MODELS = { roleModels: {}, decompositionModel: "claude-sonnet-5", reviewerModels: {} };
const ON = { run_id: "r", gate_mode: "on" };
let next = 0;
/** One event line as the Python loop writes it, with the next sequence number. */
function written(fields: Record<string, unknown>): Record<string, unknown> {
  const seq = next++;
  return { seq, ts: `2026-11-21T09:00:${String(seq).padStart(2, "0")}.000000Z`, ...ON, ...fields };
}
const ITEM = { item_id: "r-SIGNOFF-c1", module: "c1", values_sha256: "a".repeat(64), bound: [] };
const AGAIN = { ...ITEM, item_id: "r-SIGNOFF-c1-r2" };

const taken = (over: Partial<Parameters<typeof takenWords>[0]>) =>
  ({
    effect: "none",
    acts: false,
    whyNot: null,
    confirmedBy: null,
    orderTooLong: false,
    ...over,
  }) as const;

describe("what a decision on a sign-off item did is said in its own words", () => {
  it("a reject that reopened the module names its one fix, not another module", () => {
    const words = takenWords(taken({ effect: "reopen", acts: true }), "sign_off");
    expect(words).toBe(
      "The run took it: the module was reopened for its one fix, told your note and the values " +
        "the item showed.",
    );
    expect(words).not.toContain("other module");
    // A contract item's reopen still reads as before.
    expect(takenWords(taken({ effect: "reopen", acts: true }), "contract")).toContain(
      "the other module was reopened",
    );
  });

  it("each record-only reason reads differently", () => {
    const replaced = takenWords(taken({ whyNot: "superseded" }), "sign_off");
    const reopened = takenWords(taken({ whyNot: "module_reopened" }), "sign_off");
    expect(replaced).toBe(
      "Recorded only: a later sign-off item on the module replaced this one, so the values it " +
        "showed are no longer the module's.",
    );
    expect(reopened).toBe(
      "Recorded only: the module was reopened for its follow-up after the item was listed, so " +
        "the fix the item offered could no longer be ordered.",
    );
    expect(new Set([replaced, reopened]).size).toBe(2);
    for (const words of [replaced, reopened]) expect(words).not.toContain("a choice on");
    // A contract item superseded by another's choice keeps its words.
    expect(takenWords(taken({ whyNot: "superseded" }), "contract")).toContain("a choice on");
  });

  it("a reject the item said records only, or whose order is too long, says the sign-off stays owed", () => {
    const said = takenWords(taken({ whyNot: "record_only_source" }), "sign_off");
    const long = takenWords(taken({ whyNot: "order_too_long" }), "sign_off");
    expect(said).toBe(
      "Recorded only: as the item said, no fix could be ordered for the module (its one fix was " +
        "ordered already, or it was not merged then), so it stays not complete and its sign-off " +
        "owed.",
    );
    expect(long).toContain("no fix was ordered; the module stays not complete");
    for (const words of [said, long]) {
      expect(words).not.toMatch(/record_only_source|order_too_long|\(\w+_\w+\)/);
      expect(words).not.toContain("subtask ended rejected");
    }
  });

  it("a reject of a module with no attempt left says so, apart from the other reasons", () => {
    const spent = takenWords(taken({ whyNot: "no_attempt_left" }), "sign_off");
    expect(spent).toBe(
      "Recorded only: the module has no attempt left to fix its values at, so it stays not " +
        "complete and its sign-off owed.",
    );
    const others = ["record_only_source", "order_too_long", "superseded", "module_reopened"].map(
      (whyNot) => takenWords(taken({ whyNot }), "sign_off"),
    );
    expect(new Set([spent, ...others]).size).toBe(5);
    expect(spent).not.toMatch(/no_attempt_left|_/);
  });

  it("an open sign-off item a later one replaced says so, not that a choice reopened a module", () => {
    expect(supersededWords("r-SIGNOFF-c1-r2", "sign_off")).toContain(
      "A later sign-off item on the module, r-SIGNOFF-c1-r2, replaced this one",
    );
    expect(supersededOutcome("r-SIGNOFF-c1-r2", "sign_off")).toContain(
      "a later sign-off item on the module, r-SIGNOFF-c1-r2, replaced this one",
    );
    expect(supersededWords("r-contract-1")).toContain("A choice on r-contract-1 reopened");
  });
});

describe("how a one-attempt follow-up or fix ended is said in words, never as its field", () => {
  it("each reason the record gives reads as a phrase, every underscore gone", () => {
    const said = ["rejected", "blocked", "no_verdict", "for_a_person"].map(notMergedWords);
    expect(said).toEqual([
      "the gate or its review rejected it",
      "its review was blocked",
      "its review reached no verdict",
      "it was set aside for a person",
    ]);
    expect(notMergedWords("a_new_reason")).toBe("a new reason");
  });
});

describe("each line a sign-off writes is a timeline row", () => {
  const lines = [
    written({
      kind: "subtask_planned",
      subtask_id: "c1",
      spec_path: "specs/c1.md",
      assigned_role: "control",
      module_dir: "modules/c1",
    }),
    written({ kind: "sign_offs_raised", subtask_id: "c1", attempt: 1, raised: [ITEM] }),
    written({ kind: "no_follow_up_owed" }),
    written({ kind: "sign_off_fix_ended", subtask_id: "c1", attempt: 2, why: "rejected" }),
    written({
      kind: "sign_off_raised_again",
      found: "completion",
      subtask_id: "integ",
      attempt: 1,
      raised: AGAIN,
    }),
  ];
  const events = lines.map(runEvent);
  const rows = rowsOf(events, MODELS);

  it("every one is read, none as a line of a kind not known here", () => {
    expect(events.map((e) => e.kind)).toEqual([
      "subtask_planned",
      "sign_offs_raised",
      "no_follow_up_owed",
      "sign_off_fix_ended",
      "sign_off_raised_again",
    ]);
  });

  it("each says what happened, with the item it is about", () => {
    const said = rows.map((r) => r.sentence).join("\n");
    expect(said).toContain(
      "A person's sign-off was asked for Subtask 1 (r-SIGNOFF-c1), after Subtask 1 merged",
    );
    expect(said).toContain(
      "No follow-up is owed before the integration call; the run waits for a person's sign-off",
    );
    expect(said).toContain(
      "Subtask 1's one fix after a rejected sign-off ended without a merge (the gate or its review " +
        "rejected it), and is not retried: its earlier merge stands, its sign-off stays owed, and " +
        "nothing left in this run can give it",
    );
    expect(said).toContain(
      "Subtask 1's sign-off was asked for again (r-SIGNOFF-c1-r2): the values it binds had moved with " +
        "no item raised on them, found where its completion was due",
    );
  });
});
