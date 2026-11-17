/**
 * The gate's per-check records in five columns: the check (its name in words, what it looked at,
 * its id), its outcome in the mode it ran in, what it measured against its bound, whether a
 * reviewer had approved the work before the gate, and the source. Grouped by the gate call they
 * came from; where a check did not pass, the gate's own message is under its name. Records of one
 * check over one subject in one call, with one outcome, read as one row with their count, each
 * record's own message and measure kept on its line.
 */
import type { GateCheck } from "../../api/run";
import { Id } from "../../design/components/data/Id";
import { SourceChip } from "../../design/components/data/SourceChip";
import type { Source } from "../../design/components/data/source";
import { GateOutcome } from "../../design/components/verdict/GateMode";
import { Bound, CheckName, checkId, Measured, sentenceOf, subjectOf } from "../common/checks";

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

/** What makes two records of one gate call alike enough to share a row. */
function alike(check: GateCheck): string {
  return [
    check.name,
    String(check.check),
    subjectOf(check),
    check.mode,
    check.outcome,
    String(check.reviewerHadPassed),
  ].join("|");
}

/** Consecutive records alike, each run of them one row. */
export function rowsOf(checks: readonly GateCheck[]): readonly (readonly GateCheck[])[] {
  const rows: GateCheck[][] = [];
  for (const check of checks) {
    const last = rows.at(-1);
    const first = last?.[0];
    if (last !== undefined && first !== undefined && alike(first) === alike(check))
      last.push(check);
    else rows.push([check]);
  }
  return rows;
}

/**
 * The counts a person cannot read alone, in a sentence each: what unchecked means, and what a
 * pass over nothing is. Nothing is said of a count that is zero.
 */
export function CountsExplained({
  unchecked,
  overNothing,
}: {
  readonly unchecked: number;
  readonly overNothing: number;
}) {
  if (unchecked === 0 && overNothing === 0) return null;
  return (
    <ul className="pg-panel-note pg-counts-explained">
      {unchecked > 0 && (
        <li>
          Unchecked ({unchecked}): the gate could not judge these values, for example a quantity its
          catalogue does not know, so they are neither passed nor failed.
        </li>
      )}
      {overNothing > 0 && (
        <li>
          A pass over nothing ({overNothing}): the check ran but found no value to look at; it is a
          pass as the gate wrote it, not a value shown to be right.
        </li>
      )}
    </ul>
  );
}

function CheckRow({
  row,
  source,
}: {
  readonly row: readonly GateCheck[];
  readonly source: Source;
}) {
  const [check] = row;
  if (check === undefined) return null;
  const many = row.length > 1;
  return (
    <tr>
      <td className="pg-wrap">
        <CheckName check={check} />
        <Id value={checkId(check)} copy={false} />
        {many && <span className="pg-check-count">{row.length} records</span>}
        {check.outcome !== "pass" &&
          (many ? (
            <ul className="pg-why-list">
              {row.map((c, i) => (
                <li key={i} className="pg-why-line">
                  {sentenceOf(c.message)}
                </li>
              ))}
            </ul>
          ) : (
            <span className="pg-why-line">{sentenceOf(check.message)}</span>
          ))}
      </td>
      <td>
        <GateOutcome mode={check.mode} outcome={check.outcome} />
      </td>
      <td className="pg-wrap">
        {many ? (
          <ul className="pg-measured-list">
            {row.map((c, i) => (
              <li key={i}>
                <span className="pg-measured">
                  <Measured check={c} />
                </span>
                <span className="pg-bound-line">
                  <Bound check={c} />
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <>
            <span className="pg-measured">
              <Measured check={check} />
            </span>
            <span className="pg-bound-line">
              <Bound check={check} />
            </span>
          </>
        )}
      </td>
      <td className="pg-wrap">{reviewer(check.reviewerHadPassed)}</td>
      <td>
        <SourceChip {...source} compact />
      </td>
    </tr>
  );
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
            {rowsOf(group.rows).map((row, index) => (
              <CheckRow key={`${group.key}-${String(index)}`} row={row} source={source} />
            ))}
          </tbody>
        ))}
      </table>
    </div>
  );
}
