import type { CostRecord } from "../../api/records";

/**
 * Whether a cost is a lower bound, said beside it: how many calls it is short by, and, when
 * reviews are among them, that the server cannot price them at their rate. Nothing otherwise.
 */
export function CostCaveat({ cost }: { cost: CostRecord }) {
  if (!cost.lowerBound) return null;
  const n = cost.unpriced.length;
  const reviews = cost.unpriced.some((call) => call.startsWith("reviewer:"));
  return (
    <strong className="cost-caveat">
      {" "}
      Lower bound: {n}{" "}
      {n === 1 ? "call not priced at the rate it paid" : "calls not priced at the rate they paid"}
      {reviews ? "; reviews unpriced at their rate, since the server reads no review root" : ""}.
    </strong>
  );
}
