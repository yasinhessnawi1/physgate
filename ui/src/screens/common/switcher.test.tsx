// @vitest-environment happy-dom
/**
 * The run switcher does not name the run a third time: the header names it; the switcher offers
 * another, and says which is shown only to a screen reader.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { RunListing } from "../../api/records";
import { RunSwitcher } from "./RunSwitcher";

const RUN: RunListing = {
  root: 0,
  name: "bench-12",
  runId: "bench-12",
  manifestId: "m",
  gateMode: "on",
  osLayer: null,
  error: null,
  started: "2026-11-16T19:52:00Z",
};
const LABEL = "Run bench-12 · 16 Nov, 19:52";

describe("the run switcher names the run shown once, for a screen reader", () => {
  it("its visible line offers another run and does not repeat the run's name", () => {
    const host = document.createElement("div");
    host.innerHTML = renderToStaticMarkup(
      <RunSwitcher
        runs={[RUN]}
        chosen={RUN}
        labels={new Map([["0/bench-12", { label: LABEL, detail: "d" }]])}
        area="orchestration"
        slug="run-timeline"
        allShown
        showAll={() => undefined}
      />,
    );
    const summary = host.querySelector("summary");
    const copy = summary?.cloneNode(true) as HTMLElement | undefined;
    for (const hidden of copy?.querySelectorAll(".pg-visually-hidden") ?? []) hidden.remove();
    expect(copy?.textContent.trim()).toBe("Choose another run");
    expect(summary?.querySelector(".pg-visually-hidden")?.textContent).toContain(LABEL);
  });
});
