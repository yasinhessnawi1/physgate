/**
 * The store's change list between two revisions, and each changed node at both, side by side.
 * The change list is the store's own; the marks on differing rows are a view, and say so: a pair
 * differs when its value or its unit differs as recorded, and no unit is converted.
 */
import type { GraphDiff } from "../../api/graph";
import { Id } from "../../design/components/data/Id";
import { Quantity } from "../../design/components/data/Quantity";
import { SourceChip } from "../../design/components/data/SourceChip";
import { type Source, sourceAttribute } from "../../design/components/data/source";
import { EmptyState } from "../../design/components/status/States";
import { nodeLabel, quantityLabel } from "../../words/humanise";
import { quantityRows } from "./compare";

const OPS: Readonly<Record<string, string>> = {
  create: "Created",
  write: "Written",
  rollback: "Rolled back",
};

export function DiffView({ diff, source }: { readonly diff: GraphDiff; readonly source: Source }) {
  const range = `r${String(diff.from)} → r${String(diff.to)}`;
  const domainOf = new Map(
    diff.nodes.flatMap(({ id, before, after }) => {
      const domain = (after ?? before)?.domain;
      return domain === undefined ? [] : [[id, domain] as const];
    }),
  );
  return (
    <section className="pg-card pg-panel" aria-label="Diff" data-source={sourceAttribute(source)}>
      <header className="pg-panel-head">
        <h2 className="pg-panel-title">What changed from {range}</h2>
      </header>
      {diff.changes.length === 0 ? (
        <EmptyState title="Nothing changed between these revisions" />
      ) : (
        <>
          <p className="pg-panel-note">
            The store's own change list between the two revisions, read from the run's journal.
          </p>
          <div className="pg-table-wrap" role="region" aria-label="Change list" tabIndex={0}>
            <table className="pg-table" aria-label="Change list">
              <thead>
                <tr>
                  <th scope="col">Node</th>
                  <th scope="col">What happened</th>
                  <th scope="col">Revision</th>
                  <th scope="col">Version</th>
                </tr>
              </thead>
              <tbody>
                {diff.changes.map((change) => (
                  <tr key={change.revision}>
                    <td>
                      {nodeLabel(change.nodeId, domainOf.get(change.nodeId))}{" "}
                      <Id value={change.nodeId} copy={false} />
                    </td>
                    <td>{OPS[change.op] ?? change.op}</td>
                    <td className="mono">r{change.revision}</td>
                    <td className="mono">{change.version}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="pg-panel-note">
            View: rows are marked "differs" where the recorded value or unit differs between the two
            sides. No unit is converted.
          </p>
          {diff.nodes.map(({ id, before, after }) => (
            <section key={id} className="pg-diff-node" aria-label={`Changes to ${id}`}>
              <h3 className="pg-section-label">
                <span>{nodeLabel(id, domainOf.get(id))}</span> <Id value={id} copy={false} />
              </h3>
              <div
                className="pg-table-wrap"
                role="region"
                aria-label={`Quantities of ${id} at both revisions`}
                tabIndex={0}
              >
                <table className="pg-table">
                  <thead>
                    <tr>
                      <th scope="col">Quantity</th>
                      <th scope="col">
                        At r{diff.from}
                        {before === null ? "" : ` (written r${String(before.revision)})`}
                      </th>
                      <th scope="col">
                        At r{diff.to}
                        {after === null ? "" : ` (written r${String(after.revision)})`}
                      </th>
                      <th scope="col">View</th>
                    </tr>
                  </thead>
                  <tbody>
                    {quantityRows(before, after).map((row) => (
                      <tr key={row.name} className={row.differs ? "pg-differs" : undefined}>
                        <td>{quantityLabel(row.name)}</td>
                        <td>
                          {row.before === undefined ? (
                            <span className="pg-muted">absent</span>
                          ) : (
                            <Quantity {...row.before} />
                          )}
                        </td>
                        <td>
                          {row.after === undefined ? (
                            <span className="pg-muted">absent</span>
                          ) : (
                            <Quantity {...row.after} />
                          )}
                        </td>
                        <td>
                          {row.differs ? <span className="pg-differs-mark">differs</span> : ""}
                        </td>
                      </tr>
                    ))}
                    {(before?.constrains.join(",") ?? "") !==
                      (after?.constrains.join(",") ?? "") && (
                      <tr className="pg-differs">
                        <td>Constrains</td>
                        <td className="mono">{before?.constrains.join(", ") || "none"}</td>
                        <td className="mono">{after?.constrains.join(", ") || "none"}</td>
                        <td>
                          <span className="pg-differs-mark">differs</span>
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </section>
          ))}
        </>
      )}
      <SourceChip {...{ ...source, id: `${source.id} · journal ${range}` }} />
    </section>
  );
}
