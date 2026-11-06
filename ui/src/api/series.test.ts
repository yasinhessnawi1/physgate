import { describe, expect, it } from "vitest";

import {
  attemptRecords,
  attemptRoute,
  type ListedAttempt,
  recordRoute,
  recordSamples,
  type SeriesCheck,
  seriesListing,
  seriesRoute,
  type ShownRecord,
} from "./series";

/** A checked quantity as the listing sends it. */
const check = (extra: Record<string, unknown> = {}) => ({
  node_id: "control.loop",
  quantity: "phase_margin",
  record_id: "loop_nominal",
  extract: "phase_margin",
  trace: null,
  session_id: "sess-1",
  declared_value: 0.5534885189031078,
  declared_unit: "rad",
  read_value: 0.5534885189031078,
  read_unit: "rad",
  outcome: "agrees",
  reason: null,
  gate: "not_named",
  ...extra,
});

/** An attempt as the listing sends it. */
const attempt = (extra: Record<string, unknown> = {}) => ({
  subtask_id: "s1-af41ca",
  attempt: 1,
  owner_role: "control",
  merged: true,
  rejected: false,
  refused_by: null,
  sessions: [{ session_id: "sess-1", outcome: "completed", attempt_commit: "a".repeat(40) }],
  records: [
    {
      record_id: "loop_nominal",
      session_id: "sess-1",
      sha256: "b".repeat(64),
      length: 100,
      script: "s.py",
      script_sha256: "c".repeat(64),
    },
  ],
  superseded: [],
  set_aside: [],
  checks: [check()],
  ...extra,
});

const summary = (name: string, unit: string, extra: Record<string, unknown> = {}) => ({
  name,
  unit,
  samples: 3,
  first: 0,
  last: 1,
  smallest: 0,
  largest: 1.390625,
  ...extra,
});

/** A record the attempt's answer shows, as the server sends it. */
const shown = (extra: Record<string, unknown> = {}) => ({
  record_id: "step_nominal",
  session_id: "sess-1",
  sha256: "d".repeat(64),
  length: 900,
  title: "Stand-in loop, unit step at gain 2, not the robot",
  group: "step",
  axis: "time",
  loop: false,
  x: summary("time", "s", { last: 10 }),
  traces: [summary("position", "m"), summary("error", "m")],
  inputs: {
    seed: { value: "9223372036854775807", unit: "dimensionless" },
    step: { value: 1.0, unit: "m" },
  },
  producer: {
    script: { path: "control/sim.py", sha256: "e".repeat(64), blob: "f".repeat(40) },
    loaded: [{ path: "control/model.py", sha256: "1".repeat(64), blob: null }],
  },
  environment: [{ path: "/usr/lib/python3.12/json/__init__.py", sha256: "2".repeat(64) }],
  attempt_commit: "a".repeat(40),
  ...extra,
});

const samples = (extra: Record<string, unknown> = {}) => ({
  format: "physgate-series/1",
  id: "step_nominal",
  title: "Stand-in",
  group: "step",
  axis: "time",
  x: { name: "time", unit: "s", values: [0, 0.5, 1] },
  traces: [{ name: "position", unit: "m", values: [0, 0.5, 1] }],
  inputs: { seed: { value: 9223372036854775807, unit: "dimensionless" } },
  producer: {},
  ...extra,
});

function readAttempt(value: unknown): ListedAttempt {
  const listed = seriesListing({ tolerance: "0.005", attempts: [value] }).attempts[0];
  expect(listed?.kind, JSON.stringify(listed)).toBe("attempt");
  return listed as ListedAttempt;
}

function readCheck(value: unknown): SeriesCheck {
  const found = readAttempt(attempt({ checks: [value] })).checks[0];
  expect(found?.kind, JSON.stringify(found)).toBe("check");
  return found as SeriesCheck;
}

function readShown(value: unknown): ShownRecord {
  const found = attemptRecords({ subtask_id: "s1", attempt: 1, records: [value] }).records[0];
  expect(found?.kind, JSON.stringify(found)).toBe("shown");
  return found as ShownRecord;
}

describe("the routes", () => {
  it("name the run's listing, an attempt and a record under the run", () => {
    const base = "/api/runs/0/run-series";
    expect(seriesRoute(base)).toBe("/api/runs/0/run-series/series");
    expect(attemptRoute(base, "s1-af41ca", 2)).toBe("/api/runs/0/run-series/series/s1-af41ca/2");
    expect(recordRoute(base, "s1-af41ca", 2, "loop_nominal")).toBe(
      "/api/runs/0/run-series/series/s1-af41ca/2/loop_nominal",
    );
  });
});

describe("the run's listing", () => {
  it("reads an attempt, its sessions, records, checks and the tolerance as sent", () => {
    const listing = seriesListing({ tolerance: "0.005", attempts: [attempt()] });
    expect(listing.tolerance).toBe("0.005");
    const read = readAttempt(attempt());
    expect(read.subtaskId).toBe("s1-af41ca");
    expect(read.ownerRole).toBe("control");
    expect(read.merged).toBe(true);
    expect(read.sessions).toEqual([
      { sessionId: "sess-1", outcome: "completed", attemptCommit: "a".repeat(40) },
    ]);
    expect(read.records).toEqual([
      { kind: "sealed", recordId: "loop_nominal", sessionId: "sess-1" },
    ]);
    expect(readCheck(check()).declared).toEqual({ value: 0.5534885189031078, unit: "rad" });
  });

  it("ignores a field it does not draw, at every level", () => {
    const extra = { a_field_added_later: { nested: [1, 2] } };
    const listing = seriesListing({
      tolerance: "0.005",
      attempts: [
        attempt({
          ...extra,
          sessions: [{ session_id: "s", outcome: "completed", attempt_commit: null, ...extra }],
          records: [{ record_id: "r", session_id: "s", ...extra }],
          superseded: [{ record_id: "r", session_id: "s0", ...extra }],
          set_aside: [
            { session_id: "s", kind: "refused", name: "n.json", reason: "why", ...extra },
          ],
          checks: [
            check({
              ...extra,
              gate: [
                {
                  seq: 9,
                  check: 2,
                  name: "magnitude",
                  outcome: "unchecked",
                  gate_mode: "on",
                  blocking: false,
                  expected: null,
                  low: null,
                  high: null,
                  ...extra,
                },
              ],
            }),
          ],
        }),
      ],
      ...extra,
    });
    const read = listing.attempts[0];
    expect(read?.kind).toBe("attempt");
    if (read?.kind !== "attempt") return;
    expect(read.records.every((r) => r.kind !== "unread")).toBe(true);
    expect(read.superseded.every((r) => r.kind !== "unread")).toBe(true);
    expect(read.setAside.every((r) => r.kind !== "unread")).toBe(true);
    expect(read.checks.every((r) => r.kind !== "unread")).toBe(true);
  });

  it("keeps what refused an attempt, an outcome, a gate mode and a set-aside kind open, as written", () => {
    const read = readAttempt(
      attempt({
        refused_by: "interface",
        set_aside: [{ session_id: "s", kind: "quarantined", name: "x", reason: "a new reason" }],
        checks: [
          check({
            outcome: "partly",
            gate: [
              {
                seq: 1,
                check: 2,
                name: "a_new_check",
                outcome: "deferred",
                gate_mode: "advisory",
                blocking: false,
                expected: null,
                low: null,
                high: null,
              },
            ],
          }),
          check({ gate: "a_new_gate_state" }),
        ],
      }),
    );
    expect(read.refusedBy).toBe("interface");
    expect(read.setAside[0]).toMatchObject({ kind: "set-aside", how: "quarantined" });
    const [first, second] = read.checks;
    expect(first).toMatchObject({ kind: "check", outcome: "partly" });
    expect(first?.kind === "check" && first.gate).toEqual([
      expect.objectContaining({ outcome: "deferred", gateMode: "advisory", name: "a_new_check" }),
    ]);
    expect(second).toMatchObject({ kind: "check", gate: "a_new_gate_state" });
  });

  it("refuses one malformed check or attempt alone, and keeps the rest", () => {
    const listing = seriesListing({
      tolerance: "0.005",
      attempts: [
        attempt({
          checks: [
            check(),
            check({ declared_unit: "" }),
            check({ read_value: 1, read_unit: null }),
          ],
        }),
        attempt({ attempt: "two" }),
        attempt({ attempt: 3 }),
      ],
    });
    expect(listing.attempts.map((a) => a.kind)).toEqual(["attempt", "unread", "attempt"]);
    const first = listing.attempts[0];
    expect(first?.kind === "attempt" && first.checks.map((c) => c.kind)).toEqual([
      "check",
      "unread",
      "unread",
    ]);
    const unread = listing.attempts[1];
    expect(unread?.kind === "unread" && unread.error).toMatch(/attempt number/);
  });

  it("refuses the whole answer only when it is not a listing of attempts", () => {
    expect(() => seriesListing(null)).toThrow();
    expect(() => seriesListing([])).toThrow();
    expect(() => seriesListing({ tolerance: "0.005" })).toThrow();
    expect(() => seriesListing({ tolerance: "0.005", attempts: {} })).toThrow();
  });

  it("admits an integer beyond a number's exact range as the numeral the server sent", () => {
    const read = readCheck(check({ declared_value: "9223372036854775807", declared_unit: "1" }));
    expect(read.declared).toEqual({ value: "9223372036854775807", unit: "1" });
  });

  it("reads a gate record's range as quantities, and a quantity nothing was read off as none", () => {
    const read = readCheck(
      check({
        read_value: null,
        read_unit: null,
        outcome: "unreadable",
        reason: "names the record loop_nominal, which this attempt did not seal",
        gate: [
          {
            seq: 40,
            check: 2,
            name: "magnitude",
            outcome: "fail",
            gate_mode: "on",
            blocking: true,
            expected: "within the range",
            low: { value: 0.1, unit: "m" },
            high: { value: 1.0, unit: "m" },
          },
        ],
      }),
    );
    expect(read.read).toBeNull();
    expect(read.reason).toMatch(/did not seal/);
    expect(read.gate).toEqual([
      {
        seq: 40,
        check: 2,
        name: "magnitude",
        outcome: "fail",
        gateMode: "on",
        blocking: true,
        expected: "within the range",
        low: { value: 0.1, unit: "m" },
        high: { value: 1, unit: "m" },
      },
    ]);
  });
});

describe("an attempt's records", () => {
  it("reads a shown record's summaries, inputs and provenance as sent", () => {
    const read = readShown(shown());
    expect(read.title).toBe("Stand-in loop, unit step at gain 2, not the robot");
    expect(read.x).toMatchObject({ name: "time", unit: "s", samples: 3, first: 0, last: 10 });
    expect(read.traces.map((t) => t.name)).toEqual(["position", "error"]);
    expect(read.inputs).toEqual([
      ["seed", { value: "9223372036854775807", unit: "dimensionless" }],
      ["step", { value: 1, unit: "m" }],
    ]);
    expect(read.script.blob).toBe("f".repeat(40));
    expect(read.loaded[0]?.blob).toBeNull();
    expect(read.environment).toHaveLength(1);
  });

  it("ignores a field it does not draw on a record, a summary and the producer", () => {
    const extra = { later: true };
    const read = readShown(
      shown({
        ...extra,
        x: summary("time", "s", extra),
        traces: [summary("position", "m", extra)],
        producer: {
          script: { path: "p", sha256: "e".repeat(64), blob: null, ...extra },
          loaded: [],
          ...extra,
        },
      }),
    );
    expect(read.traces).toHaveLength(1);
  });

  it("reads a refused record as its own row, with the seal and what was found", () => {
    const answer = attemptRecords({
      subtask_id: "s1",
      attempt: 1,
      records: [
        shown(),
        {
          record_id: "edge_01",
          session_id: "sess-1",
          sha256: "d".repeat(64),
          length: 900,
          record: "series/s1/1/sess-1/edge_01.json",
          refused: "seal",
          error: "the record's bytes are not the ones its session sealed",
          sealed_sha256: "d".repeat(64),
          sealed_length: 900,
          found_sha256: "9".repeat(64),
        },
        {
          record_id: "edge_02",
          session_id: "sess-1",
          sha256: "d".repeat(64),
          length: 900,
          record: "series/s1/1/sess-1/edge_02.json",
          refused: "a_new_kind",
          error: "why",
          sealed_sha256: "d".repeat(64),
          sealed_length: 900,
          found_length: 12,
        },
      ],
    });
    expect(answer.records.map((r) => r.kind)).toEqual(["shown", "refused", "refused"]);
    expect(answer.records[1]).toMatchObject({
      refused: "seal",
      foundSha256: "9".repeat(64),
      foundLength: null,
      sealedLength: 900,
    });
    expect(answer.records[2]).toMatchObject({ refused: "a_new_kind", foundLength: 12 });
  });

  it("refuses one malformed record alone, by its id, and keeps the rest", () => {
    const answer = attemptRecords({
      subtask_id: "s1",
      attempt: 1,
      records: [
        shown({ record_id: "no_unit", x: summary("time", "") }),
        shown({ record_id: "bad_axis", axis: "space" }),
        shown({ record_id: "infinite", traces: [summary("p", "m", { largest: "Infinity" })] }),
        shown({ record_id: "short", traces: [summary("p", "m", { samples: 2 })] }),
        shown({ record_id: "bare_input", inputs: { seed: 7 } }),
        "not a row",
        shown(),
      ],
    });
    expect(answer.records.map((r) => [r.kind, r.recordId])).toEqual([
      ["unread", "no_unit"],
      ["unread", "bad_axis"],
      ["unread", "infinite"],
      ["unread", "short"],
      ["unread", "bare_input"],
      ["unread", null],
      ["shown", "step_nominal"],
    ]);
  });

  it("refuses the whole answer only when it holds no list of records", () => {
    expect(() => attemptRecords({ subtask_id: "s1", attempt: 1 })).toThrow();
    expect(() => attemptRecords("records")).toThrow();
  });
});

describe("a record's sealed bytes", () => {
  it("reads its axis and every column as recorded, a negative zero kept", () => {
    const read = recordSamples(
      JSON.parse(
        '{"axis": "time", "x": {"name": "time", "unit": "s", "values": [0, 1e-05, 2]}, "traces": [{"name": "position", "unit": "m", "values": [-0.0, 0.123456789, 1]}], "extra": 1}',
      ),
    );
    expect(read.x.values).toEqual([0, 1e-5, 2]);
    expect(Object.is(read.traces[0]?.values[0], -0)).toBe(true);
    expect(read.traces[0]?.values[1]).toBe(0.123456789);
  });

  it("never reads the record's inputs, so an integer it cannot hold exactly is never shown from here", () => {
    expect(Object.keys(recordSamples(samples()))).toEqual(["axis", "x", "traces"]);
  });

  it.each([
    ["a column without a unit", { x: { name: "time", unit: "", values: [0, 1, 2] } }],
    ["a value that is not a number", { traces: [{ name: "p", unit: "m", values: [0, "1", 2] }] }],
    ["a trace of another length", { traces: [{ name: "p", unit: "m", values: [0, 1] }] }],
    ["no trace", { traces: [] }],
    ["an axis that is neither", { axis: "space" }],
  ])("refuses %s", (_what, change) => {
    expect(() => recordSamples(samples(change))).toThrow();
  });
});
