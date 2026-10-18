/**
 * The design-state graph of one run: drawn, tabled, or two revisions compared. Each node leads
 * with its key in plain words, the key itself under it, its domain, its latest gate verdict and
 * a few of its quantities. A selected node opens in the inspector with every quantity, who set
 * it, its gate checks, its edges both ways and its history. Where the screen is lives in the
 * address (run, revision, node, domain, view, diff), so a link keeps it.
 */
import { type SyntheticEvent, useEffect, useMemo, useState } from "react";

import { type GraphAt, graphAt, graphDiff, nodeHistory, type NodeRecord } from "../../api/graph";
import type { RunConfig } from "../../api/records";
import { type GateCheck, gateCheck } from "../../api/run";
import { Button } from "../../design/components/actions/Button";
import { Segmented } from "../../design/components/actions/Segmented";
import { SourceChip } from "../../design/components/data/SourceChip";
import { type Source, sourceAttribute } from "../../design/components/data/source";
import { GraphCanvas } from "../../design/components/graph/GraphCanvas";
import { EmptyState, ErrorState, LoadingState } from "../../design/components/status/States";
import { type PaletteEntry, usePaletteEntries } from "../../shell/palette";
import type { ViewProps } from "../../shell/header";
import { InspectorPortal } from "../../shell/inspector";
import { hrefFor } from "../../shell/route";
import { nodeLabel, quantityLabel } from "../../words/humanise";
import { useJson, useLines } from "../common/read";
import { RunSwitcher } from "../common/RunSwitcher";
import { inProgress, runSource, useChosenRun } from "../common/runs";
import { DiffView } from "./DiffView";
import { missingTargets } from "./edges";
import { NodeInspector } from "./NodeInspector";
import { NodesTable } from "./NodesTable";
import { nodeVerdicts } from "./verdicts";

const AREA = "orchestration";
const SLUG = "design-graph";
/** The domain filter's "every domain" choice. */
const ALL = "all";
/** How many of a node's quantities its card shows; the inspector shows them all. */
const ON_CARD = 3;

type Mode = "graph" | "table" | "diff";

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

const DOMAIN_WORDS: Readonly<Record<string, string>> = {
  mechanical: "Mechanical",
  electrical: "Electrical",
  control: "Control",
  firmware: "Firmware",
  cross: "Cross-domain",
};

function CompareForm({
  head,
  initial,
  onShow,
}: {
  readonly head: number;
  readonly initial: readonly [number, number];
  readonly onShow: (from: number, to: number) => void;
}) {
  const [from, setFrom] = useState(initial[0]);
  const [to, setTo] = useState(initial[1]);
  const revisions = Array.from({ length: head + 1 }, (_, r) => r);
  const submit = (event: SyntheticEvent) => {
    event.preventDefault();
    onShow(Math.min(from, to), Math.max(from, to));
  };
  return (
    <form className="pg-toolbar pg-compare" aria-label="Compare revisions" onSubmit={submit}>
      <label className="pg-label" htmlFor="compare-from">
        From revision
      </label>
      <span className="pg-field">
        <select
          id="compare-from"
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
      </span>
      <label className="pg-label" htmlFor="compare-to">
        to revision
      </label>
      <span className="pg-field">
        <select
          id="compare-to"
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
      </span>
      <Button type="submit">Show the changes</Button>
    </form>
  );
}

function Explorer({
  base,
  graph,
  checks,
  config,
  query,
  source,
  runLabel,
}: {
  readonly base: string;
  readonly graph: GraphAt;
  readonly checks: readonly GateCheck[];
  readonly config: RunConfig;
  readonly query: URLSearchParams;
  readonly source: Source;
  readonly runLabel: string;
}) {
  const mode: Mode =
    query.get("view") === "table" ? "table" : query.get("view") === "diff" ? "diff" : "graph";
  const domain = query.get("domain");
  const domains = [...new Set(graph.nodes.map((n) => n.domain))].sort();
  const shown: readonly NodeRecord[] =
    domain === null ? graph.nodes : graph.nodes.filter((n) => n.domain === domain);
  const selectedId = query.get("node");
  const selected = graph.nodes.find((n) => n.id === selectedId) ?? null;
  const verdicts = useMemo(() => nodeVerdicts(checks), [checks]);
  const history = useJson(
    selected === null ? null : `${base}/graph/history/${encodeURIComponent(selected.id)}`,
    nodeHistory,
  );
  const diff = parseDiff(query.get("diff"));
  const diffRead = useJson(
    diff === null || mode !== "diff"
      ? null
      : `${base}/graph/diff/${String(diff[0])}/${String(diff[1])}`,
    graphDiff,
  );
  const select = (id: string) => {
    go(withQuery(query, { node: id }));
  };
  const diffHref = (from: number, to: number) =>
    withQuery(query, { view: "diff", diff: `${String(from)}-${String(to)}` });
  const edges = shown.flatMap((n) => n.constrains.map((to) => ({ from: n.id, to })));
  const drawn = edges.filter((e) => shown.some((n) => n.id === e.to));
  const missing = missingTargets(graph.nodes);
  const canvasNodes = shown.map((n) => {
    const verdict = config.gateMode === "off" ? undefined : verdicts.get(n.id);
    return {
      id: n.id,
      label: nodeLabel(n.id, n.domain),
      kind: n.kind,
      domain: n.domain,
      quantities: n.quantities.slice(0, ON_CARD).map(([name, q]) => ({
        name: quantityLabel(name),
        value: q.value,
        unit: q.unit,
      })),
      ...(verdict === undefined ? {} : { verdict }),
    };
  });
  // The command palette lists the graph's nodes while this screen is shown.
  const entries = useMemo<PaletteEntry[]>(
    () =>
      graph.nodes.map((n) => {
        const verdict = verdicts.get(n.id);
        return {
          id: `node-${n.id}`,
          section: "Nodes in this run's graph",
          label: `${nodeLabel(n.id, n.domain)} · ${n.id}${verdict === undefined ? "" : ` · ${verdict}`}`,
          run: () => {
            go(withQuery(query, { node: n.id, view: null }));
          },
        };
      }),
    [graph.nodes, verdicts, query],
  );
  usePaletteEntries(entries);
  return (
    <div className="pg-screen pg-graph-screen">
      <div className="pg-toolbar">
        <Segmented
          label="Show the graph as"
          value={mode}
          onChange={(m) => {
            go(withQuery(query, { view: m === "graph" ? null : m }));
          }}
          options={[
            { value: "graph", label: "Graph", icon: "network" },
            { value: "table", label: "Table", icon: "table" },
            { value: "diff", label: "Changes", icon: "git-compare" },
          ]}
        />
        {mode !== "diff" && (
          <>
            <label className="pg-label" htmlFor="revision">
              Revision
            </label>
            <span className="pg-field">
              <select
                id="revision"
                value={graph.revision}
                onChange={(e) => {
                  go(withQuery(query, { rev: e.target.value, node: null }));
                }}
              >
                {Array.from(
                  { length: graph.headRevision + 1 },
                  (_, i) => graph.headRevision - i,
                ).map((r) => (
                  <option key={r} value={r}>
                    r{r}
                    {r === graph.headRevision ? " · latest" : ""}
                  </option>
                ))}
              </select>
            </span>
            <Segmented
              label="Domain filter"
              value={domain ?? ALL}
              onChange={(d) => {
                go(withQuery(query, { domain: d === ALL ? null : d }));
              }}
              options={[
                { value: ALL, label: "All domains" },
                ...domains.map((d) => ({ value: d, label: DOMAIN_WORDS[d] ?? d })),
              ]}
            />
          </>
        )}
      </div>
      {mode === "diff" ? (
        <>
          <CompareForm
            head={graph.headRevision}
            initial={diff ?? [Math.max(graph.headRevision - 1, 0), graph.headRevision]}
            onShow={(from, to) => {
              go(diffHref(from, to));
            }}
          />
          {diff === null ? (
            <EmptyState title="Choose two revisions to compare" icon="git-compare">
              The store's own list of changes between them is shown, with each changed node's
              quantities at both.
            </EmptyState>
          ) : diffRead.result === null ? (
            <LoadingState reading="the change list" />
          ) : diffRead.result.ok ? (
            <DiffView diff={diffRead.result.value} source={source} />
          ) : (
            <ErrorState
              title="The changes between these revisions could not be read"
              {...diffRead.result.refusal}
              route={diffRead.route}
              onRetry={diffRead.again}
            />
          )}
        </>
      ) : mode === "table" ? (
        <NodesTable
          nodes={shown}
          all={graph.nodes}
          verdicts={verdicts}
          gateMode={config.gateMode}
          source={source}
          hrefFor={(id) => withQuery(query, { node: id })}
        />
      ) : (
        <section
          className="pg-card pg-panel"
          aria-label="Graph"
          data-source={sourceAttribute(source)}
        >
          <p className="pg-panel-note">
            View: {shown.length} nodes and {drawn.length} edges at revision r{graph.revision}.
            Arrows point from the node that constrains to the one it constrains; an edge between two
            domains is dashed.
          </p>
          {shown.length === 0 ? (
            <EmptyState title="The graph holds no nodes at this revision" />
          ) : (
            <GraphCanvas
              nodes={canvasNodes}
              edges={drawn}
              selected={selected?.id ?? null}
              onSelect={select}
              gateMode={config.gateMode === "observe" ? "observe" : "on"}
            />
          )}
          {missing.length > 0 && (
            <p className="pg-panel-note">
              Edges to nodes the graph does not hold at this revision:{" "}
              {missing.map(([from, to]) => (
                <span key={`${from}>${to}`} className="mono">
                  {from} → {to}{" "}
                </span>
              ))}
            </p>
          )}
          <SourceChip {...source} />
        </section>
      )}
      {selected !== null && (
        <InspectorPortal>
          <NodeInspector
            node={selected}
            nodes={graph.nodes}
            checks={checks}
            config={config}
            history={history.result}
            historyRoute={history.route}
            onHistoryAgain={history.again}
            source={source}
            runLabel={runLabel}
            diffHref={diffHref}
            nodeHref={(id) => withQuery(query, { node: id })}
          />
        </InspectorPortal>
      )}
    </div>
  );
}

export default function DesignGraph({ setHeader, query }: ViewProps) {
  const chosen = useChosenRun(query);
  const { runs, config, status, base, label } = chosen;
  const revision = query.get("rev");
  const route =
    base === null
      ? null
      : revision !== null && /^(0|[1-9]\d{0,8})$/.test(revision)
        ? `${base}/graph/at/${revision}`
        : `${base}/graph`;
  const graph = useJson(route, graphAt);
  const checks = useLines(base === null ? null : `${base}/gate-checks`, gateCheck);
  const configValue = config?.ok === true ? config.value : undefined;
  const going = status?.ok === true && inProgress(status.value);
  useEffect(() => {
    if (runs?.ok === true && runs.value.length === 0)
      setHeader({ title: "Design graph", runState: "none" });
    else if (config?.ok === false || runs?.ok === false || graph.result?.ok === false)
      setHeader({ title: "Design graph", runState: "unread" });
    else if (configValue !== undefined)
      setHeader({
        title: "Design graph",
        source: runSource(configValue),
        gateMode: configValue.gateMode,
        osLayer: configValue.osLayer,
        inProgress: going,
        ...(label === undefined ? {} : { run: label }),
      });
  }, [runs, config, configValue, going, label, setHeader, graph.result]);
  if (runs === null) return <LoadingState reading="the run list" />;
  if (!runs.ok)
    return (
      <ErrorState title="The run list could not be read" {...runs.refusal} route="/api/runs" />
    );
  if (chosen.chosen === undefined || base === null)
    return (
      <EmptyState title="No run to show yet">
        A run's design graph appears here once a run is recorded on this machine.
      </EmptyState>
    );
  const switcher = (
    <RunSwitcher
      runs={runs.value}
      chosen={chosen.chosen}
      labels={chosen.labels}
      area={AREA}
      slug={SLUG}
      allShown={chosen.allShown}
      showAll={chosen.showAll}
    />
  );
  const body =
    config === null || graph.result === null || checks.result === null ? (
      <LoadingState reading="the design graph" />
    ) : !config.ok ? (
      <ErrorState
        title="The run's configuration could not be read"
        {...config.refusal}
        onRetry={chosen.again}
      />
    ) : !graph.result.ok ? (
      <ErrorState
        title="The design graph could not be read. Nothing is shown rather than a partial graph."
        {...graph.result.refusal}
        route={graph.route}
        onRetry={graph.again}
      />
    ) : !checks.result.ok ? (
      <ErrorState
        title="The gate checks could not be read"
        {...checks.result.refusal}
        route={checks.route}
        onRetry={checks.again}
      />
    ) : (
      <Explorer
        base={base}
        graph={graph.result.value}
        checks={checks.result.value}
        config={config.value}
        query={query}
        source={runSource(config.value)}
        runLabel={label?.label ?? `Run ${chosen.chosen.name}`}
      />
    );
  return (
    <div className="pg-screen">
      {switcher}
      {body}
    </div>
  );
}
