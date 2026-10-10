import { ScrollTable } from "../../design/components/ScrollTable";
import type { NodeRecord } from "../../api/graph";
import { DomainChip } from "../../design/components/GraphCanvas";
import { type Source, sourceAttribute } from "../../design/components/SourceChip";
import { edgesOf } from "./edges";

/** The graph's data as a table beside the drawing: every node, its edges both ways, in id order. */
export function NodesTable({
  nodes,
  source,
  hrefFor,
}: {
  nodes: readonly NodeRecord[];
  source: Source;
  hrefFor: (id: string) => string;
}) {
  const sorted = [...nodes].sort((a, b) => a.id.localeCompare(b.id));
  return (
    <section className="card" aria-label="Nodes" data-source={sourceAttribute(source)}>
      <h2 className="card-title">Nodes</h2>
      <ScrollTable label="Nodes">
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Node</th>
              <th scope="col">Domain</th>
              <th scope="col">Kind</th>
              <th scope="col">Owner</th>
              <th scope="col">Revision</th>
              <th scope="col">Constrains</th>
              <th scope="col">Constrained by</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((node) => {
              const edges = edgesOf(node.id, nodes);
              return (
                <tr key={node.id}>
                  <td>
                    <a className="mono" href={hrefFor(node.id)}>
                      {node.id}
                    </a>
                  </td>
                  <td>
                    <DomainChip domain={node.domain} />
                  </td>
                  <td>{node.kind}</td>
                  <td>{node.owner}</td>
                  <td className="mono">r{node.revision}</td>
                  <td className="mono">
                    {edges.constrains.length === 0
                      ? "—"
                      : edges.constrains
                          .map((e) => (e.node === null ? `${e.id} (not in the graph)` : e.id))
                          .join(", ")}
                  </td>
                  <td className="mono">
                    {edges.constrainedBy.length === 0
                      ? "—"
                      : edges.constrainedBy.map((e) => e.id).join(", ")}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </ScrollTable>
    </section>
  );
}
