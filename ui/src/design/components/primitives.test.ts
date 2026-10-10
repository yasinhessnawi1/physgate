import { describe, expect, it } from "vitest";

import { layoutGraph, nodeWidth } from "./GraphCanvas";
import { axisLabel, checkPlot, type PlotSpec, PlotSpecError } from "./Plot";

/** Fixture data only: no series record exists yet, so nothing here is a recorded result. */
const STEP: PlotSpec = {
  title: "Fixture step response",
  x: { label: "time", unit: "s", scale: "linear" },
  xValues: [0, 0.5, 1, 1.5],
  y: { label: "position", unit: "m", scale: "linear" },
  series: [{ label: "fixture", unit: "m", y: [0, 0.06, 0.09, 0.1] }],
  source: { id: "fixture", commit: null },
};

describe("a plot has a unit on every axis and converts nothing", () => {
  it("labels each axis with what it measures and its unit", () => {
    expect(axisLabel(STEP.x)).toBe("time [s]");
    expect(axisLabel({ label: "gain", unit: "1", scale: "log" })).toBe("gain [dimensionless]");
  });

  it("accepts a well-formed spec", () => {
    expect(checkPlot(STEP)).toBe(STEP);
  });

  it("refuses a series in another unit than its axis", () => {
    const mixed = { ...STEP, series: [{ label: "in mm", unit: "mm", y: [0, 60, 90, 100] }] };
    expect(() => checkPlot(mixed)).toThrow(PlotSpecError);
  });

  it("refuses an axis without a unit", () => {
    expect(() => checkPlot({ ...STEP, y: { ...STEP.y, unit: " " } })).toThrow(/no unit/);
  });

  it("refuses a log axis holding zero, and a series of the wrong length", () => {
    expect(() => checkPlot({ ...STEP, x: { ...STEP.x, scale: "log" } })).toThrow(/log axis/);
    expect(() => checkPlot({ ...STEP, series: [{ label: "short", unit: "m", y: [0] }] })).toThrow(
      /one value per x/,
    );
  });
});

describe("the graph layout", () => {
  const nodes = [
    { id: "power.budget", kind: "requirement", domain: "cross" },
    { id: "motor.left", kind: "component", domain: "mechanical" },
    { id: "control.loop", kind: "module", domain: "control" },
  ];
  const edges = [
    { from: "motor.left", to: "power.budget" },
    { from: "motor.left", to: "control.loop" },
    { from: "motor.left", to: "missing.node" },
  ];

  it("is the same whatever order the nodes and edges arrive in", () => {
    const one = layoutGraph(nodes, edges);
    const two = layoutGraph([...nodes].reverse(), [...edges].reverse());
    expect(two).toEqual(one);
  });

  it("places every node and draws no edge to a node the graph does not hold", () => {
    const layout = layoutGraph(nodes, edges);
    expect(layout.nodes.map((p) => p.node.id)).toEqual([
      "control.loop",
      "motor.left",
      "power.budget",
    ]);
    expect(layout.edges.map((e) => e.edge.to).sort()).toEqual(["control.loop", "power.budget"]);
    expect(layout.width).toBeGreaterThan(0);
  });

  it("makes a box wide enough for its id", () => {
    const long = {
      id: "electrical.node_s2_5e2ad0_with_a_long_tail",
      kind: "component",
      domain: "electrical",
    };
    expect(nodeWidth(long)).toBeGreaterThan(long.id.length * 7);
    // A node box is 184 px wide, as the design draws it.
    expect(nodeWidth({ id: "a.b", kind: "module", domain: "control" })).toBe(184);
  });
});
