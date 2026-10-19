import { describe, expect, it } from "vitest";

import { guessHeight, layoutGraph, NODE_MIN_HEIGHT, NODE_WIDTH } from "./GraphCanvas";

describe("the graph layout", () => {
  const nodes = [
    { id: "power.budget", label: "power.budget", kind: "requirement", domain: "cross" as const },
    { id: "motor.left", label: "motor.left", kind: "component", domain: "mechanical" as const },
    { id: "control.loop", label: "control.loop", kind: "module", domain: "control" as const },
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
    const heights = new Map([["motor.left", 140]]);
    expect(layoutGraph([...nodes].reverse(), [...edges].reverse(), heights)).toEqual(
      layoutGraph(nodes, edges, heights),
    );
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

  it("gives a card the height its label needs, and never less than a target's", () => {
    const short = { ...nodes[0], label: "Bus" } as (typeof nodes)[number];
    const long = {
      ...short,
      label:
        "The supply bus voltage the motor driver and every sensor share, at the battery terminals",
      id: "electrical.supply.bus_voltage_at_the_battery_terminals",
    };
    expect(guessHeight(short)).toBe(NODE_MIN_HEIGHT);
    expect(guessHeight(long)).toBeGreaterThan(NODE_MIN_HEIGHT);
    expect(NODE_WIDTH).toBe(216);
    // A verdict over part of the node says so under its badge, which is one more line to guess.
    const judged = { ...long, verdict: "pass" as const };
    expect(guessHeight({ ...judged, partUnchecked: true })).toBeGreaterThan(guessHeight(judged));
  });

  it("lays out with the heights the browser measured, keeping the cards apart", () => {
    const tall = new Map([
      ["control.loop", 200],
      ["power.budget", 200],
    ]);
    const layout = layoutGraph(nodes, edges, tall);
    const [a, b] = layout.nodes.filter((p) => p.node.id !== "motor.left");
    expect(a?.height).toBe(200);
    if (a === undefined || b === undefined) throw new Error("two nodes in one layer");
    expect(Math.abs(a.y - b.y)).toBeGreaterThanOrEqual(200);
  });
});
