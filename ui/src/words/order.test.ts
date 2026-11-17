import { describe, expect, it } from "vitest";

import { runListing } from "../api/records";
import { orderRuns } from "./runs";

describe("runs are ordered so a person can tell them apart", () => {
  it("newest start first, never as text; a run with no start known last, numbers as numbers", () => {
    const runs = [
      { name: "bench-1", started: "2026-11-01T19:48:00Z" },
      { name: "bench-10", started: "2026-11-13T10:00:00Z" },
      { name: "bench-12", started: "2026-11-16T19:52:00Z" },
      { name: "bench-3", started: "2026-11-03T09:54:00Z" },
      { name: "bench-y10", started: null },
      { name: "bench-y9", started: null },
    ];
    expect(orderRuns(runs).map((r) => r.name)).toEqual([
      "bench-12",
      "bench-10",
      "bench-3",
      "bench-1",
      "bench-y9",
      "bench-y10",
    ]);
  });

  it("reads each run's start from the run list", () => {
    const [run] = runListing({
      runs: [
        {
          root: 0,
          name: "bench-12",
          run_id: "bench-12",
          manifest_id: "m",
          gate_mode: "on",
          os_layer: null,
          started: "2026-11-16T19:52:01.000000Z",
        },
      ],
    });
    expect(run?.started).toBe("2026-11-16T19:52:01.000000Z");
  });
});
