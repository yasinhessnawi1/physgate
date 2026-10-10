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

describe("a two-key shortcut survives a change of route between its keys", () => {
  it("g, then the route changes, then t: still goes to the timeline", () => {
    window.location.hash = "#/orchestration/gate-checks?run=0/a";
    const host = document.createElement("div");
    document.body.append(host);
    act(() => {
      createRoot(host).render(<Shell views={[]} />);
    });
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "g" }));
    });
    // The route changes between the two keys, as a link or another shortcut would change it.
    act(() => {
      window.location.hash = "#/orchestration/gate-checks?run=0/b";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "t" }));
    });
    expect(window.location.hash).toBe("#/orchestration/run-timeline?run=0%2Fb");
  });
});
