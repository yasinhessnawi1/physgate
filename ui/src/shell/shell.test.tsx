// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { VIEWS } from "../views/registry";
import { AREAS } from "./areas";
import { parseHash } from "./route";
import { Shell } from "./Shell";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

afterEach(() => {
  document.body.innerHTML = "";
  window.location.hash = "";
});

describe("the view registry", () => {
  it("is not empty, and every view names one of the five areas", () => {
    expect(VIEWS.length).toBeGreaterThan(0);
    const areas = new Set(AREAS.map((a) => a.id));
    for (const view of VIEWS) expect(areas.has(view.area)).toBe(true);
  });

  it("has no two views of one slug in one area", () => {
    const keys = VIEWS.map((v) => `${v.area}/${v.slug}`);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("puts the smoke page under Home", () => {
    expect(VIEWS.find((v) => v.slug === "run-records")?.area).toBe("home");
  });
});

describe("the shell", () => {
  it("lists Home and the four focus areas in order", () => {
    expect(AREAS.map((a) => a.name)).toEqual([
      "Home",
      "Concept & architecture",
      "Agentic orchestration",
      "Simulation",
      "Human–AI collaboration",
    ]);
  });

  it("shows an area with no views as an empty state, not a blank page", () => {
    window.location.hash = "#/simulation";
    const host = document.createElement("div");
    document.body.append(host);
    act(() => {
      createRoot(host).render(<Shell views={[]} />);
    });
    expect(host.querySelector(".state-empty")?.textContent).toContain("No views in this area yet");
    expect(host.querySelector(".topbar-area")?.textContent).toContain("Simulation");
  });

  it("parses a route from the hash", () => {
    const route = parseHash("#/home/run-records?run=0/run-on");
    expect([route.area, route.view, route.query.get("run")]).toEqual([
      "home",
      "run-records",
      "0/run-on",
    ]);
    expect(parseHash("").area).toBe("home");
  });
});
