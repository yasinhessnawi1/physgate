import { describe, expect, it } from "vitest";

import { graphAt, nodeAt } from "./graph";

const node = (quantity: Record<string, unknown>) => ({
  revision: 4,
  node: {
    id: "control.loop",
    kind: "component",
    domain: "control",
    owner_role: "control",
    constrains: [],
    quantities: { phase_margin: quantity },
  },
});

const PHASE = {
  value: 0.5534885189031078,
  unit: "rad",
  source: "read off the session's own record",
  written_by: "control",
};

describe("a quantity's record, as the node names it", () => {
  it("is read when the quantity names one", () => {
    const read = nodeAt(
      node({ ...PHASE, series: { record: "loop_nominal", extract: "phase_margin" } }),
    );
    expect(read.provenance.phase_margin?.series).toEqual({
      record: "loop_nominal",
      extract: "phase_margin",
      trace: null,
    });
    const timed = nodeAt(
      node({ ...PHASE, series: { record: "step_nominal", extract: "max_abs", trace: "position" } }),
    );
    expect(timed.provenance.phase_margin?.series?.trace).toBe("position");
  });

  it("is none when the quantity names none", () => {
    expect(nodeAt(node(PHASE)).provenance.phase_margin?.series).toBeNull();
  });

  it("is none, and the node still read, when the reference is malformed", () => {
    for (const series of [
      "loop_nominal",
      { extract: "phase_margin" },
      { record: 7, extract: "phase_margin" },
      { record: "loop_nominal" },
      { record: "loop_nominal", extract: "max", trace: 3 },
      [],
    ]) {
      const read = nodeAt(node({ ...PHASE, series }));
      expect(read.quantities).toEqual([
        ["phase_margin", { value: 0.5534885189031078, unit: "rad" }],
      ]);
      expect(read.provenance.phase_margin?.series).toBeNull();
    }
  });

  it("ignores a field it does not draw, and the graph still reads", () => {
    const graph = graphAt({
      head_revision: 4,
      nodes: {
        "control.loop": node({
          ...PHASE,
          series: { record: "loop_nominal", extract: "phase_margin", later: { a: 1 } },
          a_field_added_later: true,
        }),
      },
    });
    expect(graph.nodes[0]?.provenance.phase_margin?.series?.record).toBe("loop_nominal");
  });
});
