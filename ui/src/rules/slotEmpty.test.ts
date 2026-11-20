import { describe, expect, it, vi } from "vitest";

import { VIEWS } from "../screens/registry";

// The build without the thesis folder: its slot resolves to no view at all.
vi.mock("virtual:physgate-thesis-views", () => ({ THESIS_VIEWS: [] }));

describe("with the thesis slot empty", () => {
  it("the product lists no thesis view, and every product view as before", () => {
    expect(VIEWS.map((v) => v.slug)).toEqual([
      "overview",
      "approval-queue",
      "run-timeline",
      "design-graph",
      "gate-checks",
      "run-records",
      "library",
      "glossary",
      "series",
      "settings",
    ]);
    expect(VIEWS.filter((v) => v.group === "analyse").map((v) => v.slug)).toEqual(["series"]);
  });
});
