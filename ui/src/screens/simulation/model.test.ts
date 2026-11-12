import { describe, expect, it } from "vitest";

import type {
  ColumnSummary,
  ListedAttempt,
  RecordSamples,
  SeriesCheck,
  SeriesListing,
  ShownRecord,
} from "../../api/series";
import { axisLabel } from "../../design/components/plot/Plot";
import {
  attemptTag,
  chooseView,
  groupsOf,
  MAX_TRACES,
  plotsOf,
  SamplesMismatchError,
} from "./model";

const SOURCE = { id: "run r-1", commit: "a".repeat(40) };

function listed(
  subtaskId: string,
  attempt: number,
  extra: Partial<ListedAttempt> = {},
): ListedAttempt {
  return {
    kind: "attempt",
    subtaskId,
    attempt,
    ownerRole: "control",
    merged: false,
    rejected: false,
    refusedBy: null,
    sessions: [],
    records: [{ kind: "sealed", recordId: "step_nominal", sessionId: "s" }],
    superseded: [],
    setAside: [],
    checks: [],
    ...extra,
  };
}

const listing = (attempts: ListedAttempt[]): SeriesListing => ({ tolerance: "0.005", attempts });

const q = (search: string) => new URLSearchParams(search);

const gateCheck = (gate: SeriesCheck["gate"]): SeriesCheck => ({
  kind: "check",
  nodeId: "control.loop",
  quantity: "phase_margin",
  recordId: "loop_nominal",
  extract: "phase_margin",
  trace: null,
  sessionId: "s",
  declared: { value: 0.5, unit: "rad" },
  read: null,
  outcome: "unreadable",
  reason: null,
  gate,
});

describe("the attempt the screen opens on", () => {
  const all = listing([
    listed("s0", 1, { records: [] }),
    listed("s1", 1),
    listed("s1", 2, { merged: true }),
    listed("s1", 3),
    listed("s2", 1),
    listed("s2", 2),
  ]);

  it("with no choice, is the first subtask that sealed a record, at its merged attempt", () => {
    expect(chooseView(all, q(""))).toMatchObject({ attempt: { subtaskId: "s1", attempt: 2 } });
  });

  it("is a subtask's latest attempt when none merged", () => {
    expect(chooseView(all, q("subtask=s2"))).toMatchObject({
      attempt: { subtaskId: "s2", attempt: 2 },
    });
  });

  it("is always the address's choice when it names one, and keeps the record it names", () => {
    expect(chooseView(all, q("subtask=s1&attempt=3&record=edge_01"))).toMatchObject({
      attempt: { subtaskId: "s1", attempt: 3 },
      record: "edge_01",
    });
    expect(chooseView(all, q("subtask=s0&attempt=1"))).toMatchObject({
      attempt: { subtaskId: "s0", attempt: 1 },
    });
  });

  it("ignores an address naming nothing the run has, and opens on the first that sealed", () => {
    expect(chooseView(all, q("subtask=nope&attempt=9"))).toMatchObject({
      attempt: { subtaskId: "s1", attempt: 2 },
    });
  });

  it("is nothing for a run with no attempt", () => {
    expect(chooseView(listing([]), q(""))).toBeNull();
  });
});

describe("an attempt's tag comes from a line of the run's log", () => {
  it("reads merged first, then refused before the gate, then not merged, then in progress", () => {
    const merged = listed("s", 1, { merged: true, refusedBy: "series" });
    expect(attemptTag(merged, [merged], true)).toBe("merged");
    const refused = listed("s", 2, {
      refusedBy: "series",
      checks: [gateCheck("refused_before_gate")],
    });
    expect(attemptTag(refused, [refused, listed("s", 3)], true)).toBe("refused-before-gate");
    const rejected = listed("s", 1, { rejected: true });
    expect(attemptTag(rejected, [rejected], true)).toBe("not-merged");
    const earlier = listed("s", 1);
    expect(attemptTag(earlier, [earlier, listed("s", 2)], true)).toBe("not-merged");
    const last = listed("s", 2);
    expect(attemptTag(last, [listed("s", 1), last], true)).toBe("in-progress");
    expect(attemptTag(last, [listed("s", 1), last], false)).toBe("not-merged");
  });

  it("never reads refused before the gate once a gate record names one of its quantities", () => {
    const gated = listed("s", 1, { refusedBy: "series", checks: [gateCheck("not_named")] });
    expect(attemptTag(gated, [gated], false)).toBe("not-merged");
  });
});

const col = (name: string, unit: string, extra: Partial<ColumnSummary> = {}): ColumnSummary => ({
  name,
  unit,
  samples: 3,
  first: 0,
  last: 2,
  smallest: 0,
  largest: 2,
  ...extra,
});

function record(extra: Partial<ShownRecord> = {}): ShownRecord {
  return {
    kind: "shown",
    recordId: "step_nominal",
    sessionId: "s",
    sha256: "d".repeat(64),
    length: 1,
    title: "Step",
    group: "step",
    axis: "time",
    loop: false,
    x: col("time", "s"),
    traces: [col("position", "m"), col("tilt", "rad"), col("error", "m")],
    inputs: [],
    script: { path: "p", sha256: "e", blob: null },
    loaded: [],
    environment: [],
    attemptCommit: null,
    ...extra,
  };
}

const samples = (extra: Partial<RecordSamples> = {}): RecordSamples => ({
  axis: "time",
  x: { name: "time", unit: "s", values: [0, 1, 2] },
  traces: [
    { name: "position", unit: "m", values: [0, 1, 2] },
    { name: "tilt", unit: "rad", values: [0, 0.1, -0.1] },
    { name: "error", unit: "m", values: [1, 0, -1] },
  ],
  ...extra,
});

describe("a record's plots", () => {
  it("draw one plot per unit, in recorded order, with the units in the axis titles", () => {
    const plots = plotsOf(record(), samples(), SOURCE);
    expect(plots.map((p) => p.title)).toEqual(["Position and error", "Tilt"]);
    expect(plots.map((p) => axisLabel(p.spec.x))).toEqual(["Time [s]", "Time [s]"]);
    expect(plots.map((p) => axisLabel(p.spec.y))).toEqual(["Position and error [m]", "Tilt [rad]"]);
    for (const plot of plots)
      for (const s of plot.spec.series) expect(s.unit).toBe(plot.spec.y.unit);
  });

  it("draw a phase in radians as recorded, converting nothing", () => {
    const tilt = plotsOf(record(), samples(), SOURCE)[1];
    expect(tilt?.spec.series[0]?.y).toEqual([0, 0.1, -0.1]);
    expect(tilt?.spec.y.unit).toBe("rad");
  });

  it("draw every sealed sample as it is, and summarise each from the server's summary alone", () => {
    const plots = plotsOf(
      record({ traces: [col("position", "m", { largest: 2.000001 })], x: col("time", "s") }),
      samples({ traces: [{ name: "position", unit: "m", values: [0, 1, 2] }] }),
      SOURCE,
    );
    expect(plots[0]?.spec.xValues).toEqual([0, 1, 2]);
    expect(plots[0]?.spec.series[0]?.y).toEqual([0, 1, 2]);
    // The summary's largest is the server's, not one taken from the samples drawn.
    expect(plots[0]?.summary).toContain("largest 2.000001 m");
  });

  it(`split more than ${String(MAX_TRACES)} traces of one unit across plots, none dropped`, () => {
    const names = Array.from({ length: 10 }, (_, i) => `t${String(i)}`);
    const plots = plotsOf(
      record({ traces: names.map((n) => col(n, "V")) }),
      samples({ traces: names.map((n) => ({ name: n, unit: "V", values: [0, 1, 2] })) }),
      SOURCE,
    );
    expect(plots).toHaveLength(2);
    expect(plots.flatMap((p) => p.spec.series.map((s) => s.label))).toEqual(
      names.map((n) => `T${n.slice(1)}`),
    );
    expect(plots[0]?.spec.series).toHaveLength(MAX_TRACES);
  });

  it("draw a loop's magnitude and phase on a log frequency axis, the magnitude on a log scale", () => {
    const loop = record({
      axis: "frequency",
      loop: true,
      x: col("angular_frequency", "rad/s"),
      traces: [col("loop_magnitude", "dimensionless"), col("loop_phase", "rad")],
    });
    const plots = plotsOf(
      loop,
      {
        axis: "frequency",
        x: { name: "angular_frequency", unit: "rad/s", values: [0.01, 1, 100] },
        traces: [
          { name: "loop_magnitude", unit: "dimensionless", values: [200, 1, 0.0002] },
          { name: "loop_phase", unit: "rad", values: [-1.6, -2.4, -3.1] },
        ],
      },
      SOURCE,
    );
    expect(plots.map((p) => [p.title, p.spec.x.scale, p.spec.y.scale])).toEqual([
      ["Loop magnitude", "log", "log"],
      ["Loop phase", "log", "linear"],
    ]);
    expect(plots.map((p) => p.note)).toEqual([null, null]);
  });

  it("draw a magnitude of zero or below on a linear scale, and say why", () => {
    const loop = record({
      axis: "frequency",
      loop: true,
      x: col("angular_frequency", "rad/s"),
      traces: [col("loop_magnitude", "dimensionless"), col("loop_phase", "rad")],
    });
    const plots = plotsOf(
      loop,
      {
        axis: "frequency",
        x: { name: "angular_frequency", unit: "rad/s", values: [0.01, 1, 100] },
        traces: [
          { name: "loop_magnitude", unit: "dimensionless", values: [200, 0, 0.0002] },
          { name: "loop_phase", unit: "rad", values: [-1.6, -2.4, -3.1] },
        ],
      },
      SOURCE,
    );
    expect(plots[0]?.spec.y.scale).toBe("linear");
    expect(plots[0]?.note).toBe(
      "Drawn on a linear scale: the record holds a magnitude of zero or below.",
    );
  });

  it("draw a frequency record that is not a loop one plot per unit on a log axis, or linear with a reason", () => {
    const sweep = record({
      axis: "frequency",
      x: col("frequency", "Hz"),
      traces: [col("gain", "dimensionless")],
    });
    const at = (x: number[]) =>
      plotsOf(
        sweep,
        {
          axis: "frequency",
          x: { name: "frequency", unit: "Hz", values: x },
          traces: [{ name: "gain", unit: "dimensionless", values: [1, 0.5, 0.25] }],
        },
        SOURCE,
      );
    expect(at([1, 2, 4]).map((p) => [p.spec.x.scale, p.spec.y.scale, p.note])).toEqual([
      ["log", "linear", null],
    ]);
    expect(at([0, 2, 4])[0]?.spec.x.scale).toBe("linear");
    expect(at([0, 2, 4])[0]?.note).toMatch(/frequency of zero or below/);
  });

  it("refuse samples that are not the columns the summary describes", () => {
    expect(() =>
      plotsOf(record(), samples({ traces: samples().traces.slice(0, 2) }), SOURCE),
    ).toThrow(SamplesMismatchError);
    expect(() =>
      plotsOf(record(), samples({ x: { name: "time", unit: "ms", values: [0, 1, 2] } }), SOURCE),
    ).toThrow(SamplesMismatchError);
  });
});

describe("the rail's groups", () => {
  it("keep the role's groups in first-seen order, and list every record not shown last", () => {
    const groups = groupsOf([
      { kind: "unread", recordId: "z", error: "x" },
      record({ recordId: "a", group: "step" }),
      record({ recordId: "b", group: "edge_runs" }),
      record({ recordId: "n", group: null }),
      record({ recordId: "c", group: "step" }),
    ]);
    expect(groups.map((g) => [g.label, g.records.map((r) => r.recordId)])).toEqual([
      ["Step", ["a", "c"]],
      ["Edge runs", ["b"]],
      ["Not grouped", ["n"]],
      ["Records not shown", ["z"]],
    ]);
  });
});
