import type { Verdict } from "../verdict/verdict";
import { VerdictBadge } from "../verdict/VerdictBadge";
import { WhatIfMarker } from "../status/WhatIfMarker";
import { Quantity } from "./Quantity";
import { type Source, sourceAttribute } from "./source";
import { SourceChip } from "./SourceChip";

/** A what-if value: a draft re-run with a changed parameter, never a recorded result. */
export interface WhatIf {
  readonly draft: string;
}

interface Shown {
  readonly value: number | string;
  readonly unit: string;
  readonly size?: "md" | "lg";
  readonly partial?: boolean;
}

/**
 * A figure: a quantity with its provenance. A recorded figure names its source (a missing one is
 * the dashed "no source" chip) and may carry a verdict. A what-if figure names its draft and can
 * carry no verdict: the type has no place for one, and a value that arrives with one is refused.
 */
export type FigureProps =
  | (Shown & {
      readonly source: Source | null;
      readonly verdict?: Verdict;
      readonly whatIf?: never;
    })
  | (Shown & { readonly whatIf: WhatIf; readonly source?: never; readonly verdict?: never });

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
      <span className="pg-figure pg-figure-whatif">
        <WhatIfMarker />
        <Quantity
          value={props.value}
          unit={props.unit}
          whatIf
          {...(props.size === undefined ? {} : { size: props.size })}
        />
        <span className="pg-source pg-source-missing pg-source-draft">{props.whatIf.draft}</span>
      </span>
    );
  }
  const { source } = props;
  return (
    <span
      className="pg-figure"
      {...(source === null ? {} : { "data-source": sourceAttribute(source) })}
    >
      <Quantity
        value={props.value}
        unit={props.unit}
        {...(props.size === undefined ? {} : { size: props.size })}
        {...(props.partial === undefined ? {} : { partial: props.partial })}
      />
      {props.verdict !== undefined && <VerdictBadge verdict={props.verdict} />}
      <SourceChip id={source?.id ?? null} commit={source?.commit ?? null} />
    </span>
  );
}
