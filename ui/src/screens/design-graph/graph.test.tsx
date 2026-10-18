// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { GraphDiff, NodeRecord } from "../../api/graph";
import type { RunConfig } from "../../api/records";
import type { GateCheck } from "../../api/run";
import type { Quantity } from "../../design/quantity";
import { quantityRows, recordedPairDiffers } from "./compare";
import { DiffView } from "./DiffView";
import { edgesOf, missingTargets } from "./edges";
import { NodeInspector } from "./NodeInspector";
import { NodesTable } from "./NodesTable";
import { latestChecksOf, nodeVerdicts } from "./verdicts";

const SOURCE = { id: "run r-1", commit: "0123456789abcdef" };

function node(
  id: string,
  constrains: string[],
  quantities: [string, Quantity][],
  revision = 3,
  domain: NodeRecord["domain"] = "electrical",
): NodeRecord {
  return {
    id,
    kind: "component",
    domain,
    owner: "electrical",
    revision,
    provenance: Object.fromEntries(
      quantities.map(([name]) => [name, { source: "datasheet", writtenBy: "electrical" }]),
    ),
    constrains,
    quantities,
  };
}

const CONFIG: RunConfig = {
  manifestId: "m",
  runId: "r-1",
  gateMode: "on",
  harnessCommit: "0123456789abcdef",
  auth: "api_key",
  briefSha256: "a",
  seed: 7,
  roleModels: { electrical: "claude-sonnet-5" },
  decompositionModel: "claude-sonnet-5",
  reviewerModels: {},
  osLayer: null,
};

function check(seq: number, node: string | null, outcome: GateCheck["outcome"]): GateCheck {
  return {
    seq,
    subtask: "s1",
    attempt: 1,
    name: "power",
    check: 4,
    ts: null,
    scope: "module",
    mode: "on",
    outcome,
    blocking: true,
    value: null,
    node,
    evaluated: null,
    reviewerHadPassed: null,
    expected: null,
    message: "power drawn exceeds the supply",
    details: { form: "power", evaluated: null, quantities: [], low: null, high: null },
  };
}

const DRIVE = node(
  "electrical.drive",
  ["electrical.battery", "electrical.typo"],
  [["power_draw", { value: 7.5, unit: "W" }]],
);
const NODES: NodeRecord[] = [
  DRIVE,
  node("electrical.battery", [], [["energy_capacity", { value: 20, unit: "W*h" }]]),
  node("electrical.motor", ["electrical.drive"], [["power_draw", { value: 7.5, unit: "W" }]]),
];

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

describe("a node's verdict is the gate's latest record of it, and none is never a pass", () => {
  it("reads the latest gate line that names the node", () => {
    const checks = [
      check(10, "electrical.drive", "pass"),
      check(20, "electrical.drive", "fail"),
      check(20, "electrical.drive", "unchecked"),
      check(20, "electrical.battery", "unchecked"),
      check(30, null, "pass"),
    ];
    const verdicts = nodeVerdicts(checks);
    expect(verdicts.get("electrical.drive")).toBe("fail");
    expect(verdicts.get("electrical.battery")).toBe("unchecked");
    expect(verdicts.has("electrical.motor")).toBe(false);
    expect(latestChecksOf("electrical.drive", checks).map((c) => c.seq)).toEqual([20, 20]);
  });
});

describe("the node inspector", () => {
  const html = renderToStaticMarkup(
    <NodeInspector
      node={DRIVE}
      nodes={NODES}
      checks={[check(20, "electrical.drive", "fail"), check(20, "electrical.drive", "unchecked")]}
      config={CONFIG}
      history={{
        ok: true,
        value: {
          nodeId: "electrical.drive",
          baseline: 1,
          history: [
            { revision: 1, op: "create", version: 1, writtenBy: "decomposition", node: DRIVE },
            {
              revision: 3,
              op: "write",
              version: 2,
              writtenBy: { subtask: "s1", attempt: 2 },
              node: DRIVE,
            },
          ],
        },
      }}
      historyRoute="/x"
      onHistoryAgain={() => undefined}
      source={SOURCE}
      runLabel="Run 16 Oct, 13:58"
      diffHref={(a, b) => `#d${String(a)}-${String(b)}`}
      nodeHref={(id) => `#${id}`}
    />,
  );

  it("leads with the label, the key copyable beneath", () => {
    expect(html.indexOf("Drive")).toBeLessThan(html.indexOf("electrical.drive"));
    expect(html).toContain("Copy electrical.drive");
  });

  it("names each quantity in words, with who set it as visible text, and its source", () => {
    expect(html).toContain("Power draw");
    expect(html).toContain("Set by");
    expect(html).toContain("Electrical agent");
    expect(html).toContain("claude-sonnet-5");
    expect(html).toContain("pg-source");
  });

  it("lists its gate checks, unchecked after the separator", () => {
    expect(html.indexOf("pg-verdict-fail")).toBeLessThan(html.indexOf("pg-sep"));
    expect(html.indexOf("pg-sep")).toBeLessThan(html.indexOf("pg-verdict-unchecked"));
  });

  it("shows its edges both ways, and a target not in the graph", () => {
    expect(html).toContain("not in the graph at this revision");
    expect(html).toContain("Motor");
  });

  it("shows its history, newest first, each with its writer and what changed", () => {
    expect(html.indexOf("r3")).toBeLessThan(html.indexOf("Created at revision r1"));
    expect(html).toContain("What changed r1 → r3");
    expect(html).toContain("Decomposition agent");
  });
});

describe("under a domain filter the table still resolves every edge over the whole graph", () => {
  it("never calls a node of another domain missing, and keeps its incoming edges", () => {
    const all = [
      node("firmware.main", ["electrical.loop"], [], 2, "firmware"),
      node("electrical.loop", ["mechanical.plant"], []),
      node("mechanical.plant", [], [], 2, "mechanical"),
    ];
    const html = renderToStaticMarkup(
      <NodesTable
        nodes={all.filter((n) => n.domain === "electrical")}
        all={all}
        verdicts={new Map()}
        gateMode="on"
        source={SOURCE}
        hrefFor={(id) => `#${id}`}
      />,
    );
    expect(html).not.toContain("not in the graph");
    expect(html).toContain("firmware.main");
    expect(html).toContain("mechanical.plant");
    expect(html.match(/<tr>/g)).toHaveLength(2);
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

  it("shows the store's change list, led by the node's label, and labels its marks as a view", () => {
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
    const html = renderToStaticMarkup(<DiffView diff={diff} source={SOURCE} />);
    expect(html).toContain("What changed from r1 → r3");
    expect(html).toContain("store&#x27;s own change list");
    expect(html).toContain("View: rows are marked");
    expect(html.match(/pg-differs"/g)).toHaveLength(1);
  });
});
