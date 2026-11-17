import { describe, expect, it } from "vitest";

import { graphViewWords } from "../screens/design-graph/DesignGraph";
import { countOf } from "./count";

describe("a count reads in the right number", () => {
  it("one is singular, any other number plural", () => {
    expect(countOf(1, "edge")).toBe("1 edge");
    expect(countOf(4, "node")).toBe("4 nodes");
    expect(countOf(0, "record")).toBe("0 records");
    expect(countOf(1, "transcript")).toBe("1 transcript");
    expect(countOf(2, "byte")).toBe("2 bytes");
  });

  it("the design graph's view line: four nodes and one edge", () => {
    expect(graphViewWords(4, 1, 5)).toBe("View: 4 nodes and 1 edge at revision r5.");
  });
});
