import { ScrollTable } from "../../design/components/ScrollTable";
import type { GraphDiff } from "../../api/graph";
import { Quantity } from "../../design/components/Quantity";
import { type Source, SourceChip, sourceAttribute } from "../../design/components/SourceChip";
import { EmptyState } from "../../design/components/States";
import { quantityRows } from "./compare";

/**
 * The store's change list between two revisions, and each changed node at both, side by side.
 * The change list is the store's own; the marks on differing rows are a view, and say so.
 */
export function DiffCard({ diff, source }: { diff: GraphDiff; source: Source }) {
  const range = `r${String(diff.from)} → r${String(diff.to)}`;
  return (
    <section className="card" aria-label="Diff" data-source={sourceAttribute(source)}>
      <h2 className="card-title">Changes {range}</h2>
      {diff.changes.length === 0 ? (
        <EmptyState title="Nothing changed between these revisions" />
      ) : (
        <>
          <p className="view-note">
            The store&apos;s change list between the two revisions, read from the run&apos;s
            journal.
          </p>
          <ScrollTable label="Change list">
            <table className="table" aria-label="Change list">
              <thead>
                <tr>
                  <th scope="col">Revision</th>
                  <th scope="col">Node</th>
                  <th scope="col">Op</th>
                  <th scope="col">Version</th>
                </tr>
              </thead>
              <tbody>
                {diff.changes.map((change) => (
                  <tr key={change.revision}>
                    <td className="mono">r{change.revision}</td>
                    <td className="mono">{change.nodeId}</td>
                    <td>{change.op}</td>
                    <td className="mono">{change.version}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollTable>
          <p className="view-note">
            View: rows are marked where the recorded value and unit differ between the two sides.
          </p>
          {diff.nodes.map(({ id, before, after }) => (
            <section key={id} className="diff-node" aria-label={`Changes to ${id}`}>
              <h3 className="section-label mono">{id}</h3>
              <ScrollTable label={`Quantities of ${id} at both revisions`}>
                <table className="table">
                  <thead>
                    <tr>
                      <th scope="col">Quantity</th>
                      <th scope="col">
                        At r{diff.from}
                        {before === null ? "" : ` (r${String(before.revision)})`}
                      </th>
                      <th scope="col">
                        At r{diff.to}
                        {after === null ? "" : ` (r${String(after.revision)})`}
                      </th>
                      <th scope="col">View</th>
                    </tr>
                  </thead>
                  <tbody>
                    {quantityRows(before, after).map((row) => (
                      <tr key={row.name} className={row.differs ? "diff-row-differs" : undefined}>
                        <td>{row.name}</td>
                        <td>
                          {row.before === undefined ? (
                            <span className="muted">absent</span>
                          ) : (
                            <Quantity q={row.before} />
                          )}
                        </td>
                        <td>
                          {row.after === undefined ? (
                            <span className="muted">absent</span>
                          ) : (
                            <Quantity q={row.after} />
                          )}
                        </td>
                        <td>{row.differs ? <span className="diff-mark">differs</span> : ""}</td>
                      </tr>
                    ))}
                    {(before?.constrains.join(",") ?? "") !==
                      (after?.constrains.join(",") ?? "") && (
                      <tr className="diff-row-differs">
                        <td>constrains</td>
                        <td className="mono">{before?.constrains.join(", ") || "—"}</td>
                        <td className="mono">{after?.constrains.join(", ") || "—"}</td>
                        <td>
                          <span className="diff-mark">differs</span>
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </ScrollTable>
            </section>
          ))}
        </>
      )}
      <SourceChip source={{ ...source, id: `${source.id} · journal ${range}` }} />
    </section>
  );
}
