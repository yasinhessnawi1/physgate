import type { CostRecord } from "../../api/records";

/** Said wherever tokens or a cost are shown for a run that holds a response cut off. */
export const CUT_OFF =
  "A response was cut off by a connection error; its tokens are listed separately and the cost shown is a lower bound.";

/**
 * Whether a cost is a lower bound, said beside it in plain words: the cost may be higher, how
 * many calls are counted at the lowest rate because what they paid could not be read, and, when
 * reviews are among them, that their records are kept where this app does not read. Each call's
 * tokens are counted; only the rate some of them paid is unknown. Where a response was cut off,
 * that, in a line of its own: its tokens are in no figure, and whether it was billed is unknown.
 * Nothing otherwise.
 */
export function CostCaveat({ cost }: { cost: CostRecord }) {
  const cut = cost.cutShort.length > 0;
  if (!cost.lowerBound && !cut) return null;
  const n = cost.unpriced.length;
  const reviews = cost.unpriced.some((call) => call.startsWith("reviewer:"));
  return (
    <strong className="cost-caveat">
      {(n > 0 || !cut) && (
        <>
          {" "}
          Lower bound: the cost may be higher. {n} {n === 1 ? "call" : "calls"} counted at the
          lowest rate, since what {n === 1 ? "it" : "they"} paid could not be read
          {reviews ? ": the records of the reviews are kept where this app does not read" : ""}.
        </>
      )}
      {cut && ` ${CUT_OFF}`}
    </strong>
  );
}
