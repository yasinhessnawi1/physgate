import { ScrollTable } from "../../design/components/ScrollTable";
/**
 * The gate's per-check records, grouped by the gate call they came from. Every outcome is drawn
 * through the mode it ran in, so an observe record reads "would … · not enforced" and is never a
 * filled verdict; an unchecked record is its own category and says why; a pass says how much it
 * looked at, a pass over nothing included.
 */
import type { GateCheck } from "../../api/run";
import { GateOutcome } from "../../design/components/GateMode";
import { Quantity } from "../../design/components/Quantity";

function call(check: GateCheck): string {
  return check.subtask === "integration"
    ? "integration · the whole design"
    : `${check.subtask} · attempt ${String(check.attempt ?? "")}`;
}

export function Measured({ check }: { check: GateCheck }) {
  if (check.outcome === "pass") {
    // A pass record always carries its count; one that did not would say so, never a made-up 0.
    const n = check.evaluated ?? check.details.evaluated;
    if (n === null) return <span className="muted">count not recorded</span>;
    return n === 0 ? (
      <span className="evaluated evaluated-none">0 evaluated · a pass over nothing</span>
    ) : (
      <span className="evaluated">
        <span className="mono">{n}</span> evaluated
      </span>
    );
  }
  if (check.value !== null) return <Quantity q={check.value} />;
  if (check.outcome === "unchecked" && check.details.quantities.length > 0)
    return <span className="mono measured-names">{check.details.quantities.join(", ")}</span>;
  return <span className="muted">—</span>;
}

export function Bound({ check }: { check: GateCheck }) {
  const { low, high } = check.details;
  if (low !== null && high !== null)
    return (
      <span className="bound">
        <Quantity q={low} /> to <Quantity q={high} />
      </span>
    );
  return check.expected === null ? (
    <span className="muted">—</span>
  ) : (
    <span className="bound-text">{check.expected}</span>
  );
}

function reviewer(passed: boolean | null): string {
  return passed === null ? "no review" : passed ? "yes" : "no";
}

export function GateChecksTable({ checks }: { checks: readonly GateCheck[] }) {
  const calls: { key: string; label: string; rows: GateCheck[] }[] = [];
  for (const check of checks) {
    const key = String(check.seq);
    const last = calls.at(-1);
    if (last?.key === key) last.rows.push(check);
    else calls.push({ key, label: call(check), rows: [check] });
  }
  return (
    <ScrollTable label="Gate checks, by gate call">
      <table className="table checks-table">
        <thead>
          <tr>
            <th scope="col">Check</th>
            <th scope="col">Scope</th>
            <th scope="col">Node</th>
            <th scope="col">Result</th>
            <th scope="col">Measured</th>
            <th scope="col">Bound</th>
            <th scope="col">Reviewer had passed</th>
          </tr>
        </thead>
        {calls.map((group) => (
          <tbody key={group.key}>
            <tr className="checks-call">
              <th scope="rowgroup" colSpan={7}>
                <span className="mono">{group.label}</span>{" "}
                <span className="label">· gate line {group.key}</span>
              </th>
            </tr>
            {group.rows.flatMap((check, index) => {
              const row = (
                <tr
                  key={`${group.key}-${String(index)}`}
                  className={check.outcome === "pass" ? undefined : "has-why"}
                >
                  <td>{check.name}</td>
                  <td>{check.scope}</td>
                  <td className="mono">{check.node ?? "—"}</td>
                  <td>
                    <GateOutcome mode={check.mode} outcome={check.outcome} />
                  </td>
                  <td>
                    <Measured check={check} />
                  </td>
                  <td className="bound-cell">
                    <Bound check={check} />
                  </td>
                  <td>{reviewer(check.reviewerHadPassed)}</td>
                </tr>
              );
              return check.outcome === "pass"
                ? [row]
                : [
                    row,
                    <tr key={`${group.key}-${String(index)}-why`} className="why-row">
                      <td colSpan={7}>
                        <span className="label">Why: </span>
                        {check.message}
                      </td>
                    </tr>,
                  ];
            })}
          </tbody>
        ))}
      </table>
    </ScrollTable>
  );
}
