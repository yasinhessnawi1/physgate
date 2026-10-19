/**
 * The gate's per-check records in five columns: the check (its name in words, what it looked at,
 * its id), its outcome in the mode it ran in, what it measured against its bound, whether a
 * reviewer had approved the work before the gate, and the source. Grouped by the gate call they
 * came from; where a check did not pass, the gate's own message is under its name.
 */
import type { GateCheck } from "../../api/run";
import { Id } from "../../design/components/data/Id";
import { SourceChip } from "../../design/components/data/SourceChip";
import type { Source } from "../../design/components/data/source";
import { GateOutcome } from "../../design/components/verdict/GateMode";
import { Bound, CheckName, checkId, Measured, sentenceOf } from "../common/checks";

/** Which records a filter keeps. */
export type Filter = "all" | "not-passed" | "unchecked";

export function kept(checks: readonly GateCheck[], filter: Filter): readonly GateCheck[] {
  if (filter === "not-passed") return checks.filter((c) => c.outcome !== "pass");
  if (filter === "unchecked") return checks.filter((c) => c.outcome === "unchecked");
  return checks;
}

function reviewer(passed: boolean | null): string {
  return passed === null ? "not reviewed" : passed ? "yes" : "no";
}

/** The gate call a record came from, in words. */
export function callOf(check: GateCheck, names: ReadonlyMap<string, string>): string {
  return check.subtask === "integration"
    ? "The whole design, after every subtask merged"
    : `${names.get(check.subtask) ?? check.subtask} · attempt ${String(check.attempt ?? "")}`;
}

export function ChecksTable({
  checks,
  names,
  source,
}: {
  readonly checks: readonly GateCheck[];
  /** Each subtask's name as a person reads it. */
  readonly names: ReadonlyMap<string, string>;
  readonly source: Source;
}) {
  const calls: { key: string; label: string; rows: GateCheck[] }[] = [];
  for (const check of checks) {
    const key = String(check.seq);
    const last = calls.at(-1);
    if (last?.key === key) last.rows.push(check);
    else calls.push({ key, label: callOf(check, names), rows: [check] });
  }
  return (
    <div
      className="pg-table-wrap"
      role="region"
      aria-label="Gate checks, by gate call"
      tabIndex={0}
    >
      <table className="pg-table pg-checks-table" aria-label="Gate checks">
        <thead>
          <tr>
            <th scope="col">Check</th>
            <th scope="col">Outcome</th>
            <th scope="col">Value · bound</th>
            <th scope="col">Reviewer approved before the gate?</th>
            <th scope="col">Source</th>
          </tr>
        </thead>
        {calls.map((group) => (
          <tbody key={group.key}>
            <tr className="pg-group-row">
              <th scope="rowgroup" colSpan={5}>
                {group.label} <Id value={`seq ${group.key}`} copy={false} />
              </th>
            </tr>
            {group.rows.map((check, index) => (
              <tr key={`${group.key}-${String(index)}`}>
                <td className="pg-wrap">
                  <CheckName check={check} />
                  <Id value={checkId(check)} copy={false} />
                  {check.outcome !== "pass" && (
                    <span className="pg-why-line">{sentenceOf(check.message)}</span>
                  )}
                </td>
                <td>
                  <GateOutcome mode={check.mode} outcome={check.outcome} />
                </td>
                <td className="pg-wrap">
                  <span className="pg-measured">
                    <Measured check={check} />
                  </span>
                  <span className="pg-bound-line">
                    <Bound check={check} />
                  </span>
                </td>
                <td className="pg-wrap">{reviewer(check.reviewerHadPassed)}</td>
                <td>
                  <SourceChip {...source} compact />
                </td>
              </tr>
            ))}
          </tbody>
        ))}
      </table>
    </div>
  );
}
