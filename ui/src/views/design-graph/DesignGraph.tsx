/**
 * The design-graph explorer: the run's graph at any journal revision, drawn and tabled, one node
 * inspected (quantities, edges both ways, history), and the store's own diff between two
 * revisions. Every figure is read from the run's journal through the server's read routes.
 * Where the view is in the hash's query (run, revision, node, domain, diff), so a link keeps it.
 */
import { type SyntheticEvent, useEffect, useState } from "react";

import { getJson } from "../../api/client";
import { type GraphAt, graphAt, graphDiff, nodeHistory, type NodeRecord } from "../../api/graph";
import { GraphCanvas } from "../../design/components/GraphCanvas";
import { type Source, sourceAttribute } from "../../design/components/SourceChip";
import { EmptyState, ErrorState, LoadingState } from "../../design/components/States";
import type { ViewProps } from "../../shell/header";
import { hrefFor } from "../../shell/route";
import { RunPicker, runSource, useChosenRun } from "../common/runs";
import { useResult } from "../common/useResult";
import { DiffCard } from "./DiffCard";
import { missingTargets } from "./edges";
import { Inspector } from "./Inspector";
import { NodesTable } from "./NodesTable";

const AREA = "orchestration";

export function quantitiesLabel(n: number): string {
  return `${String(n)} ${n === 1 ? "quantity" : "quantities"}`;
}
const SLUG = "design-graph";

function withQuery(query: URLSearchParams, changes: Record<string, string | null>): string {
  const next = new URLSearchParams(query);
  for (const [key, value] of Object.entries(changes)) {
    if (value === null) next.delete(key);
    else next.set(key, value);
  }
  return hrefFor(AREA, SLUG, next);
}

function go(href: string) {
  window.location.hash = href.slice(1);
}

/** ``from-to`` as two revisions, or ``null``. */
export function parseDiff(value: string | null): readonly [number, number] | null {
  const found = value === null ? null : /^(\d{1,9})-(\d{1,9})$/.exec(value);
  if (found === null) return null;
  return [Number(found[1]), Number(found[2])];
}

function CompareForm({
  head,
  onShow,
}: {
  head: number;
  onShow: (from: number, to: number) => void;
}) {
  const [from, setFrom] = useState(Math.max(head - 1, 0));
  const [to, setTo] = useState(head);
  const revisions = Array.from({ length: head + 1 }, (_, r) => r);
  const submit = (event: SyntheticEvent) => {
    event.preventDefault();
    onShow(Math.min(from, to), Math.max(from, to));
  };
  return (
    <form className="compare-form" aria-label="Compare revisions" onSubmit={submit}>
      <label className="label" htmlFor="compare-from">
        From
      </label>
      <select
        id="compare-from"
        className="select"
        value={from}
        onChange={(e) => {
          setFrom(Number(e.target.value));
        }}
      >
        {revisions.map((r) => (
          <option key={r} value={r}>
            r{r}
          </option>
        ))}
      </select>
      <label className="label" htmlFor="compare-to">
        To
      </label>
      <select
        id="compare-to"
        className="select"
        value={to}
        onChange={(e) => {
          setTo(Number(e.target.value));
        }}
      >
        {revisions.map((r) => (
          <option key={r} value={r}>
            r{r}
          </option>
        ))}
      </select>
      <button type="submit" className="button button-browse">
        Show the diff
      </button>
    </form>
  );
}

function Explorer({
  base,
  graph,
  query,
  source,
}: {
  base: string;
  graph: GraphAt;
  query: URLSearchParams;
  source: Source;
}) {
  const domain = query.get("domain");
  const domains = [...new Set(graph.nodes.map((n) => n.domain))].sort();
  const shown: readonly NodeRecord[] =
    domain === null ? graph.nodes : graph.nodes.filter((n) => n.domain === domain);
  const selectedId = query.get("node");
  const selected = graph.nodes.find((n) => n.id === selectedId) ?? null;
  const history = useResult(
    selected === null ? null : () => getJson(`${base}/graph/history/${selected.id}`, nodeHistory),
    `${base}/graph/history/${String(selected?.id)}`,
  );
  const diff = parseDiff(query.get("diff"));
  const diffResult = useResult(
    diff === null
      ? null
      : () => getJson(`${base}/graph/diff/${String(diff[0])}/${String(diff[1])}`, graphDiff),
    `${base}/graph/diff/${String(diff?.[0])}/${String(diff?.[1])}`,
  );
  const [comparing, setComparing] = useState(false);
  const select = (id: string) => {
    go(withQuery(query, { node: id }));
  };
  const diffHref = (from: number, to: number) =>
    withQuery(query, { diff: `${String(from)}-${String(to)}` });
  const edges = shown.flatMap((n) => n.constrains.map((to) => ({ from: n.id, to })));
  const drawn = edges.filter((e) => shown.some((n) => n.id === e.to));
  const missing = missingTargets(graph.nodes);
  return (
    <div className="explorer">
      <div className="toolbar">
        <h2 className="section-title">Design-state graph</h2>
        <label className="label" htmlFor="revision">
          Revision
        </label>
        <select
          id="revision"
          className="select"
          value={graph.revision}
          onChange={(e) => {
            go(withQuery(query, { rev: e.target.value, node: null }));
          }}
        >
          {Array.from({ length: graph.headRevision + 1 }, (_, i) => graph.headRevision - i).map(
            (r) => (
              <option key={r} value={r}>
                r{r}
                {r === graph.headRevision ? " · latest" : ""}
              </option>
            ),
          )}
        </select>
        <div className="segmented" role="group" aria-label="Domain filter">
          <button
            type="button"
            aria-pressed={domain === null}
            onClick={() => {
              go(withQuery(query, { domain: null }));
            }}
          >
            All domains
          </button>
          {domains.map((d) => (
            <button
              key={d}
              type="button"
              aria-pressed={domain === d}
              onClick={() => {
                go(withQuery(query, { domain: d }));
              }}
            >
              {d}
            </button>
          ))}
        </div>
        <button
          type="button"
          className="button button-browse"
          aria-expanded={comparing}
          onClick={() => {
            setComparing((c) => !c);
          }}
        >
          Compare revisions…
        </button>
      </div>
      {comparing && (
        <CompareForm
          head={graph.headRevision}
          onShow={(from, to) => {
            go(diffHref(from, to));
          }}
        />
      )}
      {diff !== null &&
        (diffResult === null ? (
          <LoadingState reading="the change list" />
        ) : diffResult.ok ? (
          <DiffCard diff={diffResult.value} source={source} />
        ) : (
          <ErrorState title="Diff: not shown" refusal={diffResult.refusal} />
        ))}
      <div className="explorer-main">
        <section
          className="card graph-card"
          aria-label="Graph"
          data-source={sourceAttribute(source)}
        >
          <div className="card-head">
            <p className="label">
              View: <span className="mono">{shown.length}</span> nodes,{" "}
              <span className="mono">{drawn.length}</span> constrains edges at{" "}
              <span className="mono">r{graph.revision}</span>. Arrows point from the constraining
              node to the constrained one.
            </p>
            <span className="label">Layout: layered, left to right</span>
          </div>
          {shown.length === 0 ? (
            <EmptyState title="The graph holds no nodes at this revision" />
          ) : (
            <GraphCanvas
              nodes={shown.map((n) => ({
                id: n.id,
                kind: n.kind,
                domain: n.domain,
                summary: quantitiesLabel(n.quantities.length),
              }))}
              edges={drawn}
              selected={selected?.id ?? null}
              onSelect={select}
            />
          )}
          {missing.length > 0 && (
            <p className="view-note">
              Edges to nodes the graph does not hold at this revision:{" "}
              {missing.map(([from, to]) => (
                <span key={`${from}>${to}`} className="mono">
                  {from} → {to}{" "}
                </span>
              ))}
            </p>
          )}
        </section>
        {selected === null ? (
          <aside className="card inspector" aria-label="Node inspector">
            <EmptyState title="Choose a node">
              Select a node in the graph or the table to see its quantities, its edges and its
              history.
            </EmptyState>
          </aside>
        ) : (
          <Inspector
            node={selected}
            nodes={graph.nodes}
            history={history}
            source={source}
            diffHref={diffHref}
          />
        )}
      </div>
      <NodesTable nodes={shown} source={source} hrefFor={(id) => withQuery(query, { node: id })} />
    </div>
  );
}

export default function DesignGraph({ setHeader, query }: ViewProps) {
  const { runs, chosen, config, base } = useChosenRun(query);
  const revision = query.get("rev");
  const route =
    base === null
      ? null
      : revision !== null && /^(0|[1-9]\d{0,8})$/.test(revision)
        ? `${base}/graph/at/${revision}`
        : `${base}/graph`;
  const graph = useResult(route === null ? null : () => getJson(route, graphAt), String(route));
  useEffect(() => {
    if (config?.ok === true) {
      setHeader({
        title: "Design graph",
        source: runSource(config.value),
        gateMode: config.value.gateMode,
      });
    }
  }, [config, setHeader]);
  if (runs === null) return <LoadingState reading="the run list" />;
  if (!runs.ok) return <ErrorState title="The run list was refused" refusal={runs.refusal} />;
  if (chosen === undefined || base === null)
    return (
      <EmptyState title="No runs under the roots yet">
        A run's graph appears here once a run directory exists under a root this server was started
        with.
      </EmptyState>
    );
  return (
    <div className="view">
      <RunPicker runs={runs.value} chosen={chosen} area={AREA} slug={SLUG} />
      {config === null || graph === null ? (
        <LoadingState reading="the graph journal" />
      ) : !config.ok ? (
        <ErrorState title="The run's configuration was refused" refusal={config.refusal} />
      ) : !graph.ok ? (
        <ErrorState title="The graph was refused" refusal={graph.refusal} />
      ) : (
        <Explorer base={base} graph={graph.value} query={query} source={runSource(config.value)} />
      )}
    </div>
  );
}
