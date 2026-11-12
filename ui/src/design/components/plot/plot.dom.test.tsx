// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PAGE_ROWS, Plot, plotOptions, type PlotSpec, PlotTable } from "./Plot";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

/** Fixture data only: made-up values, no record. */
function spec(rows: number): PlotSpec {
  const xs = Array.from({ length: rows }, (_, i) => i / 1000);
  return {
    title: "Fixture",
    x: { label: "time", unit: "s", scale: "linear" },
    xValues: xs,
    y: { label: "position", unit: "m", scale: "linear" },
    series: [{ label: "position", unit: "m", y: xs.map((x) => x * 0.123456789) }],
    source: { id: "fixture", commit: null },
  };
}

let root: Root | null = null;

beforeEach(() => {
  // The page has no canvas here: uPlot draws into one that accepts every call and draws nothing.
  const context = new Proxy(
    {},
    { get: (_t, key) => (key === "measureText" ? () => ({ width: 10 }) : () => undefined) },
  );
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(context as never);
  vi.stubGlobal(
    "Path2D",
    class {
      moveTo() {}
      lineTo() {}
      rect() {}
      arc() {}
      closePath() {}
      bezierCurveTo() {}
      addPath() {}
    },
  );
});

afterEach(() => {
  act(() => {
    root?.unmount();
  });
  root = null;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

function mount(element: ReactNode): HTMLElement {
  const host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  act(() => {
    root?.render(element);
  });
  return host;
}

const button = (host: HTMLElement, words: string) => {
  const found = [...host.querySelectorAll("button")].find((b) => b.textContent === words);
  expect(found, `a button "${words}"`).toBeDefined();
  return found as HTMLButtonElement;
};

describe("the data table shows every row, a page at a time", () => {
  it("pages at the set size and says which rows it shows of how many", () => {
    const host = mount(<PlotTable spec={spec(1200)} />);
    expect(PAGE_ROWS).toBe(500);
    expect(host.querySelectorAll("tbody tr")).toHaveLength(500);
    expect(host.textContent).toContain("Rows 1–500 of 1200");
    expect(button(host, "Previous rows").disabled).toBe(true);
  });

  it("reaches every row through its pages, each once, unrounded", () => {
    const rows = 1200;
    const host = mount(<PlotTable spec={spec(rows)} />);
    const seen: string[] = [];
    for (let page = 0; page < 3; page += 1) {
      for (const tr of host.querySelectorAll("tbody tr"))
        seen.push(tr.querySelector("td")?.textContent ?? "");
      if (page < 2)
        act(() => {
          button(host, "Next rows").click();
        });
    }
    expect(seen).toEqual(Array.from({ length: rows }, (_, i) => String(i / 1000)));
    expect(host.textContent).toContain("Rows 1001–1200 of 1200");
    expect(button(host, "Next rows").disabled).toBe(true);
    expect(host.textContent).toContain(String((1199 / 1000) * 0.123456789));
  });

  it("shows a short table whole, with its row count and no page controls", () => {
    const host = mount(<PlotTable spec={spec(3)} />);
    expect(host.querySelectorAll("tbody tr")).toHaveLength(3);
    expect(host.textContent).toContain("Rows 1–3 of 3");
    expect(host.querySelectorAll("button")).toHaveLength(0);
  });
});

describe("the plot draws no value of its own", () => {
  it("turns uPlot's own legend off, so no cursor readout rounds a value", () => {
    expect(plotOptions(spec(3), 640, 320).legend?.show).toBe(false);
  });

  it("draws the chart with no legend element, hidden from assistive tech", () => {
    const host = mount(<Plot spec={spec(3)} />);
    expect(host.querySelector(".u-legend")).toBeNull();
    expect(host.querySelector(".pg-plot-canvas")?.getAttribute("aria-hidden")).toBe("true");
  });
});
