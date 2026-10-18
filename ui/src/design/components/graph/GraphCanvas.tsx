import dagre, { type EdgeLabel, type GraphLabel, type NodeLabel } from "@dagrejs/dagre";
import { type KeyboardEvent, useLayoutEffect, useMemo, useRef, useState } from "react";

import { Button } from "../actions/Button";
import type { Domain } from "../data/DomainChip";
import type { GateMode } from "../verdict/GateMode";
import type { Verdict } from "../verdict/verdict";
import { GraphNode } from "./GraphNode";

/** A node of the design graph as the canvas draws it. */
export interface CanvasNode {
  readonly id: string;
  /** What a person reads first; until the schema carries labels, the key as written. */
  readonly label: string;
  readonly kind: string;
  readonly domain: Domain;
  /** One line under the key, from the record (for example "7 quantities"). */
  readonly summary?: string;
  /** The latest verdict the gate recorded on the node, if any. */
  readonly verdict?: Verdict;
  /** The verdict covers part of the node: some of its records were left unchecked. */
  readonly partUnchecked?: boolean;
  /** Up to a few quantities to show on the card, as recorded. */
  readonly quantities?: readonly {
    readonly name: string;
    readonly value: number | string;
    readonly unit: string;
  }[];
}

/** A `constrains` edge: ``from`` constrains ``to``. */
export interface CanvasEdge {
  readonly from: string;
  readonly to: string;
}

export interface Placed {
  readonly node: CanvasNode;
  readonly x: number;
  readonly y: number;
  readonly height: number;
}

/** Layers left to right, or, where the room is too narrow for that, top to bottom. */
export type Direction = "LR" | "TB";

export interface Layout {
  readonly direction: Direction;
  readonly nodes: readonly Placed[];
  readonly edges: readonly {
    readonly edge: CanvasEdge;
    readonly points: readonly { x: number; y: number }[];
  }[];
  readonly width: number;
  readonly height: number;
}

/** Every card is this wide; its label and key wrap inside it and the card grows downward. */
export const NODE_WIDTH = 216;
/** The least a card is tall. */
export const NODE_MIN_HEIGHT = 80;
/** No zoom shrinks a node, a button, below the 44 px a target must keep. */
const TOUCH_MIN = 44;
// One pixel of margin: the scaled height is a float, and 44 can render as 43.99997.
export const LEAST_ZOOM = (TOUCH_MIN + 1) / NODE_MIN_HEIGHT;
/** The least the graph is shrunk to open with every node whole; below it the text is too small. */
export const READABLE_ZOOM = 0.8;

/** Characters per line of the label and of the key, and the height of each line, for a first guess. */
const LABEL_CHARS = 24;
const KEY_CHARS = 28;
const LABEL_LINE = 18;
const KEY_LINE = 16;
const CARD_REST = 46;

/**
 * A first guess at a card's height from its text, before the browser has drawn it. The canvas
 * then measures every card and lays the graph out again with the heights it measured, so a guess
 * that is short never leaves a card overlapping another.
 */
export function guessHeight(node: CanvasNode): number {
  const lines = (text: string, per: number) => Math.max(1, Math.ceil(text.length / per));
  return Math.max(
    NODE_MIN_HEIGHT,
    lines(node.label, LABEL_CHARS) * LABEL_LINE +
      lines(node.id, KEY_CHARS) * KEY_LINE +
      (node.quantities?.length ?? 0) * KEY_LINE +
      (node.verdict === undefined ? 0 : LABEL_LINE + 6) +
      CARD_REST,
  );
}

/**
 * Lay the graph out in layers, left to right, with dagre. Deterministic: the same nodes, edges
 * and card heights, in any order, give the same positions, because all are sorted before layout.
 * An edge to a node the graph does not hold is not drawn; the views list it in words instead.
 */
export function layoutGraph(
  nodes: readonly CanvasNode[],
  edges: readonly CanvasEdge[],
  heights: ReadonlyMap<string, number> = new Map(),
  direction: Direction = "LR",
): Layout {
  const graph = new dagre.graphlib.Graph<GraphLabel, NodeLabel, EdgeLabel>();
  graph.setGraph({ rankdir: direction, nodesep: 24, ranksep: 56, marginx: 16, marginy: 16 });
  graph.setDefaultEdgeLabel(() => ({}));
  const sorted = [...nodes].sort((a, b) => a.id.localeCompare(b.id));
  const known = new Set(sorted.map((n) => n.id));
  const heightOf = (node: CanvasNode) =>
    Math.max(NODE_MIN_HEIGHT, heights.get(node.id) ?? guessHeight(node));
  for (const node of sorted) graph.setNode(node.id, { width: NODE_WIDTH, height: heightOf(node) });
  const drawn = [...edges]
    .filter((e) => known.has(e.from) && known.has(e.to))
    .sort((a, b) => `${a.from}>${a.to}`.localeCompare(`${b.from}>${b.to}`));
  for (const edge of drawn) graph.setEdge(edge.from, edge.to);
  dagre.layout(graph);
  const label = graph.graph();
  return {
    direction,
    nodes: sorted.map((node) => {
      const at = graph.node(node.id);
      return { node, x: at.x ?? 0, y: at.y ?? 0, height: heightOf(node) };
    }),
    edges: drawn.map((edge) => ({ edge, points: graph.edge(edge.from, edge.to).points ?? [] })),
    width: label.width ?? 0,
    height: label.height ?? 0,
  };
}

/** Where a placed node's layer is: its x when layers run left to right, its y when top down. */
function layerOf(layout: Layout, p: Placed): number {
  return Math.round(layout.direction === "LR" ? p.x : p.y);
}

/** Where a node sits within its layer. */
function acrossOf(layout: Layout, p: Placed): number {
  return layout.direction === "LR" ? p.y : p.x;
}

/** The nodes in reading order: layer by layer, then along each layer. */
export function readingOrder(layout: Layout): readonly Placed[] {
  return [...layout.nodes].sort(
    (a, b) =>
      layerOf(layout, a) - layerOf(layout, b) ||
      acrossOf(layout, a) - acrossOf(layout, b) ||
      a.node.id.localeCompare(b.node.id),
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
          .filter((p) => here !== undefined && layerOf(layout, p) === layerOf(layout, here))
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

/** Whether two height maps hold the same heights, to the pixel. */
function sameHeights(a: ReadonlyMap<string, number>, b: ReadonlyMap<string, number>): boolean {
  if (a.size !== b.size) return false;
  for (const [id, h] of a) if (Math.abs((b.get(id) ?? -1) - h) > 0.5) return false;
  return true;
}

/**
 * The design graph: edges drawn in SVG, and each node a real button laid over them, in reading
 * order. The arrow keys move along edges; Enter or a click selects. Each card is measured once
 * drawn and the graph laid out again with its real height, so a label that wraps grows its card
 * and never runs into another. Zoom scales the drawing and the frame scrolls.
 */
export function GraphCanvas({
  nodes,
  edges,
  selected = null,
  onSelect,
  gateMode,
}: {
  readonly nodes: readonly CanvasNode[];
  readonly edges: readonly CanvasEdge[];
  readonly selected?: string | null;
  readonly onSelect?: (id: string) => void;
  /** The mode the nodes' verdicts were recorded under. */
  readonly gateMode?: GateMode;
}) {
  const [heights, setHeights] = useState<ReadonlyMap<string, number>>(new Map());
  // The room the frame gives. Layers run left to right; where that cannot open with every node
  // whole at a readable size and top to bottom can, they run top to bottom instead.
  const [room, setRoom] = useState(0);
  const layout = useMemo(() => {
    const across = layoutGraph(nodes, edges, heights, "LR");
    if (room <= 0 || across.width * READABLE_ZOOM <= room) return across;
    const down = layoutGraph(nodes, edges, heights, "TB");
    return down.width < across.width ? down : across;
  }, [nodes, edges, heights, room]);
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
  // Measure every card as the browser draws it, and whenever one changes size (a font loading, a
  // density switch); lay out again only when a height differs from the one used.
  useLayoutEffect(() => {
    if (typeof ResizeObserver === "undefined") return;
    const measure = () => {
      const measured = new Map<string, number>();
      for (const [id, button] of refs.current) {
        const h = button.offsetHeight;
        if (h > 0) measured.set(id, h);
      }
      setHeights((current) =>
        measured.size > 0 && !sameHeights(measured, current) ? measured : current,
      );
    };
    const observer = new ResizeObserver(measure);
    for (const button of refs.current.values()) observer.observe(button);
    return () => {
      observer.disconnect();
    };
  }, [layout]);
  const width = Math.max(layout.width, 1);
  const height = Math.max(layout.height, 1);
  // Open with every node whole: shrunk to the frame's width if a readable zoom does it, and
  // otherwise at the graph's start, at full size.
  // The fit is taken again whenever the frame changes width (an inspector opening beside it).
  const frame = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const node = frame.current;
    if (node === null) return;
    const fit = () => {
      const wide = node.clientWidth;
      setRoom(wide);
      const ratio = wide / width;
      setZoom(wide > 0 && ratio < 1 && ratio >= READABLE_ZOOM ? ratio : 1);
      node.scrollLeft = 0;
    };
    if (typeof ResizeObserver === "undefined") {
      fit();
      return;
    }
    const observer = new ResizeObserver(fit);
    observer.observe(node);
    return () => {
      observer.disconnect();
    };
  }, [width]);

  const touches = (e: CanvasEdge) =>
    selected !== null && (e.from === selected || e.to === selected);
  // An edge between two domains is drawn dashed: the design's cross-domain constraint.
  const domainOf = new Map(nodes.map((n) => [n.id, n.domain]));
  const crosses = (e: CanvasEdge) => domainOf.get(e.from) !== domainOf.get(e.to);
  return (
    <div className="pg-graph">
      <div className="pg-graph-tools">
        <Button
          onClick={() => {
            setZoom((z) => z * 1.25);
          }}
        >
          Zoom in
        </Button>
        <Button
          onClick={() => {
            setZoom((z) => Math.max(z / 1.25, LEAST_ZOOM));
          }}
        >
          Zoom out
        </Button>
      </div>
      <div className="pg-graph-frame pg-ground" ref={frame}>
        <div className="pg-graph-stage" style={{ width: width * zoom, height: height * zoom }}>
          <div
            className="pg-graph-layer"
            role="group"
            aria-label={`Design graph: ${String(layout.nodes.length)} nodes, ${String(layout.edges.length)} constrains edges`}
            style={{ width, height, transform: `scale(${String(zoom)})` }}
          >
            <svg
              className="pg-graph-canvas"
              width={width}
              height={height}
              viewBox={`0 0 ${String(width)} ${String(height)}`}
              aria-hidden="true"
            >
              <defs>
                <marker
                  id="pg-arrow"
                  viewBox="0 0 10 10"
                  refX="9"
                  refY="5"
                  markerWidth="7"
                  markerHeight="7"
                  orient="auto"
                >
                  <path d="M0,0 L10,5 L0,10 z" className="pg-arrow" />
                </marker>
                <marker
                  id="pg-arrow-on"
                  viewBox="0 0 10 10"
                  refX="9"
                  refY="5"
                  markerWidth="7"
                  markerHeight="7"
                  orient="auto"
                >
                  <path d="M0,0 L10,5 L0,10 z" className="pg-arrow-on" />
                </marker>
              </defs>
              {layout.edges.map(({ edge, points }) => (
                <polyline
                  key={`${edge.from}>${edge.to}`}
                  className={[
                    "pg-edge",
                    crosses(edge) ? "pg-edge-cross" : null,
                    touches(edge) ? "pg-edge-on" : null,
                  ]
                    .filter((c) => c !== null)
                    .join(" ")}
                  data-cross={crosses(edge) ? "true" : "false"}
                  points={points.map((p) => `${String(p.x)},${String(p.y)}`).join(" ")}
                  markerEnd={touches(edge) ? "url(#pg-arrow-on)" : "url(#pg-arrow)"}
                />
              ))}
            </svg>
            {ordered.map(({ node, x, y, height: h }) => (
              <GraphNode
                key={node.id}
                id={node.id}
                label={node.label}
                domain={node.domain}
                summary={node.summary === undefined ? node.kind : `${node.kind} · ${node.summary}`}
                {...(node.quantities === undefined ? {} : { quantities: node.quantities })}
                {...(node.verdict === undefined
                  ? {}
                  : { verdict: node.verdict, partUnchecked: node.partUnchecked === true })}
                {...(gateMode === undefined ? {} : { gateMode })}
                selected={node.id === selected}
                buttonRef={(el: HTMLButtonElement | null) => {
                  if (el === null) refs.current.delete(node.id);
                  else refs.current.set(node.id, el);
                }}
                style={{ left: x - NODE_WIDTH / 2, top: y - h / 2, width: NODE_WIDTH }}
                onKeyDown={onKey(node.id)}
                onClick={() => onSelect?.(node.id)}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
