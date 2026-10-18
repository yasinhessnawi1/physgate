/**
 * Each node's latest verdict from the gate's per-check records: the records that name the node in
 * the latest gate line that names it. Fail if any record there failed, else warn, else pass;
 * unchecked when every record there is unchecked. A node no record names has no verdict, which is
 * never a pass.
 */
import type { GateCheck } from "../../api/run";
import type { Verdict } from "../../design/components/verdict/verdict";

export function nodeVerdicts(checks: readonly GateCheck[]): ReadonlyMap<string, Verdict> {
  const latest = new Map<string, number>();
  for (const c of checks)
    if (c.node !== null && c.seq >= (latest.get(c.node) ?? -1)) latest.set(c.node, c.seq);
  const found = new Map<string, Verdict>();
  for (const [node, seq] of latest) {
    const outcomes = checks.filter((c) => c.node === node && c.seq === seq).map((c) => c.outcome);
    found.set(
      node,
      outcomes.includes("fail")
        ? "fail"
        : outcomes.includes("warn")
          ? "warn"
          : outcomes.includes("pass")
            ? "pass"
            : "unchecked",
    );
  }
  return found;
}

/** The gate's records that name ``node``, from its latest gate line. */
export function latestChecksOf(node: string, checks: readonly GateCheck[]): readonly GateCheck[] {
  const mine = checks.filter((c) => c.node === node);
  const seq = Math.max(-1, ...mine.map((c) => c.seq));
  return mine.filter((c) => c.seq === seq);
}
