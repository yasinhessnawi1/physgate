import dagre, { type EdgeLabel, type GraphLabel, type NodeLabel } from "@dagrejs/dagre";
import { type KeyboardEvent, useMemo, useRef, useState } from "react";

/** A node of the design graph as the canvas draws it. */
export interface GraphNode {
  readonly id: string;
  readonly kind: string;
  readonly domain: string;
  /** One line under the id, from the record (for example "7 quantities"). */
  readonly summary?: string;
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

const NODE_MIN_WIDTH = 184;
/** No zoom shrinks a node, a button, below the 44 px a target must keep. */
const TOUCH_MIN = 44;
export const NODE_HEIGHT = 80;
// One pixel of margin: the scaled height is a float, and 44 can render as 43.99997.
export const LEAST_ZOOM = (TOUCH_MIN + 1) / NODE_HEIGHT;
/** Room per character of an id in the mono label, and the box's padding around it. */
const CHARACTER_WIDTH = 8;
const NODE_PADDING = 28;

/** A node's box is as wide as its id needs, so no id runs out of its box. */
export function nodeWidth(node: GraphNode): number {
  return Math.max(NODE_MIN_WIDTH, Math.ceil(node.id.length * CHARACTER_WIDTH) + NODE_PADDING);
}

/**
 * Lay the graph out in layers, left to right, with dagre. Deterministic: the same nodes and
 * edges, in any order, give the same positions, because both are sorted before layout. An edge
 * to a node the graph does not hold is not drawn; the views list it in words instead.
 */
export function layoutGraph(nodes: readonly GraphNode[], edges: readonly GraphEdge[]): Layout {
  const graph = new dagre.graphlib.Graph<GraphLabel, NodeLabel, EdgeLabel>();
  graph.setGraph({ rankdir: "LR", nodesep: 24, ranksep: 72, marginx: 16, marginy: 16 });
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

/** The nodes in reading order: layer by layer, left to right, then top to bottom. */
export function readingOrder(layout: Layout): readonly Placed[] {
  return [...layout.nodes].sort(
    (a, b) => Math.round(a.x) - Math.round(b.x) || a.y - b.y || a.node.id.localeCompare(b.node.id),
  );
}

/** Where a key takes the focus, and the edge it was reached by. */
export interface Move {
  readonly to: string;
  /** The node the last edge was followed from, and in which direction. */
  readonly via: { readonly node: string; readonly forward: boolean } | null;
}

/**
 * Arrow keys move along edges. → goes to the first node ``from`` constrains, ← to the first that
 * constrains it, in reading order. ↓ and ↑ step among the siblings the last edge reached: the
 * other nodes the same node constrains (or is constrained by). With no edge followed yet, the
 * siblings are the node's layer.
 */
export function moveFrom(layout: Layout, from: string, key: string, via: Move["via"]): Move | null {
  const order = readingOrder(layout).map((p) => p.node.id);
  const rank = (id: string) => order.indexOf(id);
  const byReading = (ids: string[]) => [...new Set(ids)].sort((a, b) => rank(a) - rank(b));
  const targets = (id: string) =>
    byReading(layout.edges.filter((e) => e.edge.from === id).map((e) => e.edge.to));
  const sources = (id: string) =>
    byReading(layout.edges.filter((e) => e.edge.to === id).map((e) => e.edge.from));
  if (key === "ArrowRight" || key === "ArrowLeft") {
    const forward = key === "ArrowRight";
    const next = (forward ? targets(from) : sources(from))[0];
    return next === undefined ? null : { to: next, via: { node: from, forward } };
  }
  if (key === "ArrowDown" || key === "ArrowUp") {
    let siblings: string[];
    if (via !== null) siblings = via.forward ? targets(via.node) : sources(via.node);
    else {
      const here = layout.nodes.find((p) => p.node.id === from);
      siblings = byReading(
        layout.nodes
          .filter((p) => here !== undefined && Math.round(p.x) === Math.round(here.x))
          .map((p) => p.node.id),
      );
    }
    const at = siblings.indexOf(from);
    if (at < 0 || siblings.length < 2) return null;
    const step = key === "ArrowDown" ? 1 : siblings.length - 1;
    const to = siblings[(at + step) % siblings.length];
    return to === undefined ? null : { to, via };
  }
  return null;
}

/**
 * The design graph: edges drawn in SVG, and each node a real button laid over them, in reading
 * order. The arrow keys move along edges; Enter or a click selects. Zoom scales the drawing and
 * the frame around it scrolls, so nothing is redrawn and nothing is lost.
 */
export function GraphCanvas({
  nodes,
  edges,
  selected = null,
  onSelect,
}: {
  nodes: readonly GraphNode[];
  edges: readonly GraphEdge[];
  selected?: string | null;
  onSelect?: (id: string) => void;
}) {
  const layout = useMemo(() => layoutGraph(nodes, edges), [nodes, edges]);
  const ordered = useMemo(() => readingOrder(layout), [layout]);
  const [zoom, setZoom] = useState(1);
  const via = useRef<Move["via"]>(null);
  const refs = useRef(new Map<string, HTMLButtonElement>());
  const onKey = (id: string) => (event: KeyboardEvent<HTMLButtonElement>) => {
    const move = moveFrom(layout, id, event.key, via.current);
    if (move === null) return;
    event.preventDefault();
    via.current = move.via;
    refs.current.get(move.to)?.focus();
  };
  const width = Math.max(layout.width, 1);
  const height = Math.max(layout.height, 1);

  const touches = (e: GraphEdge) => selected !== null && (e.from === selected || e.to === selected);
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
            setZoom((z) => Math.max(z / 1.25, LEAST_ZOOM));
          }}
        >
          Zoom out
        </button>
      </div>
      <div className="graph-frame">
        <div className="graph-stage" style={{ width: width * zoom, height: height * zoom }}>
          <div
            className="graph-layer"
            role="group"
            aria-label={`Design graph: ${String(layout.nodes.length)} nodes, ${String(layout.edges.length)} constrains edges`}
            style={{ width, height, transform: `scale(${String(zoom)})` }}
          >
            <svg
              className="graph-canvas"
              width={width}
              height={height}
              viewBox={`0 0 ${String(width)} ${String(height)}`}
              aria-hidden="true"
            >
              <defs>
                <marker
                  id="graph-arrow"
                  viewBox="0 0 10 10"
                  refX="9"
                  refY="5"
                  markerWidth="7"
                  markerHeight="7"
                  orient="auto"
                >
                  <path d="M0,0 L10,5 L0,10 z" className="graph-arrow" />
                </marker>
                <marker
                  id="graph-arrow-on"
                  viewBox="0 0 10 10"
                  refX="9"
                  refY="5"
                  markerWidth="7"
                  markerHeight="7"
                  orient="auto"
                >
                  <path d="M0,0 L10,5 L0,10 z" className="graph-arrow-on" />
                </marker>
              </defs>
              {layout.edges.map(({ edge, points }) => (
                <polyline
                  key={`${edge.from}>${edge.to}`}
                  className={touches(edge) ? "graph-edge graph-edge-on" : "graph-edge"}
                  points={points.map((p) => `${String(p.x)},${String(p.y)}`).join(" ")}
                  markerEnd={touches(edge) ? "url(#graph-arrow-on)" : "url(#graph-arrow)"}
                />
              ))}
            </svg>
            {ordered.map(({ node, x, y }) => (
              <button
                key={node.id}
                ref={(el) => {
                  if (el === null) refs.current.delete(node.id);
                  else refs.current.set(node.id, el);
                }}
                type="button"
                className={node.id === selected ? "graph-node graph-node-selected" : "graph-node"}
                aria-pressed={node.id === selected}
                style={{
                  left: x - nodeWidth(node) / 2,
                  top: y - NODE_HEIGHT / 2,
                  width: nodeWidth(node),
                  height: NODE_HEIGHT,
                }}
                onKeyDown={onKey(node.id)}
                onClick={() => onSelect?.(node.id)}
              >
                <DomainChip domain={node.domain} />
                <span className="graph-node-id mono">{node.id}</span>
                <span className="graph-node-summary">
                  {node.kind}
                  {node.summary !== undefined && ` · ${node.summary}`}
                </span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

/** A node's domain: its word, in the domain's colour, outlined. */
export function DomainChip({ domain }: { domain: string }) {
  return <span className={`domain-chip domain-${domain}`}>{domain}</span>;
}
