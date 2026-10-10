import dagre, { type EdgeLabel, type GraphLabel, type NodeLabel } from "@dagrejs/dagre";
import { type KeyboardEvent, useMemo, useRef, useState } from "react";

/** A node of the design graph as the canvas draws it. */
export interface GraphNode {
  readonly id: string;
  readonly kind: string;
  readonly domain: string;
}

/** A `constrains` edge: ``from`` constrains ``to``. */
export interface GraphEdge {
  readonly from: string;
  readonly to: string;
}

export interface Placed {
  readonly node: GraphNode;
  readonly x: number;
  readonly y: number;
}

export interface Layout {
  readonly nodes: readonly Placed[];
  readonly edges: readonly {
    readonly edge: GraphEdge;
    readonly points: readonly { x: number; y: number }[];
  }[];
  readonly width: number;
  readonly height: number;
}

const NODE_MIN_WIDTH = 168;
const NODE_HEIGHT = 44;
/** Room per character of an id in the mono label, and the box's padding around it. */
const CHARACTER_WIDTH = 7.5;
const NODE_PADDING = 24;

/** A node's box is as wide as its id needs, so no id runs out of its box. */
export function nodeWidth(node: GraphNode): number {
  return Math.max(NODE_MIN_WIDTH, Math.ceil(node.id.length * CHARACTER_WIDTH) + NODE_PADDING);
}

/**
 * Lay the graph out in layers, left to right, with dagre. Deterministic: the same nodes and
 * edges, in any order, give the same positions, because both are sorted before layout. An edge
 * to a node the graph does not hold is not drawn.
 */
export function layoutGraph(nodes: readonly GraphNode[], edges: readonly GraphEdge[]): Layout {
  const graph = new dagre.graphlib.Graph<GraphLabel, NodeLabel, EdgeLabel>();
  graph.setGraph({ rankdir: "LR", nodesep: 24, ranksep: 64, marginx: 16, marginy: 16 });
  graph.setDefaultEdgeLabel(() => ({}));
  const sorted = [...nodes].sort((a, b) => a.id.localeCompare(b.id));
  const known = new Set(sorted.map((n) => n.id));
  for (const node of sorted)
    graph.setNode(node.id, { width: nodeWidth(node), height: NODE_HEIGHT });
  const drawn = [...edges]
    .filter((e) => known.has(e.from) && known.has(e.to))
    .sort((a, b) => `${a.from}>${a.to}`.localeCompare(`${b.from}>${b.to}`));
  for (const edge of drawn) graph.setEdge(edge.from, edge.to);
  dagre.layout(graph);
  const label = graph.graph();
  return {
    nodes: sorted.map((node) => {
      const at = graph.node(node.id);
      return { node, x: at.x ?? 0, y: at.y ?? 0 };
    }),
    edges: drawn.map((edge) => ({ edge, points: graph.edge(edge.from, edge.to).points ?? [] })),
    width: label.width ?? 0,
    height: label.height ?? 0,
  };
}

/**
 * The design graph as an SVG. Nodes are buttons in reading order; the arrow keys move along
 * edges (right and down to what a node constrains, left and up to what constrains it). Zoom is
 * a view-box change, so nothing is redrawn and nothing is lost.
 */
export function GraphCanvas({
  nodes,
  edges,
  onSelect,
}: {
  nodes: readonly GraphNode[];
  edges: readonly GraphEdge[];
  onSelect?: (id: string) => void;
}) {
  const layout = useMemo(() => layoutGraph(nodes, edges), [nodes, edges]);
  const [zoom, setZoom] = useState(1);
  const refs = useRef(new Map<string, SVGGElement>());
  const move = (from: string, forward: boolean) => {
    const next = layout.edges.find((e) => (forward ? e.edge.from === from : e.edge.to === from));
    const target = next === undefined ? undefined : forward ? next.edge.to : next.edge.from;
    if (target !== undefined) refs.current.get(target)?.focus();
  };
  const onKey = (id: string) => (event: KeyboardEvent) => {
    if (event.key === "ArrowRight" || event.key === "ArrowDown") move(id, true);
    else if (event.key === "ArrowLeft" || event.key === "ArrowUp") move(id, false);
    else if (event.key === "Enter" || event.key === " ") onSelect?.(id);
    else return;
    event.preventDefault();
  };
  // The SVG is drawn at its own size, so text stays at the type scale; zoom scales the drawing
  // and the frame around it scrolls.
  const width = Math.max(layout.width, 1);
  const height = Math.max(layout.height, 1);
  return (
    <div className="graph">
      <div className="graph-tools">
        <button
          type="button"
          className="button button-browse"
          onClick={() => {
            setZoom((z) => z * 1.25);
          }}
        >
          Zoom in
        </button>
        <button
          type="button"
          className="button button-browse"
          onClick={() => {
            setZoom((z) => z / 1.25);
          }}
        >
          Zoom out
        </button>
      </div>
      <div className="graph-frame">
        <svg
          className="graph-canvas"
          width={width * zoom}
          height={height * zoom}
          viewBox={`0 0 ${String(width)} ${String(height)}`}
          role="group"
          aria-label={`Design graph: ${String(layout.nodes.length)} nodes, ${String(layout.edges.length)} constrains edges`}
        >
          <defs>
            <marker
              id="graph-arrow"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="8"
              markerHeight="8"
              orient="auto"
            >
              <path d="M0,0 L10,5 L0,10 z" className="graph-arrow" />
            </marker>
          </defs>
          {layout.edges.map(({ edge, points }) => (
            <polyline
              key={`${edge.from}>${edge.to}`}
              className="graph-edge"
              points={points.map((p) => `${String(p.x)},${String(p.y)}`).join(" ")}
              markerEnd="url(#graph-arrow)"
            />
          ))}
          {layout.nodes.map(({ node, x, y }) => (
            <g
              key={node.id}
              ref={(el) => {
                if (el === null) refs.current.delete(node.id);
                else refs.current.set(node.id, el);
              }}
              className={`graph-node graph-node-${node.domain}`}
              role="button"
              tabIndex={0}
              aria-label={`${node.id}, ${node.kind}, ${node.domain}`}
              transform={`translate(${String(x - nodeWidth(node) / 2)},${String(y - NODE_HEIGHT / 2)})`}
              onKeyDown={onKey(node.id)}
              onClick={() => onSelect?.(node.id)}
            >
              <rect width={nodeWidth(node)} height={NODE_HEIGHT} rx="8" />
              <text x="10" y="18" className="graph-node-id">
                {node.id}
              </text>
              <text x="10" y="34" className="graph-node-kind">
                {node.kind} · {node.domain}
              </text>
            </g>
          ))}
        </svg>
      </div>
    </div>
  );
}
