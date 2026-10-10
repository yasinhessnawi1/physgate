// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it } from "vitest";

import type { GraphDiff, NodeHistory, NodeRecord } from "../../api/graph";
import type { Quantity } from "../../design/quantity";
import { quantityRows, recordedPairDiffers } from "./compare";
import { DiffCard } from "./DiffCard";
import { edgesOf, missingTargets } from "./edges";
import { FIRST_QUANTITIES, Inspector } from "./Inspector";
import { NodesTable } from "./NodesTable";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const SOURCE = { id: "run r-1", commit: "0123456789abcdef" };

function node(
  id: string,
  constrains: string[],
  quantities: [string, Quantity][],
  revision = 3,
): NodeRecord {
  return {
    id,
    kind: "component",
    domain: "electrical",
    owner: "electrical",
    revision,
    constrains,
    quantities,
  };
}

const MANY: [string, Quantity][] = Array.from({ length: FIRST_QUANTITIES + 2 }, (_, i) => [
  `q${String(i)}`,
  { value: i + 0.5, unit: i % 2 === 0 ? "W" : "1" },
]);
const DRIVE = node("electrical.drive", ["electrical.battery", "electrical.typo"], MANY);
const NODES: NodeRecord[] = [
  DRIVE,
  node("electrical.battery", [], [["energy_capacity", { value: 20, unit: "W*h" }]]),
  node("electrical.motor", ["electrical.drive"], [["power_draw", { value: 7.5, unit: "W" }]]),
];
const HISTORY: NodeHistory = {
  nodeId: "electrical.drive",
  baseline: 1,
  history: [
    { revision: 1, op: "create", version: 1, writtenBy: "decomposition", node: DRIVE },
    {
      revision: 3,
      op: "write",
      version: 2,
      writtenBy: { subtask: "drive-c18c5d", attempt: 2 },
      node: DRIVE,
    },
  ],
};

afterEach(() => {
  document.body.innerHTML = "";
});

describe("a node's edges, both ways", () => {
  it("lists what it constrains and what constrains it, and a target the graph lacks", () => {
    const edges = edgesOf("electrical.drive", NODES);
    expect(edges.constrains.map((e) => [e.id, e.node === null])).toEqual([
      ["electrical.battery", false],
      ["electrical.typo", true],
    ]);
    expect(edges.constrainedBy.map((e) => e.id)).toEqual(["electrical.motor"]);
    expect(missingTargets(NODES)).toEqual([["electrical.drive", "electrical.typo"]]);
  });
});

describe("the inspector", () => {
  function render() {
    const host = document.createElement("div");
    document.body.append(host);
    act(() => {
      createRoot(host).render(
        <Inspector
          node={DRIVE}
          nodes={NODES}
          history={{ ok: true, value: HISTORY }}
          source={SOURCE}
          diffHref={(a, b) => `#diff-${String(a)}-${String(b)}`}
        />,
      );
    });
    return host;
  }

  it("shows every quantity with its unit once all are asked for", () => {
    const host = render();
    expect(host.querySelectorAll(".quantity")).toHaveLength(FIRST_QUANTITIES);
    act(() => {
      host.querySelector<HTMLButtonElement>("button")?.click();
    });
    const shown = [...host.querySelectorAll(".quantity")];
    expect(shown).toHaveLength(MANY.length);
    for (const q of shown)
      expect(q.querySelector(".quantity-unit")?.textContent).toMatch(/^(W|dimensionless)$/);
  });

  it("shows its edges both ways, and says when a target is not in the graph", () => {
    const host = render();
    const constrains = host.querySelector('section[aria-label="Constrains"]')?.textContent ?? "";
    expect(constrains).toContain("→ electrical.battery");
    expect(constrains).toContain("→ electrical.typo");
    expect(constrains).toContain("not in the graph at this revision");
    expect(host.querySelector('section[aria-label="Constrained by"]')?.textContent).toContain(
      "← electrical.motor",
    );
  });

  it("shows its history, newest first, each with its writer and a diff to the one before", () => {
    const host = render();
    const entries = [...host.querySelectorAll(".history-entry")].map((li) => li.textContent);
    expect(entries).toHaveLength(2);
    expect(entries[0]).toContain("r3 · drive-c18c5d · attempt 2");
    expect(entries[0]).toContain("Diff r1 → r3");
    expect(entries[1]).toContain("r1 · decomposition");
    expect(entries[1]).toContain("created");
    expect(host.querySelector(".history-entry a")?.getAttribute("href")).toBe("#diff-1-3");
  });

  it("names its source", () => {
    expect(render().querySelector("[data-source]")?.getAttribute("data-source")).toBe(
      "run r-1@0123456",
    );
  });
});

describe("the nodes table lists every node with its edges both ways", () => {
  it("has one row per node", () => {
    const html = renderToStaticMarkup(
      <NodesTable nodes={NODES} source={SOURCE} hrefFor={(id) => `#${id}`} />,
    );
    for (const n of NODES) expect(html).toContain(`>${n.id}</a>`);
    expect(html).toContain("electrical.typo (not in the graph)");
  });
});

describe("the diff", () => {
  it("marks a recorded pair that differs, by value or by unit, and converts nothing", () => {
    expect(recordedPairDiffers({ value: 2, unit: "V" }, { value: 2, unit: "V" })).toBe(false);
    expect(recordedPairDiffers({ value: 2, unit: "V" }, { value: 2000, unit: "mV" })).toBe(true);
    expect(recordedPairDiffers(undefined, { value: 1, unit: "A" })).toBe(true);
    const rows = quantityRows(
      node(
        "a.b",
        [],
        [
          ["x", { value: 1, unit: "A" }],
          ["y", { value: 2, unit: "A" }],
        ],
      ),
      node(
        "a.b",
        [],
        [
          ["x", { value: 1, unit: "A" }],
          ["y", { value: 3, unit: "A" }],
        ],
      ),
    );
    expect(rows.map((r) => [r.name, r.differs])).toEqual([
      ["x", false],
      ["y", true],
    ]);
  });

  it("shows the store's change list and labels its marks as a view", () => {
    const diff: GraphDiff = {
      from: 1,
      to: 3,
      changes: [{ revision: 3, nodeId: "a.b", version: 2, op: "write" }],
      nodes: [
        {
          id: "a.b",
          before: node("a.b", [], [["y", { value: 2, unit: "A" }]], 1),
          after: node("a.b", [], [["y", { value: 3, unit: "A" }]], 3),
        },
      ],
    };
    const html = renderToStaticMarkup(<DiffCard diff={diff} source={SOURCE} />);
    expect(html).toContain("Changes r1 → r3");
    expect(html).toContain("store&#x27;s change list");
    expect(html).toContain("View: rows are marked where the recorded value and unit differ");
    expect(html.match(/diff-row-differs/g)).toHaveLength(1);
  });
});
