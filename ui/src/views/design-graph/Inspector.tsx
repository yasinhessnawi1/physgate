import { ScrollTable } from "../../design/components/ScrollTable";
import { useState } from "react";

import type { Result } from "../../api/client";
import type { NodeHistory, NodeRecord, Writer } from "../../api/graph";
import { DomainChip } from "../../design/components/GraphCanvas";
import { Quantity } from "../../design/components/Quantity";
import { type Source, SourceChip, sourceAttribute } from "../../design/components/SourceChip";
import { ErrorState, LoadingState } from "../../design/components/States";
import { type EdgeEnd, edgesOf } from "./edges";

/** How many quantities show before the rest are asked for. */
export const FIRST_QUANTITIES = 6;

export function writerLabel(writer: Writer): string {
  if (writer === null) return "no write recorded in the run's log";
  if (writer === "decomposition") return "decomposition";
  return `${writer.subtask} · attempt ${String(writer.attempt)}`;
}

function Edge({ end, arrow }: { end: EdgeEnd; arrow: "→" | "←" }) {
  return (
    <li className="edge">
      <span className="mono">
        {arrow} {end.id}
      </span>
      {end.node === null ? (
        <span className="edge-missing">not in the graph at this revision</span>
      ) : (
        <span className="label">
          {end.node.domain} · {end.node.kind}
        </span>
      )}
    </li>
  );
}

/**
 * One node: its quantities with their units, its edges both ways, and its history from the
 * journal, each revision with the attempt that wrote it and a link to its diff.
 */
export function Inspector({
  node,
  nodes,
  history,
  source,
  diffHref,
}: {
  node: NodeRecord;
  nodes: readonly NodeRecord[];
  history: Result<NodeHistory> | null;
  source: Source;
  diffHref: (from: number, to: number) => string;
}) {
  const [all, setAll] = useState(false);
  const edges = edgesOf(node.id, nodes);
  const shown = all ? node.quantities : node.quantities.slice(0, FIRST_QUANTITIES);
  return (
    <aside
      className="card inspector"
      aria-label="Node inspector"
      data-source={sourceAttribute(source)}
    >
      <div className="inspector-head">
        <div className="inspector-name">
          <DomainChip domain={node.domain} />
          <h2 className="card-title mono">{node.id}</h2>
        </div>
        <span className="label">
          written by {node.owner} · <span className="mono">r{node.revision}</span>
        </span>
      </div>

      <section aria-label="Quantities">
        <h3 className="section-label">Quantities</h3>
        {node.quantities.length === 0 ? (
          <p className="view-note">This node records no quantities.</p>
        ) : (
          <ScrollTable label="Quantities">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col" className="numeric">
                    Value
                  </th>
                </tr>
              </thead>
              <tbody>
                {shown.map(([name, q]) => (
                  <tr key={name}>
                    <td>{name}</td>
                    <td className="numeric">
                      <Quantity q={q} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollTable>
        )}
        {node.quantities.length > FIRST_QUANTITIES && (
          <button
            type="button"
            className="button button-browse"
            onClick={() => {
              setAll((a) => !a);
            }}
          >
            {all ? "Show fewer" : `Show all ${String(node.quantities.length)} quantities`}
          </button>
        )}
      </section>

      <section aria-label="Constrains">
        <h3 className="section-label">Constrains</h3>
        {edges.constrains.length === 0 ? (
          <p className="view-note">No outgoing edges.</p>
        ) : (
          <ul className="edges">
            {edges.constrains.map((end) => (
              <Edge key={end.id} end={end} arrow="→" />
            ))}
          </ul>
        )}
      </section>

      <section aria-label="Constrained by">
        <h3 className="section-label">Constrained by</h3>
        {edges.constrainedBy.length === 0 ? (
          <p className="view-note">No node constrains this one.</p>
        ) : (
          <ul className="edges">
            {edges.constrainedBy.map((end) => (
              <Edge key={end.id} end={end} arrow="←" />
            ))}
          </ul>
        )}
      </section>

      <section aria-label="History">
        <h3 className="section-label">History</h3>
        {history === null ? (
          <LoadingState reading="the node's history" />
        ) : !history.ok ? (
          <ErrorState title="History: not shown" refusal={history.refusal} />
        ) : (
          <ol className="history">
            {[...history.value.history].reverse().map((entry, index, newestFirst) => {
              const earlier = newestFirst[index + 1];
              return (
                <li key={entry.revision} className="history-entry">
                  <span>
                    <span className="mono">r{entry.revision}</span> · {writerLabel(entry.writtenBy)}
                    {entry.op !== "create" && <span className="label"> · {entry.op}</span>}
                  </span>
                  {earlier === undefined ? (
                    <span className="label">created</span>
                  ) : (
                    <a href={diffHref(earlier.revision, entry.revision)}>
                      Diff r{earlier.revision} → r{entry.revision}
                    </a>
                  )}
                </li>
              );
            })}
          </ol>
        )}
      </section>
      <SourceChip source={{ ...source, id: `${source.id} · journal r${String(node.revision)}` }} />
    </aside>
  );
}
