import type { CSSProperties, KeyboardEvent, Ref } from "react";

import { type Domain, DomainChip } from "../data/DomainChip";
import { WhatIfVerdictError } from "../data/Figure";
import { Quantity } from "../data/Quantity";
import { ProvenanceTag } from "../parts/ProvenanceTag";
import { WhatIfMarker } from "../status/WhatIfMarker";
import type { Verdict } from "../verdict/verdict";
import { VerdictBadge } from "../verdict/VerdictBadge";

interface Common {
  /** The node's key, shown under the label, smaller, in mono, whole. */
  readonly id: string;
  /** Required: what a person reads first. It wraps onto further lines and is never cut. */
  readonly label: string;
  readonly domain: Domain;
  /** One line under the key, from the record: the node's kind and a summary. */
  readonly summary?: string;
  readonly quantities?: readonly {
    readonly name: string;
    readonly value: number | string;
    readonly unit: string;
  }[];
  /** A part decision: have (solid ink rail), make (striped), find (plain). */
  readonly provenance?: "have" | "make" | "find";
  readonly selected?: boolean;
  readonly onClick?: () => void;
  readonly onKeyDown?: (event: KeyboardEvent<HTMLButtonElement>) => void;
  readonly buttonRef?: Ref<HTMLButtonElement>;
  /** Position on a canvas: React's style property, set through the CSSOM. */
  readonly style?: CSSProperties;
}

/** A recorded node may carry a verdict; a node that exists only in a what-if draft cannot. */
export type GraphNodeProps = Common &
  (
    | { readonly verdict?: Verdict; readonly whatIf?: false }
    | { readonly whatIf: true; readonly verdict?: never }
  );

export class GraphLabelError extends Error {
  constructor(id: string) {
    super(`a graph node leads with a label a person can read: ${id} has none`);
    this.name = "GraphLabelError";
  }
}

/**
 * A design-state node as a real button: its label first, wrapping as long as it needs, the key
 * beneath it in mono, the domain in words, then its quantities and its verdict or what-if mark.
 */
export function GraphNode(props: GraphNodeProps) {
  const {
    id,
    label,
    domain,
    summary,
    quantities = [],
    provenance,
    selected = false,
    onClick,
    onKeyDown,
    buttonRef,
    style,
  } = props;
  if ((label as unknown) === undefined || label.trim() === "") throw new GraphLabelError(id);
  const whatIf = props.whatIf === true;
  if (whatIf && (props as { verdict?: unknown }).verdict !== undefined)
    throw new WhatIfVerdictError();
  const className = [
    "pg-node",
    whatIf ? "pg-node-whatif" : null,
    provenance === "have" ? "pg-node-have" : null,
    provenance === "make" ? "pg-node-make" : null,
  ]
    .filter((c) => c !== null)
    .join(" ");
  const verdict = whatIf ? undefined : props.verdict;
  return (
    <button
      ref={buttonRef}
      type="button"
      className={className}
      aria-pressed={selected}
      onClick={onClick}
      onKeyDown={onKeyDown}
      style={style}
    >
      <span className="pg-node-label">{label}</span>
      <span className="pg-node-id">{id}</span>
      <span className="pg-node-head">
        <DomainChip domain={domain} />
        {summary !== undefined && <span className="pg-node-summary">{summary}</span>}
      </span>
      {quantities.length > 0 && (
        <span className="pg-node-qs">
          {quantities.map((q) => (
            <span key={q.name} className="pg-node-q">
              <span>{q.name}</span>
              <Quantity value={q.value} unit={q.unit} whatIf={whatIf} />
            </span>
          ))}
        </span>
      )}
      {(whatIf || verdict !== undefined || provenance !== undefined) && (
        <span className="pg-node-foot">
          {whatIf ? (
            <WhatIfMarker />
          ) : verdict !== undefined ? (
            <VerdictBadge verdict={verdict} />
          ) : (
            <span />
          )}
          {provenance !== undefined && <ProvenanceTag kind={provenance} />}
        </span>
      )}
    </button>
  );
}
