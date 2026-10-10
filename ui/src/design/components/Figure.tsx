import type { Quantity as Q } from "../quantity";
import { Quantity } from "./Quantity";
import { type Source, SourceChip, sourceAttribute } from "./SourceChip";
import { type Verdict, VerdictBadge } from "./VerdictBadge";

/** A what-if value: a draft re-run with a changed parameter, never a recorded result. */
export interface WhatIf {
  readonly draft: string;
}

/**
 * A figure: a quantity with its provenance. A recorded figure names its source and may carry a
 * verdict. A what-if figure names its draft and can carry no verdict at all: the type has no
 * place for one, and a value that arrives with one anyway is refused.
 */
export type FigureProps =
  | { readonly q: Q; readonly source: Source; readonly verdict?: Verdict; readonly whatIf?: never }
  | { readonly q: Q; readonly whatIf: WhatIf; readonly source?: never; readonly verdict?: never };

export class WhatIfVerdictError extends Error {
  constructor() {
    super("a what-if value is never given a verdict: nothing judged it");
    this.name = "WhatIfVerdictError";
  }
}

export function Figure(props: FigureProps) {
  if (props.whatIf !== undefined) {
    if ((props as { verdict?: unknown }).verdict !== undefined) throw new WhatIfVerdictError();
    return (
      <span className="figure figure-whatif">
        <WhatIfMarker />
        <span className="whatif-value">
          <Quantity q={props.q} />
        </span>
        <span className="mono whatif-draft">{props.whatIf.draft}</span>
      </span>
    );
  }
  return (
    <span className="figure" data-source={sourceAttribute(props.source)}>
      <Quantity q={props.q} />
      {props.verdict !== undefined && <VerdictBadge verdict={props.verdict} />}
      <SourceChip source={props.source} />
    </span>
  );
}

/** Orange, dashed, with a flask: marks a value or a view as a what-if, never a result. */
export function WhatIfMarker() {
  return (
    <span className="badge whatif-marker">
      <span aria-hidden="true">⚗</span> What-if
    </span>
  );
}

/** Teal dot: the figures beside it come from a run still in progress and are partial. */
export function InProgressBadge() {
  return (
    <span className="badge in-progress">
      <span className="in-progress-dot" aria-hidden="true" /> In progress · partial
    </span>
  );
}
