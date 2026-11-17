import type { CostRecord } from "../../api/records";

/**
 * Whether a cost is a lower bound, said beside it in plain words: the cost may be higher, how
 * many calls are counted at the lowest rate because what they paid could not be read, and, when
 * reviews are among them, that their records are kept where this app does not read. Each call's
 * tokens are counted; only the rate some of them paid is unknown. Nothing otherwise.
 */
export function CostCaveat({ cost }: { cost: CostRecord }) {
  if (!cost.lowerBound) return null;
  const n = cost.unpriced.length;
  const reviews = cost.unpriced.some((call) => call.startsWith("reviewer:"));
  return (
    <strong className="cost-caveat">
      {" "}
      Lower bound: the cost may be higher. {n} {n === 1 ? "call" : "calls"} counted at the lowest
      rate, since what {n === 1 ? "it" : "they"} paid could not be read
      {reviews ? ": the records of the reviews are kept where this app does not read" : ""}.
    </strong>
  );
}
