import { requireQuantity, unitLabel, valueLabel } from "../../quantity";

export interface QuantityProps {
  /** As recorded; never rounded by the view. */
  readonly value: number | string;
  /** Required. "1" reads "dimensionless". */
  readonly unit: string;
  readonly size?: "md" | "lg";
  /** Drawn in the what-if hue. Pair it with a what-if marker. */
  readonly whatIf?: boolean;
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
}: QuantityProps) {
  const checked = requireQuantity({ value, unit });
  const className = [
    "pg-quantity",
    size === "lg" ? "pg-quantity-lg" : null,
    whatIf ? "pg-quantity-whatif" : null,
  ]
    .filter((c) => c !== null)
    .join(" ");
  return (
    <span className={className}>
      <span className="pg-quantity-value">{valueLabel(checked.value)}</span>
      <span className="pg-quantity-unit">{unitLabel(checked.unit)}</span>
      {partial && <span className="pg-so-far">so far</span>}
    </span>
  );
}
