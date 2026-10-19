/**
 * Each node's latest verdict from the gate's per-check records: the records that name the node in
 * the latest gate line that names it. Fail if any record there failed, else warn, else pass;
 * unchecked when every record there is unchecked. A verdict over records of which some were left
 * unchecked says so beside it ("pass · part unchecked"), since a pass over part of a node is not
 * a pass over the node. A node no record names has no verdict, which is never a pass.
 */
import type { GateCheck } from "../../api/run";
import type { GateMode } from "../../design/components/verdict/GateMode";
import type { Verdict } from "../../design/components/verdict/verdict";

export interface NodeVerdict {
  readonly verdict: Verdict;
  /** Some, not all, of the node's records in that gate line were left unchecked. */
  readonly partUnchecked: boolean;
}

export function nodeVerdicts(checks: readonly GateCheck[]): ReadonlyMap<string, NodeVerdict> {
  const latest = new Map<string, number>();
  for (const c of checks)
    if (c.node !== null && c.seq >= (latest.get(c.node) ?? -1)) latest.set(c.node, c.seq);
  const found = new Map<string, NodeVerdict>();
  for (const [node, seq] of latest) {
    const outcomes = checks.filter((c) => c.node === node && c.seq === seq).map((c) => c.outcome);
    const verdict: Verdict = outcomes.includes("fail")
      ? "fail"
      : outcomes.includes("warn")
        ? "warn"
        : outcomes.includes("pass")
          ? "pass"
          : "unchecked";
    found.set(node, {
      verdict,
      partUnchecked: verdict !== "unchecked" && outcomes.includes("unchecked"),
    });
  }
  return found;
}

/**
 * A node's verdict in words, for the command palette: under observe the gate enforced nothing,
 * so it reads "would pass", never "pass"; a part-unchecked verdict says so.
 */
export function verdictWords(found: NodeVerdict, mode: GateMode): string {
  const word =
    mode === "observe" && found.verdict !== "unchecked" ? `would ${found.verdict}` : found.verdict;
  return found.partUnchecked ? `${word} · part unchecked` : word;
}

/** The gate's records that name ``node``, from its latest gate line. */
export function latestChecksOf(node: string, checks: readonly GateCheck[]): readonly GateCheck[] {
  const mine = checks.filter((c) => c.node === node);
  const seq = Math.max(-1, ...mine.map((c) => c.seq));
  return mine.filter((c) => c.seq === seq);
}
