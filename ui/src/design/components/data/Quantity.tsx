import { requireQuantity, roundedLabel, unitLabel, valueLabel } from "../../quantity";

export interface QuantityProps {
  /** As recorded; never rounded by the view. */
  readonly value: number | string;
  /** Required. "1" reads "dimensionless". */
  readonly unit: string;
  readonly size?: "md" | "lg";
  /** Drawn in the what-if hue. Pair it with a what-if marker. */
  readonly whatIf?: boolean;
  /**
   * Show a recorded decimal to this many places, for a cost a person reads to the sen. The exact
   * figure stays one hover away. Without it, a quantity is never rounded.
   */
  readonly decimals?: number;
  /** A running total of a run still in progress: "so far" follows as text. */
  readonly partial?: boolean;
}

/**
 * One unbreakable figure: the value in tabular mono, the unit beside it. There is no way to show
 * a bare number: the type needs the unit, and a value that arrives without one is refused.
 */
export function Quantity({
  value,
  unit,
  size = "md",
  whatIf = false,
  partial = false,
  decimals,
}: QuantityProps) {
  const checked = requireQuantity({ value, unit });
  const className = [
    "pg-quantity",
    size === "lg" ? "pg-quantity-lg" : null,
    whatIf ? "pg-quantity-whatif" : null,
  ]
    .filter((c) => c !== null)
    .join(" ");
  const rounded = decimals === undefined ? null : roundedLabel(checked.value, decimals);
  return (
    <span
      className={className}
      {...(rounded === null
        ? {}
        : { title: `${valueLabel(checked.value)} ${unitLabel(checked.unit)} as recorded` })}
    >
      <span className="pg-quantity-value">{rounded ?? valueLabel(checked.value)}</span>
      <span className="pg-quantity-unit">{unitLabel(checked.unit)}</span>
      {partial && <span className="pg-so-far">so far</span>}
    </span>
  );
}
