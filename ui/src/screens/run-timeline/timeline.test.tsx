// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { RunEvent } from "../../api/events";
import { RowView } from "../common/RowView";
import { type Row, rowsOf } from "../common/rows";
import { gateReading, readingWords } from "./gate";
import { parseAttempt } from "./RunTimeline";

const MODELS = {
  roleModels: { electrical: "claude-sonnet-5" },
  decompositionModel: "claude-sonnet-5",
  reviewerModels: {},
};

const at = (seq: number) => ({
  seq,
  ts: `2026-10-10T12:00:${String(seq).padStart(2, "0")}.000000Z`,
});

/** The row of ``seq``; a missing one fails the test that asked for it. */
function rowAt(rows: readonly Row[], seq: number): Row {
  const found = rows.find((r) => r.seq === seq);
  if (found === undefined) throw new Error(`no row for line ${String(seq)}`);
  return found;
}

const LOG: RunEvent[] = [
  { ...at(0), kind: "run_started", runId: "r", mode: "on" },
  { ...at(1), kind: "decomposed", model: "claude-sonnet-5", subtasks: 1, interfaceNodes: [] },
  { ...at(2), kind: "subtask_planned", subtask: "s1", role: "electrical" },
  { ...at(3), kind: "stage_entered", subtask: "s1", attempt: 1, stage: "gate" },
  {
    ...at(4),
    kind: "gate_ran",
    subtask: "s1",
    attempt: 1,
    verdict: "fail",
    mode: "on",
    finding: "the stall current is too high",
    failingCheck: "magnitude",
    value: { value: 3.4, unit: "A" },
  },
  {
    ...at(5),
    kind: "attempt_rejected",
    subtask: "s1",
    attempt: 1,
    findingSource: "gate",
    finding: "x",
  },
  { ...at(6), kind: "stage_entered", subtask: "s1", attempt: 2, stage: "gate" },
  { ...at(7), kind: "escalated", subtask: "s1", itemId: "item-1" },
];

describe("the timeline's rows are sentences built from the record", () => {
  const rows = rowsOf(LOG, MODELS);

  it("keeps the log's order and the depth of run, subtask and attempt", () => {
    expect(rows.map((r) => [r.seq, r.depth])).toEqual([
      [0, 0],
      [1, 0],
      [2, 1],
      [4, 2],
      [5, 2],
      [6, 2],
      [7, 1],
    ]);
  });

  it("a failed gate's sentence is its own message, with its value as a quantity", () => {
    const gate = rows.find((r) => r.seq === 4);
    expect(gate?.sentence).toBe("The stall current is too high");
    expect(gate?.value).toEqual({ value: 3.4, unit: "A" });
    expect(gate?.end).toEqual({ kind: "gate", mode: "on", outcome: "fail" });
    const html = renderToStaticMarkup(<RowView row={rowAt(rows, 4)} />);
    expect(html).toContain("pg-quantity");
    expect(html).toContain("pg-verdict-fail");
  });

  it("a gate stage with no recorded result is no verdict, never a pass", () => {
    const open = rows.find((r) => r.seq === 6);
    expect(open?.end).toEqual({ kind: "no-verdict" });
    const html = renderToStaticMarkup(<RowView row={rowAt(rows, 6)} />);
    expect(html).toContain("No verdict recorded");
    expect(html).not.toContain("pg-verdict-pass");
    // A gate stage that has its result makes no row of its own.
    expect(rows.some((r) => r.seq === 3)).toBe(false);
  });

  it("a subtask set aside reads as set aside, and the run going on", () => {
    expect(rows.find((r) => r.seq === 7)?.sentence).toBe(
      "Set aside for a person to decide (item-1). The run goes on with the other subtasks.",
    );
  });

  it("every row shows its actor: the harness, or an agent with its model", () => {
    expect(rows.find((r) => r.seq === 0)?.actor).toEqual({
      kind: "deterministic",
      name: "Orchestrator",
    });
    expect(rows.find((r) => r.seq === 1)?.actor).toMatchObject({
      kind: "agent",
      model: "claude-sonnet-5",
    });
    expect(rows.find((r) => r.seq === 4)?.actor).toEqual({ kind: "deterministic", name: "Gate" });
  });

  it("under observe a failed gate reads would fail, not enforced, never a filled fail", () => {
    const observed = rowsOf(
      LOG.map((e) => (e.kind === "gate_ran" ? { ...e, mode: "observe" } : e)),
      MODELS,
    );
    const html = renderToStaticMarkup(<RowView row={rowAt(observed, 4)} />);
    expect(html).toContain("Would fail · not enforced");
    expect(html).not.toContain("pg-verdict-fail");
  });

  it("an unmapped actor is shown as written, with no actor colour", () => {
    const rows2 = rowsOf(LOG, { ...MODELS, roleModels: {} });
    const html = renderToStaticMarkup(
      <RowView
        row={{
          ...rowAt(rows2, 0),
          actor: { kind: "unmapped", name: "someone" },
        }}
      />,
    );
    expect(html).toContain('data-actor="unmapped"');
    expect(html).not.toContain("pg-actor-agent");
  });
});

describe("repairs, infrastructure faults and the whole-design gate say what the record says", () => {
  const more: RunEvent[] = [
    ...LOG,
    {
      ...at(8),
      kind: "session_ended",
      subtask: "s1",
      attempt: 2,
      sessionId: "x",
      outcome: "infrastructure",
      cause: "rate_limited",
      sealed: false,
    },
    { ...at(9), kind: "integration_gate_ran", verdict: "fail", mode: "observe" },
  ];
  const unchecked = {
    seq: 9,
    subtask: "integration",
    attempt: null,
    name: "power" as const,
    check: 4,
    ts: null,
    scope: "system",
    mode: "observe" as const,
    outcome: "unchecked" as const,
    blocking: true,
    value: null,
    node: null,
    evaluated: null,
    reviewerHadPassed: null,
    expected: null,
    message: "m",
    details: { form: "power", evaluated: null, quantities: [], low: null, high: null },
  };
  const rows = rowsOf(more, MODELS, [unchecked]);

  it("names a repair by the finding that caused it", () => {
    expect(rowAt(rows, 5).sentence).toBe("Attempt 1 sent back for repair: x");
    expect(rowAt(rows, 5).meta).toContain("finding from the gate");
  });

  it("names an infrastructure fault by its cause", () => {
    expect(rowAt(rows, 8).sentence).toContain("infrastructure fault (rate_limited)");
  });

  it("the whole design's gate shows its mode, and what it left unchecked", () => {
    const row = rowAt(rows, 9);
    expect(row.end).toEqual({ kind: "gate", mode: "observe", outcome: "fail" });
    expect(row.meta).toBe("integration · 1 left unchecked");
    const html = renderToStaticMarkup(<RowView row={row} />);
    expect(html).toContain("Would fail · not enforced");
    const on = rowsOf(
      more.map((e) => (e.kind === "integration_gate_ran" ? { ...e, mode: "on" } : e)),
      MODELS,
    );
    expect(renderToStaticMarkup(<RowView row={rowAt(on, 9)} />)).toContain("pg-verdict-fail");
  });
});

describe("an attempt's gate reading is its own records', through the one tally", () => {
  it("no record is no verdict, never a pass, in either mode", () => {
    expect(gateReading("on", [], false)).toEqual({ kind: "none" });
    expect(gateReading("observe", [], false)).toEqual({ kind: "none" });
  });

  it("records that are all unchecked judged nothing", () => {
    expect(gateReading("on", [{ outcome: "unchecked", blocking: true }], false)).toEqual({
      kind: "unchecked-only",
    });
  });

  it("a failure that does not block is not the gate failing", () => {
    expect(
      gateReading(
        "on",
        [
          { outcome: "fail", blocking: false },
          { outcome: "pass", blocking: true },
        ],
        false,
      ),
    ).toMatchObject({ outcome: "pass" });
  });

  it("under observe it reads would-be and not enforced, and says what it left unchecked", () => {
    const reading = gateReading(
      "observe",
      [
        { outcome: "fail", blocking: true },
        { outcome: "unchecked", blocking: true },
      ],
      false,
    );
    expect(readingWords(reading)).toBe(
      "The gate would have failed this attempt, but was not enforced. It left 1 unchecked.",
    );
  });

  it("a skipped gate says so, and takes no verdict", () => {
    expect(gateReading("on", [{ outcome: "pass", blocking: true }], true)).toEqual({ kind: "off" });
    expect(gateReading("off", [{ outcome: "pass", blocking: true }], false)).toEqual({
      kind: "off",
    });
  });
});

describe("the address names an attempt", () => {
  it("as subtask:attempt", () => {
    expect(parseAttempt("drive-c18c5d:3")).toEqual({ subtask: "drive-c18c5d", attempt: 3 });
    expect(parseAttempt("nonsense")).toBeNull();
    expect(parseAttempt(null)).toBeNull();
  });
});
