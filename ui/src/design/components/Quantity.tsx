import { type Quantity as Q, requireQuantity, unitLabel, valueLabel } from "../quantity";

/** One unbreakable figure: the value in mono, a thin gap, the unit in the third text colour. */
export function Quantity({ q }: { q: Q }) {
  const checked = requireQuantity(q);
  return (
    <span className="quantity">
      <span className="quantity-value">{valueLabel(checked.value)}</span>
      <span className="quantity-unit">{unitLabel(checked.unit)}</span>
    </span>
  );
}
