// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { RunEvent } from "../../api/events";
import { RowView } from "../common/RowView";
import { type Row, rowsOf } from "../common/rows";
import { Reviews } from "./AttemptInspector";
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

  it("names a rejected attempt by the finding that rejected it, and says nothing of a repair", () => {
    // The log records a rejection and its finding. Whether a repair follows is not in this line.
    expect(rowAt(rows, 5).sentence).toBe("Attempt 1 rejected: x");
    expect(rowAt(rows, 5).sentence).not.toMatch(/repair/i);
    expect(rowAt(rows, 5).meta).toContain("finding from the gate");
  });

  it("a gate line in a mode the interface does not know is shown as written, never as on", () => {
    const strange = rowsOf(
      more.map((e) => (e.kind === "integration_gate_ran" ? { ...e, mode: "dry-run" } : e)),
      MODELS,
    );
    const row = rowAt(strange, 9);
    expect(row.end).toEqual({ kind: "gate-unknown-mode", mode: "dry-run", outcome: "fail" });
    const html = renderToStaticMarkup(<RowView row={row} />);
    expect(html).toContain("dry-run");
    expect(html).not.toMatch(/pg-verdict-(pass|fail|warn)|pg-observed|pg-gate-on/);
  });

  it("a row the record maps to no actor shows none, never a default one", () => {
    const row: Row = { ...rowAt(rows, 5), actor: null };
    const html = renderToStaticMarkup(<RowView row={row} />);
    expect(html).not.toContain("pg-actor");
    expect(html).not.toContain("Orchestrator");
    expect(html).toContain("Attempt 1 rejected: x");
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

describe("the attempt inspector's reviews are the log's review lines", () => {
  it("with none, says only that none is recorded: why none ran is not in the log", () => {
    const html = renderToStaticMarkup(<Reviews reviews={[]} />);
    expect(html).toContain("Not run: no review is recorded for this attempt.");
    expect(html).not.toMatch(/because|gate failed|reviewer saw/i);
  });

  it("lists each recorded review by its finding, its model and its verdict", () => {
    const html = renderToStaticMarkup(
      <Reviews
        reviews={[
          {
            ...at(9),
            kind: "review_ran",
            subtask: "s1",
            attempt: 1,
            verdict: "fail",
            finding: "x",
            reviewerModel: "claude-sonnet-5",
            sessionId: null,
          },
        ]}
      />,
    );
    expect(html).toContain("x");
    expect(html).toContain("claude-sonnet-5");
    expect(html).toContain("pg-verdict-fail");
    expect(html).not.toContain("Not run");
  });
});

describe("a review that reached no verdict has its own row, never a pass or a fail", () => {
  const log: RunEvent[] = [
    { ...at(0), kind: "run_started", runId: "r", mode: "on" },
    { ...at(2), kind: "subtask_planned", subtask: "s1", role: "electrical" },
    {
      ...at(4),
      kind: "gate_ran",
      subtask: "s1",
      attempt: 2,
      verdict: "pass",
      mode: "on",
      finding: "ok",
      failingCheck: null,
      value: null,
    },
    {
      ...at(5),
      kind: "review_unavailable",
      subtask: "s1",
      attempt: 2,
      cause: "invalid_verdict",
      detail:
        "the binary's cap on refused verdicts ended it: Failed to provide valid structured output after 5 attempts",
      reviewerModel: "claude-sonnet-5",
    },
    { ...at(6), kind: "escalated", subtask: "s1", itemId: "item-1" },
  ];
  const rows = rowsOf(log, MODELS);
  const row = rowAt(rows, 5);

  it("sits between the gate and the set-aside row, in the log's order", () => {
    expect(rows.map((r) => r.seq)).toEqual([0, 2, 4, 5, 6]);
  });

  it("says in plain words what happened, with the cause and the tries", () => {
    expect(row.sentence).toBe(
      "Review of attempt 2 reached no verdict: the reviewer's answer did not fit the required form (5 tries)",
    );
    expect(row.depth).toBe(2);
    expect(row.attempt).toBe(2);
  });

  it("shows the reviewer as the actor, and ends as no verdict, not as a pass or a fail", () => {
    expect(row.actor).toMatchObject({ kind: "agent", model: "claude-sonnet-5" });
    const html = renderToStaticMarkup(<RowView row={row} />);
    expect(html).toContain("no verdict");
    expect(html).not.toMatch(/pg-verdict-(pass|fail)/);
  });

  it("says nothing about tries when the record has none, and names a cause it does not know", () => {
    const bare = rowsOf(
      log.map((e) =>
        e.kind === "review_unavailable" ? { ...e, cause: "odd_new_cause", detail: null } : e,
      ),
      MODELS,
    );
    expect(rowAt(bare, 5).sentence).toBe(
      "Review of attempt 2 reached no verdict: cause recorded as odd_new_cause",
    );
  });
});

describe("a finding is shown once, a short first line first and the rest expandable", () => {
  const long =
    "The control design is thorough and, on its technical merits, would be an accept. " +
    "However the session wrote outside its allowance, which the hooks forbid. " +
    "Details follow in the trajectory.";
  const log: RunEvent[] = [
    { ...at(0), kind: "run_started", runId: "r", mode: "on" },
    { ...at(2), kind: "subtask_planned", subtask: "s1", role: "electrical" },
    {
      ...at(5),
      kind: "review_ran",
      subtask: "s1",
      attempt: 1,
      verdict: "fail",
      finding: long,
      reviewerModel: "claude-sonnet-5",
      sessionId: "x",
    },
    {
      ...at(6),
      kind: "attempt_rejected",
      subtask: "s1",
      attempt: 1,
      findingSource: "review",
      finding: long,
    },
  ];
  const rows = rowsOf(log, MODELS);

  it("the reviewer's row holds the finding: a first sentence, the rest apart", () => {
    const review = rowAt(rows, 5);
    expect(review.sentence).toBe(
      "The reviewer refused attempt 1: The control design is thorough and, on its technical merits, would be an accept.",
    );
    expect(review.more).toBe(
      "However the session wrote outside its allowance, which the hooks forbid. Details follow in the trajectory.",
    );
  });

  it("the rejection that repeats it says so and does not print it again", () => {
    const rejected = rowAt(rows, 6);
    expect(rejected.sentence).toBe("Attempt 1 rejected on the reviewer's finding above");
    expect(rejected.more).toBeNull();
    const all = rows.map((r) => `${r.sentence} ${r.more ?? ""}`).join(" ");
    expect(all.split("would be an accept").length - 1).toBe(1);
  });

  it("the expandable rest is a collapsed details element beside the row, not inside its button", () => {
    const html = renderToStaticMarkup(<RowView row={rowAt(rows, 5)} onSelect={() => undefined} />);
    expect(html).toContain("<details");
    expect(html).not.toContain("<details open");
    expect(html).toContain("Show the rest");
    expect(html.indexOf("</button>")).toBeLessThan(html.indexOf("<details"));
  });

  it("a short finding has nothing to expand, and a differing rejection still prints its text", () => {
    const short = rowsOf(
      log.map((e) => (e.kind === "review_ran" ? { ...e, finding: "Too hot." } : e)),
      MODELS,
    );
    expect(rowAt(short, 5).more).toBeNull();
    expect(rowAt(short, 5).sentence).toBe("The reviewer refused attempt 1: Too hot.");
    expect(rowAt(short, 6).sentence).toContain("rejected: ");
  });
});
