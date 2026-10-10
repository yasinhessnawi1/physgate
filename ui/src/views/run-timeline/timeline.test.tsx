import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type {
  Decision,
  GateCheck,
  StepTiming,
  TimelineEvents,
  Tokens,
  Trace,
  Usage,
} from "../../api/run";
import { TokensCard } from "./Cards";
import { StagesTable } from "./Chart";
import { findingLabel, gateReading, lanes } from "./model";

const SOURCE = { id: "run r-1", commit: "0123456789abcdef" };

function usage(input: number, output: number): Usage {
  return { input, output, cacheRead: 0, cacheWrite: 0 };
}

/** Two attempts whose stage lines run backwards in time: the order must still be the log's. */
const STEPS: StepTiming[] = [
  {
    seq: 3,
    subtask: "s1",
    attempt: 1,
    stage: "spawn",
    entered: "2026-10-10T12:00:09.000000Z",
    seconds: 1,
  },
  {
    seq: 5,
    subtask: "s1",
    attempt: 1,
    stage: "gate",
    entered: "2026-10-10T12:00:08.000000Z",
    seconds: 1,
  },
  {
    seq: 8,
    subtask: "s1",
    attempt: 2,
    stage: "spawn",
    entered: "2026-10-10T12:00:05.000000Z",
    seconds: 1,
  },
  {
    seq: 9,
    subtask: "s1",
    attempt: 2,
    stage: "gate",
    entered: "2026-10-10T12:00:04.000000Z",
    seconds: 1,
  },
  {
    seq: 11,
    subtask: "s1",
    attempt: 2,
    stage: "review",
    entered: "2026-10-10T12:00:03.000000Z",
    seconds: 1,
  },
];

const TRACE: Trace = {
  manifestId: "m".repeat(64),
  runId: "r-1",
  started: "2026-10-10T12:00:00.000000Z",
  last: "2026-10-10T12:00:10.000000Z",
  steps: STEPS,
  sessions: [
    {
      sessionId: "sess-one",
      subtask: "s1",
      attempt: 1,
      outcome: "completed",
      cause: null,
      wallClockS: 1,
      tokens: usage(10, 3),
      partial: false,
    },
    {
      sessionId: "sess-two",
      subtask: "s1",
      attempt: 2,
      outcome: "infrastructure",
      cause: "api_error",
      wallClockS: 1,
      tokens: usage(5, 1),
      partial: false,
    },
  ],
  decompositionTokens: usage(0, 0),
  reviewerTokens: {},
  routingTokens: usage(0, 0),
};

const DECISIONS: Decision[] = [
  {
    step: "gate",
    seq: 6,
    subtask: "s1",
    attempt: 1,
    verdict: "fail",
    failingCheck: "power",
    findingKey: null,
    cause: null,
    reason: null,
  },
  {
    step: "rejected",
    seq: 7,
    subtask: "s1",
    attempt: 1,
    verdict: null,
    failingCheck: null,
    findingKey: "gate|electrical.drive|power",
    cause: null,
    reason: null,
  },
  {
    step: "gate",
    seq: 10,
    subtask: "s1",
    attempt: 2,
    verdict: "pass",
    failingCheck: null,
    findingKey: null,
    cause: null,
    reason: null,
  },
];

/** A record of the gate line at ``seq`` for attempt ``attempt`` of s1. */
function record(seq: number, attempt: number | null, outcome: GateCheck["outcome"]): GateCheck {
  return {
    seq,
    subtask: attempt === null ? "integration" : "s1",
    attempt,
    name: "power",
    scope: "module",
    mode: "on",
    outcome,
    blocking: outcome !== "warn",
    value: null,
    node: null,
    evaluated: outcome === "pass" ? 1 : null,
    reviewerHadPassed: null,
    expected: null,
    message: "m",
    details: { form: outcome, evaluated: null, quantities: [], low: null, high: null },
  };
}

/** Attempt 1's gate line (6) failed with an unchecked record beside it; attempt 2's (10) passed. */
const CHECKS: GateCheck[] = [
  record(6, 1, "fail"),
  record(6, 1, "unchecked"),
  record(10, 2, "pass"),
  record(20, null, "fail"),
];

const EVENTS: TimelineEvents = {
  decomposed: {
    seq: 1,
    ts: "2026-10-10T12:00:00.500000Z",
    model: "claude-opus-5-5",
    subtasks: 1,
    interfaceNodes: ["iface.bus"],
  },
  roles: { s1: "electrical" },
  reviews: [],
  rejections: [
    {
      subtask: "s1",
      attempt: 1,
      findingKey: "gate|electrical.drive|power",
      repeatsPrevious: false,
    },
  ],
  integration: {
    seq: 20,
    ts: "2026-10-10T12:00:10.000000Z",
    kind: "skipped",
    verdict: null,
    reason: "not_all_merged",
  },
  gateSkipped: [],
};

describe("the timeline keeps the log's order", () => {
  it("lays lanes out in the order their stages first appear in the log, whatever the clock said", () => {
    const drawn = lanes(TRACE, DECISIONS, EVENTS, "on", { electrical: "claude-opus-5-5" }, CHECKS);
    expect(drawn.map((l) => l.key)).toEqual(["decomposition", "s1/1", "s1/2", "integration"]);
  });

  it("lists every stage in the order it was given", () => {
    const html = renderToStaticMarkup(<StagesTable steps={STEPS} source={SOURCE} />);
    const seqs = [...html.matchAll(/<tr><td class="mono">(\d+)<\/td>/g)].map((m) => Number(m[1]));
    expect(seqs).toEqual([3, 5, 8, 9, 11]);
  });

  it("names a repair by the finding that caused it, and an infrastructure session by its cause", () => {
    const drawn = lanes(TRACE, DECISIONS, EVENTS, "on", { electrical: "claude-opus-5-5" }, CHECKS);
    const second = drawn.find((l) => l.key === "s1/2");
    expect(second?.subtitle).toContain("repair of gate · power");
    expect(second?.segments.find((s) => s.kind === "infrastructure")?.label).toBe(
      "infrastructure · api_error",
    );
    expect(findingLabel("review|-|R3")).toBe("review · R3");
  });
});

describe("a gate segment's verdict is its own records', through the one tally", () => {
  it("under observe it reads would-be and not enforced, never a filled gate", () => {
    const drawn = lanes(TRACE, DECISIONS, EVENTS, "observe", {}, CHECKS);
    const gates = drawn.flatMap((l) => l.segments.filter((s) => s.kind === "gate"));
    expect(gates.map((g) => g.tone)).toEqual(["segment-gate-observe", "segment-gate-observe"]);
    expect(gates.map((g) => g.label)).toEqual([
      "would fail · not enforced · 1 unchecked",
      "would pass · not enforced",
    ]);
  });

  it("under on it is the gate's own colour, and it says what it left unchecked", () => {
    const drawn = lanes(TRACE, DECISIONS, EVENTS, "on", {}, CHECKS);
    const gates = drawn.flatMap((l) => l.segments.filter((s) => s.kind === "gate"));
    expect(gates.map((g) => [g.tone, g.label])).toEqual([
      ["segment-gate-on", "gate · fail · 1 unchecked"],
      ["segment-gate-on", "gate · pass"],
    ]);
  });

  it("a gate stage with no records is no verdict, never a pass, in either mode", () => {
    for (const mode of ["on", "observe"] as const) {
      const drawn = lanes(TRACE, DECISIONS, EVENTS, mode, {}, []);
      const gates = drawn.flatMap((l) => l.segments.filter((s) => s.kind === "gate"));
      expect(gates.map((g) => [g.tone, g.label])).toEqual([
        ["segment-gate-none", "gate · no verdict recorded"],
        ["segment-gate-none", "gate · no verdict recorded"],
      ]);
    }
  });

  it("records that are all unchecked judged nothing", () => {
    expect(
      gateReading(
        "on",
        [
          { outcome: "unchecked", blocking: true },
          { outcome: "unchecked", blocking: true },
        ],
        false,
      ),
    ).toEqual(["segment-gate-none", "gate · unchecked only"]);
    expect(gateReading("observe", [{ outcome: "unchecked", blocking: true }], false)[1]).toBe(
      "gate · unchecked only",
    );
  });

  it("a failure that does not block is not the gate failing", () => {
    const reading = gateReading(
      "on",
      [
        { outcome: "fail", blocking: false },
        { outcome: "pass", blocking: true },
      ],
      false,
    );
    expect(reading).toEqual(["segment-gate-on", "gate · pass"]);
    expect(gateReading("on", [{ outcome: "fail", blocking: true }], false)[1]).toBe("gate · fail");
  });

  it("a skipped gate says so, and takes no verdict", () => {
    expect(gateReading("off", [{ outcome: "pass", blocking: true }], false)).toEqual([
      "segment-gate-off",
      "gate skipped · gate off",
    ]);
  });
});

describe("the integration lane shows the mode it ran in", () => {
  const ran: TimelineEvents = {
    ...EVENTS,
    integration: {
      seq: 20,
      ts: "2026-10-10T12:00:10.000000Z",
      kind: "ran",
      verdict: "fail",
      reason: null,
    },
  };

  it("under observe it reads would fail, not enforced", () => {
    const drawn = lanes(TRACE, DECISIONS, ran, "observe", {}, CHECKS);
    const integration = drawn.find((l) => l.key === "integration");
    expect(integration?.subtitle).toContain("would fail · not enforced");
  });

  it("under on it is the gate's verdict", () => {
    const drawn = lanes(TRACE, DECISIONS, ran, "on", {}, CHECKS);
    const integration = drawn.find((l) => l.key === "integration");
    expect(integration?.subtitle).toBe("gate on the whole design · fail");
  });

  it("under on it also says what the integration call left unchecked", () => {
    const withUnchecked = [...CHECKS, record(20, null, "unchecked"), record(20, null, "unchecked")];
    const drawn = lanes(TRACE, DECISIONS, ran, "on", {}, withUnchecked);
    const integration = drawn.find((l) => l.key === "integration");
    expect(integration?.subtitle).toBe("gate on the whole design · fail · 2 unchecked");
  });
});

describe("the token figures are the account's, never a sum made here", () => {
  // Deliberately inconsistent: the total is not the sum of the attributions. The card must
  // show the account's own total, so a total recomputed in the view would show here.
  const TOKENS: Tokens = {
    byAttribution: { "session:a": usage(10, 3), "reviewer:b": usage(4, 1) },
    byKind: {
      decomposition: usage(0, 0),
      reviewer: usage(4, 1),
      routing: usage(0, 0),
      session: usage(10, 3),
    },
    total: usage(999, 777),
  };

  it("shows the total the account gave", () => {
    const html = renderToStaticMarkup(<TokensCard tokens={TOKENS} cost={null} source={SOURCE} />);
    const total = html.slice(html.indexOf("the run"));
    expect(total).toContain('<span class="quantity-value">999</span>');
    expect(total).toContain('<span class="quantity-value">777</span>');
    expect(html).toContain("all routing");
  });
});
