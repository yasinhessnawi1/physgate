/**
 * A subtask held while a subtask it reads from is with a person, and how the hold was let go:
 * each line reads as its own plain sentence, said by the orchestrator, never as an unnamed line.
 */
import { describe, expect, it } from "vitest";

import { runEvent } from "../../api/events";
import { bannedIn } from "../../words/queue";
import { type Row, rowsOf } from "../common/rows";

const MODELS = {
  roleModels: { control: "claude-sonnet-5" },
  decompositionModel: "claude-sonnet-5",
  reviewerModels: {},
};

let next = 0;
/** One event line as the Python loop writes it, with the next sequence number. */
function written(fields: Record<string, unknown>): Record<string, unknown> {
  const seq = next++;
  return {
    seq,
    ts: `2026-11-13T09:00:${String(seq).padStart(2, "0")}.000000Z`,
    run_id: "r",
    gate_mode: "on",
    ...fields,
  };
}

const PLANNED = [
  written({ kind: "subtask_planned", subtask_id: "control", assigned_role: "control" }),
  written({ kind: "subtask_planned", subtask_id: "firmware", assigned_role: "firmware" }),
];
const HELD = written({
  kind: "dispatch_held",
  subtask_id: "firmware",
  producer: "control",
  item_id: "r-control-3",
  interfaces: ["balance.loop_contract"],
});

function released(outcome: string): Record<string, unknown> {
  return written({
    kind: "dispatch_released",
    subtask_id: "firmware",
    producer: "control",
    item_id: "r-control-3",
    outcome,
  });
}

const RELEASED = {
  merged: released("merged"),
  ended_unmerged: released("ended_unmerged"),
  waits_for_closing_pass: released("waits_for_closing_pass"),
  mutual_readers: released("mutual_readers"),
};

const LINES = [...PLANNED, HELD, ...Object.values(RELEASED)];

function rows(): readonly Row[] {
  return rowsOf(LINES.map(runEvent), MODELS);
}

function rowOfLine(line: Record<string, unknown>): Row | undefined {
  return rows().find((r) => r.seq === line.seq);
}

describe("a held dispatch says what it waits for, and its release says why it was let go", () => {
  it("the hold names the subtask waited for, that it is with a person, and the item", () => {
    const row = rowOfLine(HELD);
    expect(row?.sentence).toBe(
      "Subtask 2 is waiting for Subtask 1, which is with a person (r-control-3)",
    );
    expect(row?.meta).toBe("firmware · reads balance.loop_contract");
    expect(row?.subtask).toBe("firmware");
    expect(row?.depth).toBe(1);
    expect(row?.actor).toEqual({ kind: "deterministic", name: "Orchestrator" });
  });

  it.each([
    ["merged", "Subtask 2 released: Subtask 1 merged"],
    ["ended_unmerged", "Subtask 2 released: Subtask 1 ended without merging"],
    [
      "waits_for_closing_pass",
      "Subtask 2 released: Subtask 1 waits for sizing's closing pass, which comes after it",
    ],
    [
      "mutual_readers",
      "Subtask 2 is not held: it and Subtask 1 read from each other, so it runs while Subtask 1 is with a person",
    ],
  ] as const)("released as %s", (outcome, says) => {
    const row = rowOfLine(RELEASED[outcome]);
    expect(row?.sentence).toBe(says);
    expect(row?.meta).toBe("firmware · r-control-3");
    expect(row?.depth).toBe(1);
    expect(row?.actor).toEqual({ kind: "deterministic", name: "Orchestrator" });
  });

  it("an outcome the loop does not write is refused, not shown", () => {
    expect(() => runEvent(released("approved"))).toThrow();
  });

  it("no row uses a word that claims more than the record", () => {
    const said = rows()
      .map((r) => `${r.sentence} ${r.meta}`)
      .join("\n");
    expect(bannedIn(said)).toEqual([]);
  });
});
