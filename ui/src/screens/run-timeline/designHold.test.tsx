/**
 * The design pairs a run plans, a builder held until the design it implements is merged, and its
 * release: each line reads as its own plain sentence, said by the orchestrator, never as an
 * unnamed line.
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
    ts: `2026-11-21T09:00:${String(seq).padStart(2, "0")}.000000Z`,
    run_id: "r",
    gate_mode: "on",
    ...fields,
  };
}

const PLANNED = [
  written({ kind: "subtask_planned", subtask_id: "control", assigned_role: "control" }),
  written({ kind: "subtask_planned", subtask_id: "firmware", assigned_role: "firmware" }),
  written({ kind: "subtask_planned", subtask_id: "third", assigned_role: "firmware" }),
];
const PAIRS = written({
  kind: "design_pairs_planned",
  pairs: [
    { designer: "control", builder: "firmware", nodes: ["control.law"] },
    { designer: "firmware", builder: "third", nodes: ["firmware.law"] },
  ],
});
const MUTUAL = written({
  kind: "design_pairs_planned",
  pairs: [{ designer: "control", builder: "firmware", nodes: ["control.law"] }],
  mutual: [{ designer: "firmware", builder: "control", nodes: ["firmware.timing"] }],
});

function held(why: string, extra: Record<string, unknown> = {}): Record<string, unknown> {
  return written({
    kind: "builder_held",
    subtask_id: "firmware",
    designer: "control",
    nodes: ["control.law"],
    why,
    ...extra,
  });
}

const HELD = {
  escalated: held("escalated", { item_id: "r-control-3" }),
  ended_unmerged: held("ended_unmerged"),
  designer_held: written({
    kind: "builder_held",
    subtask_id: "third",
    designer: "firmware",
    nodes: ["firmware.law"],
    why: "designer_held",
    chain: ["firmware", "control"],
  }),
  not_merged: held("not_merged"),
};
const RELEASED = written({
  kind: "builder_released",
  subtask_id: "firmware",
  designer: "control",
  nodes: ["control.law"],
});

const LINES = [...PLANNED, PAIRS, MUTUAL, ...Object.values(HELD), RELEASED];

function rows(): readonly Row[] {
  return rowsOf(LINES.map(runEvent), MODELS);
}

function rowOfLine(line: Record<string, unknown>): Row | undefined {
  return rows().find((r) => r.seq === line.seq);
}

const ORCHESTRATOR = { kind: "deterministic", name: "Orchestrator" };

describe("a builder held until its design is merged reads as its own sentence", () => {
  it("the planned pairs name each builder, its designer and the design's nodes", () => {
    const row = rowOfLine(PAIRS);
    expect(row?.sentence).toBe("Planned 2 design pairs");
    expect(row?.meta).toBe(
      "Subtask 2 builds Subtask 1's design on control.law; Subtask 3 builds Subtask 2's design on firmware.law",
    );
    expect(row?.actor).toEqual(ORCHESTRATOR);
  });

  it("a naming the other way round is shown beside its pair, holding nothing", () => {
    const row = rowOfLine(MUTUAL);
    expect(row?.sentence).toBe("Planned 1 design pair");
    expect(row?.meta).toBe(
      "Subtask 2 builds Subtask 1's design on control.law; Subtask 1 also names firmware.timing of Subtask 2's, which holds nothing",
    );
  });

  it.each([
    [
      "escalated",
      "Subtask 2 is held until Subtask 1's design is merged: Subtask 1 is with a person (r-control-3)",
      "firmware · implements control.law",
    ],
    [
      "ended_unmerged",
      "Subtask 2 is held for good: Subtask 1 ended without merging, so there is no design to build",
      "firmware · implements control.law",
    ],
    [
      "designer_held",
      "Subtask 3 is held for good: Subtask 2 is itself held for good, through Subtask 2, then Subtask 1",
      "third · implements firmware.law",
    ],
    [
      "not_merged",
      "Subtask 2 is held until Subtask 1's design is merged",
      "firmware · implements control.law",
    ],
  ] as const)("held as %s", (why, says, meta) => {
    const row = rowOfLine(HELD[why]);
    expect(row?.sentence).toBe(says);
    expect(row?.meta).toBe(meta);
    expect(row?.depth).toBe(1);
    expect(row?.actor).toEqual(ORCHESTRATOR);
  });

  it("the release says the design merged", () => {
    const row = rowOfLine(RELEASED);
    expect(row?.sentence).toBe("Subtask 2 released: Subtask 1's design merged");
    expect(row?.meta).toBe("firmware · implements control.law");
    expect(row?.subtask).toBe("firmware");
    expect(row?.actor).toEqual(ORCHESTRATOR);
  });

  it("no line of the three reads as an unnamed line", () => {
    const kinds = [PAIRS, ...Object.values(HELD), RELEASED].map((l) => runEvent(l).kind);
    expect(kinds).not.toContain("other");
  });

  it("a reason the loop does not write is refused, not shown", () => {
    expect(() => runEvent(held("approved"))).toThrow();
  });

  it("no row uses a word that claims more than the record", () => {
    const said = rows()
      .map((r) => `${r.sentence} ${r.meta}`)
      .join("\n");
    expect(bannedIn(said)).toEqual([]);
  });
});
