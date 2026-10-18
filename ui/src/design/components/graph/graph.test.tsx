// @vitest-environment happy-dom
import type { ReactNode } from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it } from "vitest";

import { WhatIfVerdictError } from "../data/Figure";
import { type CanvasNode, GraphCanvas, layoutGraph, moveFrom, readingOrder } from "./GraphCanvas";
import { GraphLabelError, GraphNode } from "./GraphNode";

const LooseGraphNode = GraphNode as unknown as (props: Record<string, unknown>) => ReactNode;

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

/** a constrains b and c; b and c constrain d. Three layers: a | b, c | d. */
const NODES: CanvasNode[] = ["d.x", "c.x", "b.x", "a.x"].map((id) => ({
  id,
  label: id,
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
    const buttons = [...host.querySelectorAll("button.pg-node")];
    expect(buttons.every((b) => b.tagName === "BUTTON")).toBe(true);
    const order = readingOrder(layoutGraph(NODES, EDGES)).map((p) => p.node.id);
    expect(order[0]).toBe("a.x");
    expect(order.at(-1)).toBe("d.x");
    expect(buttons.map((b) => b.querySelector(".pg-node-id")?.textContent)).toEqual(order);
  });

  it("each name their domain in words, and the selected one says it is pressed", () => {
    const host = render("b.x");
    expect(host.querySelectorAll(".pg-domain.pg-domain-electrical")).toHaveLength(4);
    const pressed = [...host.querySelectorAll('button[aria-pressed="true"]')];
    expect(pressed.map((b) => b.querySelector(".pg-node-id")?.textContent)).toEqual(["b.x"]);
  });
});

describe("a node leads with its label, and the label is never cut", () => {
  const long =
    "Main loop sample rate of the motor-control firmware, measured at the encoder interrupt";

  it("requires a label, in the type and at run time", () => {
    // @ts-expect-error a node without a label a person can read.
    expect(<GraphNode id="a.b" domain="control" />).toBeTruthy();
    expect(() => renderToStaticMarkup(<GraphNode id="a.b" label=" " domain="control" />)).toThrow(
      GraphLabelError,
    );
  });

  it("puts the label first, the key beneath it whole, and the whole label in its name", () => {
    const html = renderToStaticMarkup(
      <GraphNode id="firmware.main_loop.sample_rate" label={long} domain="firmware" />,
    );
    expect(html.indexOf("pg-node-label")).toBeLessThan(html.indexOf("pg-node-id"));
    expect(html).toContain(`<span class="pg-node-label">${long}</span>`);
    expect(html).toContain('<span class="pg-node-id">firmware.main_loop.sample_rate</span>');
  });

  it("a what-if node carries no verdict, in the type and at run time", () => {
    // @ts-expect-error a what-if node takes no verdict.
    expect(<GraphNode id="a.b" label="A" domain="control" whatIf verdict="pass" />).toBeTruthy();
    expect(() =>
      renderToStaticMarkup(
        <LooseGraphNode
          {...{ id: "a", label: "A", domain: "control", whatIf: true, verdict: "pass" }}
        />,
      ),
    ).toThrow(WhatIfVerdictError);
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
    const first = host.querySelector<HTMLButtonElement>("button.pg-node");
    first?.focus();
    act(() => {
      first?.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    });
    expect(document.activeElement?.querySelector(".pg-node-id")?.textContent).toBe(top);
  });
});
