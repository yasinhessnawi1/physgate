// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { GraphCanvas, layoutGraph, moveFrom, readingOrder } from "./GraphCanvas";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

/** a constrains b and c; b and c constrain d. Three layers: a | b, c | d. */
const NODES = ["d.x", "c.x", "b.x", "a.x"].map((id) => ({
  id,
  kind: "component",
  domain: "electrical",
}));
const EDGES = [
  { from: "a.x", to: "b.x" },
  { from: "a.x", to: "c.x" },
  { from: "b.x", to: "d.x" },
  { from: "c.x", to: "d.x" },
];

afterEach(() => {
  document.body.innerHTML = "";
});

function render(selected: string | null = null) {
  const host = document.createElement("div");
  document.body.append(host);
  act(() => {
    createRoot(host).render(<GraphCanvas nodes={NODES} edges={EDGES} selected={selected} />);
  });
  return host;
}

describe("the graph's nodes", () => {
  it("are real buttons, in reading order: layer by layer, top to bottom", () => {
    const host = render();
    const buttons = [...host.querySelectorAll("button.graph-node")];
    expect(buttons.every((b) => b.tagName === "BUTTON")).toBe(true);
    const order = readingOrder(layoutGraph(NODES, EDGES)).map((p) => p.node.id);
    expect(order[0]).toBe("a.x");
    expect(order.at(-1)).toBe("d.x");
    expect(buttons.map((b) => b.querySelector(".graph-node-id")?.textContent)).toEqual(order);
  });

  it("each name their domain in words, and the selected one says it is pressed", () => {
    const host = render("b.x");
    expect(host.querySelectorAll(".domain-chip.domain-electrical")).toHaveLength(4);
    const pressed = [...host.querySelectorAll('button[aria-pressed="true"]')];
    expect(pressed.map((b) => b.querySelector(".graph-node-id")?.textContent)).toEqual(["b.x"]);
  });
});

describe("the arrow keys move along edges", () => {
  const layout = layoutGraph(NODES, EDGES);
  // b and c share a layer; which is on top is the layout's to say, and reading order follows it.
  const order = readingOrder(layout).map((p) => p.node.id);
  const [top = "", below = ""] = order.filter((id) => id === "b.x" || id === "c.x");

  it("→ follows an edge forward and ← back", () => {
    expect(moveFrom(layout, "a.x", "ArrowRight", null)?.to).toBe(top);
    expect(moveFrom(layout, "d.x", "ArrowLeft", null)?.to).toBe(top);
    expect(moveFrom(layout, "d.x", "ArrowRight", null)).toBeNull();
  });

  it("↓ and ↑ step among the siblings the last edge reached", () => {
    const right = moveFrom(layout, "a.x", "ArrowRight", null);
    expect(right?.via).toEqual({ node: "a.x", forward: true });
    expect(moveFrom(layout, top, "ArrowDown", right?.via ?? null)?.to).toBe(below);
    expect(moveFrom(layout, below, "ArrowDown", right?.via ?? null)?.to).toBe(top);
    expect(moveFrom(layout, top, "ArrowUp", right?.via ?? null)?.to).toBe(below);
  });

  it("moves the focus in the page", () => {
    const host = render();
    const first = host.querySelector<HTMLButtonElement>("button.graph-node");
    first?.focus();
    act(() => {
      first?.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    });
    expect(document.activeElement?.querySelector(".graph-node-id")?.textContent).toBe(top);
  });
});
