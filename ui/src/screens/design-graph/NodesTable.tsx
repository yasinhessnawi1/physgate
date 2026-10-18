/**
 * The graph as a table: every node led by its label, its key under it, its domain, its latest
 * verdict, and its edges both ways. Under a domain filter the rows narrow, but every edge is
 * still resolved over the whole graph, so a node of another domain is never called missing.
 */
import type { NodeRecord } from "../../api/graph";
import { DomainChip } from "../../design/components/data/DomainChip";
import { Id } from "../../design/components/data/Id";
import { SourceChip } from "../../design/components/data/SourceChip";
import { type Source, sourceAttribute } from "../../design/components/data/source";
import { type GateMode, GateOutcome } from "../../design/components/verdict/GateMode";
import type { Verdict } from "../../design/components/verdict/verdict";
import { nodeLabel } from "../../words/humanise";
import { edgesOf } from "./edges";

export function NodesTable({
  nodes,
  all,
  verdicts,
  gateMode,
  source,
  hrefFor,
}: {
  /** The rows shown: the graph, or the part of it a filter keeps. */
  readonly nodes: readonly NodeRecord[];
  /** The whole graph at this revision, which every edge is resolved against, filtered or not. */
  readonly all: readonly NodeRecord[];
  readonly verdicts: ReadonlyMap<string, Verdict>;
  readonly gateMode: GateMode;
  readonly source: Source;
  readonly hrefFor: (id: string) => string;
}) {
  const sorted = [...nodes].sort((a, b) => a.id.localeCompare(b.id));
  return (
    <section className="pg-card pg-panel" aria-label="Nodes" data-source={sourceAttribute(source)}>
      <div className="pg-table-wrap" role="region" aria-label="Nodes, as a table" tabIndex={0}>
        <table className="pg-table" aria-label="Nodes">
          <thead>
            <tr>
              <th scope="col">Node</th>
              <th scope="col">Domain</th>
              <th scope="col">Latest gate verdict</th>
              <th scope="col">Kind</th>
              <th scope="col">Revision</th>
              <th scope="col">Constrains</th>
              <th scope="col">Constrained by</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((node) => {
              const edges = edgesOf(node.id, all);
              const verdict = gateMode === "off" ? undefined : verdicts.get(node.id);
              return (
                <tr key={node.id}>
                  <td>
                    <a className="pg-node-link pg-hit" href={hrefFor(node.id)}>
                      {nodeLabel(node.id, node.domain)}
                    </a>
                    <Id value={node.id} copy={false} />
                  </td>
                  <td>
                    <DomainChip domain={node.domain} />
                  </td>
                  <td>
                    {verdict === undefined ? (
                      <span className="pg-muted">none recorded</span>
                    ) : (
                      <GateOutcome mode={gateMode} outcome={verdict} />
                    )}
                  </td>
                  <td>{node.kind}</td>
                  <td className="mono">r{node.revision}</td>
                  <td className="pg-wrap">
                    {edges.constrains.length === 0 ? (
                      <span className="pg-muted">none</span>
                    ) : (
                      edges.constrains.map((e) => (
                        <span key={e.id} className="pg-edge-ref">
                          {e.node === null ? `${e.id} (not in the graph)` : e.id}
                        </span>
                      ))
                    )}
                  </td>
                  <td className="pg-wrap">
                    {edges.constrainedBy.length === 0 ? (
                      <span className="pg-muted">none</span>
                    ) : (
                      edges.constrainedBy.map((e) => (
                        <span key={e.id} className="pg-edge-ref">
                          {e.id}
                        </span>
                      ))
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <SourceChip {...source} />
    </section>
  );
}
