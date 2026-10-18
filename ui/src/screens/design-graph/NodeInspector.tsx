/**
 * One node: its label, its key to copy, its domain and latest verdict; every quantity named in
 * words with its source and who set it; the gate's latest checks of it, unchecked after the
 * separator; its edges both ways; and its history from the journal, each revision with who
 * wrote it and a link to what changed.
 */
import type { Result } from "../../api/client";
import type { NodeHistory, NodeRecord, Writer } from "../../api/graph";
import type { RunConfig } from "../../api/records";
import type { GateCheck } from "../../api/run";
import { DomainChip } from "../../design/components/data/DomainChip";
import { Id } from "../../design/components/data/Id";
import { Quantity } from "../../design/components/data/Quantity";
import { SourceChip } from "../../design/components/data/SourceChip";
import { type Source, sourceAttribute } from "../../design/components/data/source";
import { Inspector, InspectorSection } from "../../design/components/layout/Inspector";
import { ErrorState, LoadingState } from "../../design/components/status/States";
import { GateOutcome } from "../../design/components/verdict/GateMode";
import { VerdictBadge } from "../../design/components/verdict/VerdictBadge";
import { type Actor, agentOf, writerActor } from "../../words/actors";
import { nodeLabel, quantityLabel } from "../../words/humanise";
import { ActorTag } from "../common/ActorTag";
import { CheckName, checkId } from "../common/checks";
import { type EdgeEnd, edgesOf } from "./edges";
import { latestChecksOf, nodeVerdicts } from "./verdicts";

/** Who wrote a revision of a node, from the journal's writer and the run's roles. */
function historyActor(writer: Writer, node: NodeRecord, config: RunConfig): Actor | null {
  if (writer === null) return null;
  if (writer === "decomposition") return writerActor("decomposition", config);
  return agentOf(node.owner, config.roleModels[node.owner]);
}

function Edge({
  end,
  arrow,
  href,
}: {
  readonly end: EdgeEnd;
  readonly arrow: "→" | "←";
  readonly href: (id: string) => string;
}) {
  return (
    <li className="pg-list-row">
      {end.node === null ? (
        <span className="pg-list-row-main">
          <span>
            {arrow} {nodeLabel(end.id)}: not in the graph at this revision
          </span>
          <Id value={end.id} copy={false} />
        </span>
      ) : (
        <a className="pg-list-row-main pg-hit" href={href(end.id)}>
          <span>
            {arrow} {nodeLabel(end.id, end.node.domain)}
          </span>
          <Id value={end.id} copy={false} />
        </a>
      )}
      {end.node !== null && <DomainChip domain={end.node.domain} />}
    </li>
  );
}

export function NodeInspector({
  node,
  nodes,
  checks,
  config,
  history,
  historyRoute,
  onHistoryAgain,
  source,
  runLabel,
  diffHref,
  nodeHref,
}: {
  readonly node: NodeRecord;
  readonly nodes: readonly NodeRecord[];
  readonly checks: readonly GateCheck[];
  readonly config: RunConfig;
  readonly history: Result<NodeHistory> | null;
  readonly historyRoute: string | null;
  readonly onHistoryAgain: () => void;
  readonly source: Source;
  readonly runLabel: string;
  readonly diffHref: (from: number, to: number) => string;
  readonly nodeHref: (id: string) => string;
}) {
  const edges = edgesOf(node.id, nodes);
  const verdict = config.gateMode === "off" ? undefined : nodeVerdicts(checks).get(node.id);
  const latest = latestChecksOf(node.id, checks);
  const judged = latest.filter((c) => c.outcome !== "unchecked");
  const unchecked = latest.filter((c) => c.outcome === "unchecked");
  return (
    <Inspector
      label="Node inspector"
      crumbs={[runLabel, "Design graph"]}
      title={nodeLabel(node.id, node.domain)}
      badges={
        <>
          <DomainChip domain={node.domain} />
          {verdict !== undefined && <GateOutcome mode={config.gateMode} outcome={verdict} />}
          <Id value={node.id} />
        </>
      }
    >
      <div data-source={sourceAttribute(source)}>
        <InspectorSection label="Quantities">
          {node.quantities.length === 0 ? (
            <p className="pg-muted">This node records no quantities.</p>
          ) : (
            <ul className="pg-list">
              {node.quantities.map(([name, q]) => {
                const recorded = node.provenance[name];
                const by = writerActor(recorded?.writtenBy ?? null, config);
                return (
                  <li key={name} className="pg-quantity-row">
                    <span className="pg-list-row">
                      <span className="pg-list-row-main">
                        <span>{quantityLabel(name)}</span>
                        <Id value={name} copy={false} />
                      </span>
                      <Quantity {...q} />
                    </span>
                    <span className="pg-set-by">
                      Set by{" "}
                      {by === null ? (
                        <span>no writer recorded</span>
                      ) : (
                        <ActorTag actor={by} size="sm" />
                      )}
                      {recorded?.source !== null && recorded?.source !== undefined && (
                        <span className="pg-panel-note"> · from {recorded.source}</span>
                      )}
                    </span>
                    <SourceChip {...source} compact />
                  </li>
                );
              })}
            </ul>
          )}
        </InspectorSection>
        <InspectorSection label="Gate checks">
          {config.gateMode === "off" ? (
            <p className="pg-muted">The gate did not run in this run.</p>
          ) : latest.length === 0 ? (
            <p className="pg-muted">No gate check names this node.</p>
          ) : (
            <>
              <ul className="pg-list">
                {judged.map((c, i) => (
                  <li key={`j${String(i)}`} className="pg-list-row">
                    <span className="pg-list-row-main">
                      <CheckName check={c} />
                      <Id value={checkId(c)} copy={false} />
                    </span>
                    <GateOutcome mode={c.mode} outcome={c.outcome} />
                  </li>
                ))}
              </ul>
              {unchecked.length > 0 && (
                <>
                  <hr className="pg-sep" />
                  <ul className="pg-list" aria-label="Unchecked">
                    {unchecked.map((c, i) => (
                      <li key={`u${String(i)}`} className="pg-list-row">
                        <span className="pg-list-row-main">
                          <CheckName check={c} />
                          <span className="pg-panel-note">{c.message}</span>
                        </span>
                        <VerdictBadge verdict="unchecked" />
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </>
          )}
        </InspectorSection>
        <InspectorSection label="Constrains">
          {edges.constrains.length === 0 ? (
            <p className="pg-muted">It constrains no other node.</p>
          ) : (
            <ul className="pg-list">
              {edges.constrains.map((end) => (
                <Edge key={end.id} end={end} arrow="→" href={nodeHref} />
              ))}
            </ul>
          )}
        </InspectorSection>
        <InspectorSection label="Constrained by">
          {edges.constrainedBy.length === 0 ? (
            <p className="pg-muted">No node constrains this one.</p>
          ) : (
            <ul className="pg-list">
              {edges.constrainedBy.map((end) => (
                <Edge key={end.id} end={end} arrow="←" href={nodeHref} />
              ))}
            </ul>
          )}
        </InspectorSection>
        <InspectorSection label="History">
          {history === null ? (
            <LoadingState reading="the node's history" rows={1} />
          ) : !history.ok ? (
            <ErrorState
              title="The node's history could not be read"
              {...history.refusal}
              route={historyRoute}
              onRetry={onHistoryAgain}
            />
          ) : (
            <ol className="pg-list">
              {[...history.value.history].reverse().map((entry, index, newestFirst) => {
                const earlier = newestFirst[index + 1];
                const by = historyActor(entry.writtenBy, node, config);
                return (
                  <li key={entry.revision} className="pg-list-row pg-history-entry">
                    <span className="pg-list-row-main">
                      <span>
                        {entry.op === "create"
                          ? "Created"
                          : entry.op === "rollback"
                            ? "Rolled back"
                            : "Written"}{" "}
                        at revision r{entry.revision}
                        {entry.writtenBy !== null && entry.writtenBy !== "decomposition"
                          ? `, by attempt ${String(entry.writtenBy.attempt)}`
                          : ""}
                      </span>
                      {by === null ? (
                        <span className="pg-panel-note">no write recorded in the run's log</span>
                      ) : (
                        <ActorTag actor={by} size="sm" />
                      )}
                    </span>
                    {earlier === undefined ? (
                      <span className="pg-panel-note">first revision</span>
                    ) : (
                      <a className="pg-hit" href={diffHref(earlier.revision, entry.revision)}>
                        What changed r{earlier.revision} → r{entry.revision}
                      </a>
                    )}
                  </li>
                );
              })}
            </ol>
          )}
        </InspectorSection>
      </div>
    </Inspector>
  );
}
