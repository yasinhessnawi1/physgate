import { describe, expect, it } from "vitest";

import { CHORD_MS, chordTarget } from "./shortcuts";

const RUN = new URLSearchParams({ run: "0/drive-on" });

describe("shortcuts are two keys, never one", () => {
  it("g then g, t or q go to the graph, the timeline and the approval queue", () => {
    const g = { key: "g", at: 100 };
    expect(chordTarget(g, "g", 200, RUN)).toBe("#/orchestration/design-graph?run=0%2Fdrive-on");
    expect(chordTarget(g, "t", 200, RUN)).toBe("#/orchestration/run-timeline?run=0%2Fdrive-on");
    expect(chordTarget(g, "q", 200, RUN)).toBe("#/collaboration/approval-queue?run=0%2Fdrive-on");
  });

  it("a single key, another first key, or a slow second key is nothing", () => {
    expect(chordTarget(null, "g", 100, RUN)).toBeNull();
    expect(chordTarget({ key: "t", at: 100 }, "g", 200, RUN)).toBeNull();
    expect(chordTarget({ key: "g", at: 0 }, "t", CHORD_MS + 1, RUN)).toBeNull();
    expect(chordTarget({ key: "g", at: 0 }, "x", 10, RUN)).toBeNull();
  });
});
