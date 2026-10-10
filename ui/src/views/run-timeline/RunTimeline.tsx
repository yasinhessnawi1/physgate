/**
 * One run on its own clock: decomposition, each attempt with its sessions, gate and review, the
 * repairs and the findings that caused them, infrastructure outcomes and the integration call;
 * what it spent, by attribution and by model; its reviewers' verdicts; and its gate checks in its
 * mode. Every figure is the server's, from the reader the command line uses.
 */
import { useEffect } from "react";

import { getJson, getLines, type Result } from "../../api/client";
import { anyEvent, costRecord, priceDates, type RunConfig } from "../../api/records";
import {
  decisions as decisionSequence,
  gateCheck,
  runStatus,
  type RunStatus,
  timelineEvents,
  tokens as tokenAccount,
  trace as runTrace,
} from "../../api/run";
import { Figure } from "../../design/components/Figure";
import { type Source, SourceChip } from "../../design/components/SourceChip";
import { EmptyState, ErrorState, LoadingState } from "../../design/components/States";
import type { ViewProps } from "../../shell/header";
import { hrefFor } from "../../shell/route";
import { useConfigs } from "../common/configs";
import { RunPicker, runKey, runSource, useChosenRun } from "../common/runs";
import { useResult } from "../common/useResult";
import { GateChecksSummary } from "../gate-checks/GateChecksSummary";
import { PairedRun } from "../gate-checks/PairedRun";
import { pairable } from "../gate-checks/pairing";
import { ReviewsCard, SessionsCard, TokensCard } from "./Cards";
import { clock, StagesTable, TimelineChart } from "./Chart";
import { lanes } from "./model";

const AREA = "orchestration";
const SLUG = "run-timeline";

/** Where the run stands, in the loop's own words: done, escalated, halted, or not finished. */
export function StatusBadge({ status }: { status: RunStatus }) {
  if (status.kind === "done")
    return (
      <span className="badge status status-done">
        <span aria-hidden="true">✓</span> Completed
      </span>
    );
  if (status.kind === "escalated")
    return (
      <span className="badge status status-escalated">
        <span aria-hidden="true">!</span> Escalated
      </span>
    );
  if (status.kind === "halted")
    return (
      <span className="badge status status-halted">
        <span aria-hidden="true">✕</span> Halted · {status.halted?.reason ?? "no reason recorded"}
      </span>
    );
  return <span className="badge status status-open">Not finished · next: {status.kind}</span>;
}

function Loaded<T>({
  result,
  what,
  children,
}: {
  result: Result<T> | null;
  what: string;
  children: (value: T) => React.ReactNode;
}) {
  if (result === null) return <LoadingState reading={what} />;
  if (!result.ok) return <ErrorState title={`${what}: not shown`} refusal={result.refusal} />;
  return <>{children(result.value)}</>;
}

function Timeline({
  base,
  config,
  query,
  source,
  pairKey,
  configs,
  pairHref,
}: {
  base: string;
  config: RunConfig;
  query: URLSearchParams;
  source: Source;
  pairKey: string | null;
  configs: Result<ReadonlyMap<string, RunConfig>> | null;
  pairHref: (key: string | null) => string;
}) {
  const trace = useResult(() => getJson(`${base}/trace`, runTrace), `${base}/trace`);
  const decided = useResult(
    () => getJson(`${base}/decisions`, decisionSequence),
    `${base}/decisions`,
  );
  const status = useResult(() => getJson(`${base}/status`, runStatus), `${base}/status`);
  const tokens = useResult(() => getJson(`${base}/tokens`, tokenAccount), `${base}/tokens`);
  const events = useResult(() => getLines(`${base}/events`, anyEvent), `${base}/events`);
  const checks = useResult(() => getLines(`${base}/gate-checks`, gateCheck), `${base}/gate-checks`);
  const prices = useResult(() => getJson("/api/prices", priceDates), "/api/prices");
  const newest = prices?.ok === true ? prices.value.at(-1) : undefined;
  const cost = useResult(
    newest === undefined ? null : () => getJson(`${base}/cost/${newest}`, costRecord),
    `${base}/cost/${String(newest)}`,
  );
  if (trace === null || decided === null || events === null || status === null)
    return <LoadingState reading="the run's trace and event log" />;
  for (const [answer, what] of [
    [trace, "The trace"],
    [decided, "The decisions"],
    [events, "The event log"],
    [status, "The run's status"],
  ] as const) {
    if (!answer.ok) return <ErrorState title={`${what}: not shown`} refusal={answer.refusal} />;
  }
  if (!trace.ok || !decided.ok || !events.ok || !status.ok) return null;
  const named = timelineEvents(events.value);
  const drawn = lanes(trace.value, decided.value, named, config.gateMode, config.roleModels);
  return (
    <>
      <div
        className="run-head"
        data-source={`${source.id}@${(source.commit ?? "no commit").slice(0, 7)}`}
      >
        <div className="run-head-titles">
          <div className="title-with-badge">
            <h2 className="section-title mono">{config.runId}</h2>
            <StatusBadge status={status.value} />
          </div>
          <div className="title-with-badge">
            <SourceChip source={source} />
            <span className="source-chip">
              manifest <span className="mono">{config.manifestId.slice(0, 8)}</span>
            </span>
            <span className="label">
              started <span className="mono">{clock(trace.value.started)}</span> UTC ·{" "}
              {named.decomposed === null
                ? "no decomposition recorded"
                : `${String(named.decomposed.subtasks)} planned ${named.decomposed.subtasks === 1 ? "subtask" : "subtasks"}`}{" "}
              · View: <span className="mono">{trace.value.sessions.length}</span>{" "}
              {trace.value.sessions.length === 1 ? "session" : "sessions"}
            </span>
          </div>
        </div>
        <div className="run-head-figures">
          {cost?.ok === true && (
            <div className="headline">
              <span className="label">
                {cost.value.basis === "list_price_estimate"
                  ? "Cost (list-price estimate)"
                  : "Cost (list price)"}
              </span>
              <Figure q={cost.value.usd} source={source} />
            </div>
          )}
          {tokens?.ok === true && (
            <div className="headline">
              <span className="label">Output tokens</span>
              <Figure q={{ value: tokens.value.total.output, unit: "tok" }} source={source} />
            </div>
          )}
        </div>
      </div>
      <TimelineChart
        lanes={drawn}
        started={trace.value.started}
        last={trace.value.last}
        source={source}
      />
      <div className="split">
        <div className="split-main">
          <Loaded result={checks} what="Gate checks">
            {(value) => (
              <GateChecksSummary
                checks={value}
                mode={config.gateMode}
                source={source}
                manifestId={config.manifestId}
              >
                <a
                  className="button button-browse"
                  href={hrefFor(AREA, "gate-checks", new URLSearchParams(query))}
                >
                  Open every check
                </a>
              </GateChecksSummary>
            )}
          </Loaded>
          <SessionsCard sessions={trace.value.sessions} source={source} />
          <Loaded result={tokens} what="Tokens">
            {(value) => (
              <TokensCard
                tokens={value}
                cost={cost?.ok === true ? cost.value : null}
                source={source}
              />
            )}
          </Loaded>
          <StagesTable steps={trace.value.steps} source={source} />
        </div>
        <div className="split-side">
          <ReviewsCard reviews={named.reviews} source={source} />

          {configs === null ? (
            <LoadingState reading="the other runs' configurations" />
          ) : configs.ok ? (
            <PairedRun
              candidates={pairable(config, configs.value)}
              pairKey={pairKey}
              pairHref={pairHref}
            />
          ) : (
            <ErrorState title="The other runs could not be read" refusal={configs.refusal} />
          )}
        </div>
      </div>
    </>
  );
}

export default function RunTimeline({ setHeader, query }: ViewProps) {
  const { runs, chosen, config, base } = useChosenRun(query);
  const configs = useConfigs(runs?.ok === true ? runs.value : null);
  useEffect(() => {
    if (config?.ok === true)
      setHeader({
        title: "Run timeline",
        source: runSource(config.value),
        gateMode: config.value.gateMode,
      });
  }, [config, setHeader]);
  if (runs === null) return <LoadingState reading="the run list" />;
  if (!runs.ok) return <ErrorState title="The run list was refused" refusal={runs.refusal} />;
  if (chosen === undefined || base === null)
    return (
      <EmptyState title="No runs under the roots yet">
        A run's timeline appears here once a run directory exists under a root this server was
        started with.
      </EmptyState>
    );
  const pairHref = (key: string | null) => {
    const next = new URLSearchParams(query);
    next.set("run", runKey(chosen));
    if (key === null) next.delete("pair");
    else next.set("pair", key);
    return hrefFor(AREA, SLUG, next);
  };
  return (
    <div className="view">
      <RunPicker runs={runs.value} chosen={chosen} area={AREA} slug={SLUG} />
      {config === null ? (
        <LoadingState reading="run.json" />
      ) : config.ok ? (
        <Timeline
          key={base}
          base={base}
          config={config.value}
          query={query}
          source={runSource(config.value)}
          pairKey={query.get("pair")}
          configs={configs}
          pairHref={pairHref}
        />
      ) : (
        <ErrorState title="The run's configuration was refused" refusal={config.refusal} />
      )}
    </div>
  );
}
