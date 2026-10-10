/**
 * The smoke page: one run's records read end to end through every read route, each shown with
 * the components the rest of the app uses. It proves the plumbing; the views proper arrive in
 * the focus areas later. Every figure here is read from a record and carries its source; the
 * only things this page computes are counts over a record, and each says it is a view.
 */
import { type ReactNode, useEffect } from "react";

import { getJson, getLines, type Result } from "../../api/client";
import {
  anyEvent,
  costRecord,
  gateEventLine,
  graphRecord,
  ledgerLine,
  type LedgerLine,
  priceDates,
  type RunConfig,
  runConfig,
  type RunListing,
  runListing,
  sealedSessions,
} from "../../api/records";
import { Figure } from "../../design/components/Figure";
import { GateModeBadge, GateOutcome } from "../../design/components/GateMode";
import { GraphCanvas } from "../../design/components/GraphCanvas";
import { Quantity } from "../../design/components/Quantity";
import { type Source, SourceChip, sourceAttribute } from "../../design/components/SourceChip";
import { EmptyState, ErrorState, LoadingState } from "../../design/components/States";
import { Tally, VerdictBadge } from "../../design/components/VerdictBadge";
import { tallyOf } from "../../design/tally";
import type { ViewProps } from "../../shell/header";
import { hrefFor } from "../../shell/route";
import { useResult } from "../common/useResult";

/** A card that shows its record, or the reading state, or the refusal, and nothing partial. */
function Card<T>({
  title,
  reading,
  result,
  children,
}: {
  title: string;
  reading: string;
  result: Result<T> | null;
  children: (value: T) => ReactNode;
}) {
  return (
    <section className="card" aria-label={title}>
      <h2 className="card-title">{title}</h2>
      {result === null ? (
        <LoadingState reading={reading} />
      ) : result.ok ? (
        children(result.value)
      ) : (
        <ErrorState title={`${title}: not shown`} refusal={result.refusal} />
      )}
    </section>
  );
}

function ledgerVerdict(mode: RunConfig["gateMode"], result: LedgerLine["gate"]) {
  if (result === null) return <span className="muted">not run</span>;
  if (result === "skipped") return <span className="muted">skipped · gate off</span>;
  return <GateOutcome mode={mode} outcome={result} />;
}

function reviewVerdict(result: LedgerLine["review"]) {
  if (result === null) return <span className="muted">not run</span>;
  if (result === "skipped") return <span className="muted">skipped</span>;
  return <VerdictBadge verdict={result} />;
}

function RunView({ listing, config }: { listing: RunListing; config: RunConfig }) {
  const base = `/api/runs/${String(listing.root)}/${encodeURIComponent(listing.name)}`;
  const source: Source = { id: `run ${config.runId}`, commit: config.harnessCommit };
  const ledger = useResult(() => getLines(`${base}/ledger`, ledgerLine), `${base}/ledger`);
  const gates = useResult(
    () => getLines(`${base}/gate-events`, gateEventLine),
    `${base}/gate-events`,
  );
  const graph = useResult(() => getJson(`${base}/graph`, graphRecord), `${base}/graph`);
  const events = useResult(() => getLines(`${base}/events`, anyEvent), `${base}/events`);
  const prices = useResult(() => getJson("/api/prices", priceDates), "/api/prices");
  const newest = prices?.ok === true ? prices.value.at(-1) : undefined;
  const cost = useResult(
    newest === undefined ? null : () => getJson(`${base}/cost/${newest}`, costRecord),
    `${base}/cost/${String(newest)}`,
  );
  const sessions = events?.ok === true ? sealedSessions(events.value) : [];
  const first = sessions[0];
  const trajectory = useResult(
    first === undefined
      ? null
      : () => getLines(`${base}/trajectories/${first.sessionId}`, anyEvent),
    `${base}/trajectories/${String(first?.sessionId)}`,
  );
  return (
    <div className="cards">
      <section className="card" aria-label="Configuration">
        <h2 className="card-title">Configuration</h2>
        <dl className="facts">
          <dt>Run</dt>
          <dd className="mono" data-source={sourceAttribute(source)}>
            {config.runId}
          </dd>
          <dt>Gate mode</dt>
          <dd>
            <GateModeBadge mode={config.gateMode} />
          </dd>
          <dt>Manifest id</dt>
          <dd className="mono digest" data-source={sourceAttribute(source)}>
            {config.manifestId}
          </dd>
          <dt>Harness commit</dt>
          <dd className="mono">{config.harnessCommit ?? "no commit"}</dd>
        </dl>
        <SourceChip source={source} />
      </section>

      <Card title="Task ledger" reading="ledger.jsonl" result={ledger}>
        {(lines) =>
          lines.length === 0 ? (
            <EmptyState title="No ledger lines yet">The run has dispatched nothing.</EmptyState>
          ) : (
            <>
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Subtask</th>
                    <th scope="col">Role</th>
                    <th scope="col">Attempts</th>
                    <th scope="col">Gate</th>
                    <th scope="col">Review</th>
                    <th scope="col">Merge</th>
                  </tr>
                </thead>
                <tbody>
                  {lines.map((line, index) => (
                    <tr key={String(index)} data-source={sourceAttribute(source)}>
                      <td className="mono">{line.id}</td>
                      <td>{line.role}</td>
                      <td className="mono">{line.attempts}</td>
                      <td>{ledgerVerdict(config.gateMode, line.gate)}</td>
                      <td>{reviewVerdict(line.review)}</td>
                      <td className="mono">{line.mergeCommit?.slice(0, 7) ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <SourceChip source={source} />
            </>
          )
        }
      </Card>

      <Card title="Gate checks" reading="the gate events" result={gates}>
        {(lines) => {
          if (lines.length === 0)
            return (
              <EmptyState title="No gate checks recorded">
                The gate has not run in this run.
              </EmptyState>
            );
          const counts = tallyOf(lines.map((line) => line.outcome));
          return (
            <>
              <p className="view-note" data-source={sourceAttribute(source)}>
                View: counted from <span className="mono">{lines.length}</span> gate events.
              </p>
              <Tally counts={counts} observed={config.gateMode === "observe"} />
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Seq</th>
                    <th scope="col">Subtask</th>
                    <th scope="col">Check</th>
                    <th scope="col">Outcome</th>
                    <th scope="col">Value</th>
                    <th scope="col">Node</th>
                    <th scope="col">Reviewer had passed</th>
                  </tr>
                </thead>
                <tbody>
                  {lines.map((line, index) => (
                    <tr key={String(index)} data-source={sourceAttribute(source)}>
                      <td className="mono">{line.seq}</td>
                      <td className="mono">{line.subtask}</td>
                      <td>
                        {line.check} <span className="muted">· {line.scope}</span>
                      </td>
                      <td>
                        <GateOutcome mode={line.mode} outcome={line.outcome} />
                      </td>
                      <td>{line.value === null ? "—" : <Quantity q={line.value} />}</td>
                      <td className="mono">{line.node ?? "—"}</td>
                      <td>
                        {line.reviewerHadPassed === null
                          ? "no review"
                          : line.reviewerHadPassed
                            ? "yes"
                            : "no"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <SourceChip source={source} />
            </>
          );
        }}
      </Card>

      <Card title="Design graph" reading="the graph journal" result={graph}>
        {(record) =>
          record.nodes.length === 0 ? (
            <EmptyState title="The graph holds no nodes yet" />
          ) : (
            <>
              <p className="view-note" data-source={sourceAttribute(source)}>
                Journal head revision <span className="mono">{record.headRevision}</span>.
              </p>
              <GraphCanvas
                nodes={record.nodes}
                edges={record.nodes.flatMap((node) =>
                  node.constrains.map((to) => ({ from: node.id, to })),
                )}
              />
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Node</th>
                    <th scope="col">Quantity</th>
                    <th scope="col">Value</th>
                  </tr>
                </thead>
                <tbody>
                  {record.nodes.flatMap((node) =>
                    node.quantities.map(([name, q]) => (
                      <tr key={`${node.id}.${name}`}>
                        <td className="mono">{node.id}</td>
                        <td>{name}</td>
                        <td>
                          <Figure q={q} source={source} />
                        </td>
                      </tr>
                    )),
                  )}
                </tbody>
              </table>
            </>
          )
        }
      </Card>

      <Card title="Cost" reading="the token account" result={cost}>
        {(line) => (
          <>
            <p className="view-note">
              {line.basis === "list_price_estimate"
                ? "A list-price estimate: the subscription is not billed per token."
                : "The tokens at the sheet's list prices."}{" "}
              Price sheet of <span className="mono">{line.pricesDate}</span>
              {line.partial ? " · partial: some usage was read from an unfinished stream" : ""}.
            </p>
            <div className="figures">
              <Figure q={line.usd} source={source} />
              <Figure q={line.nok} source={source} />
            </div>
          </>
        )}
      </Card>

      <Card title="Trajectories" reading="the sealed streams" result={events}>
        {() =>
          first === undefined ? (
            <EmptyState title="No sealed trajectory">
              No session of this run ended with a captured stream.
            </EmptyState>
          ) : (
            <>
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Session</th>
                    <th scope="col">Subtask</th>
                    <th scope="col">Attempt</th>
                    <th scope="col">Sealed length</th>
                  </tr>
                </thead>
                <tbody>
                  {sessions.map((session) => (
                    <tr key={session.sessionId}>
                      <td className="mono">{session.sessionId.slice(0, 8)}</td>
                      <td className="mono">{session.subtask}</td>
                      <td className="mono">{session.attempt}</td>
                      <td>
                        <Figure q={session.length} source={source} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="view-note">
                {trajectory === null
                  ? "Reading the first sealed stream…"
                  : trajectory.ok
                    ? "The first sealed stream was read whole and matched its seal."
                    : `The first sealed stream was refused: ${trajectory.refusal.error}`}
              </p>
            </>
          )
        }
      </Card>
    </div>
  );
}

export default function RunRecords({ setHeader, query }: ViewProps) {
  const runs = useResult(() => getJson("/api/runs", runListing), "/api/runs");
  const readable = runs?.ok === true ? runs.value.filter((run) => run.error === null) : [];
  const wanted = query.get("run");
  const chosen =
    readable.find((run) => `${String(run.root)}/${run.name}` === wanted) ?? readable[0];
  const configKey =
    chosen === undefined ? "none" : `/api/runs/${String(chosen.root)}/${chosen.name}/config`;
  const config = useResult(
    chosen === undefined ? null : () => getJson(configKey, runConfig),
    configKey,
  );
  useEffect(() => {
    if (config?.ok === true) {
      setHeader({
        title: "Run records",
        source: { id: `run ${config.value.runId}`, commit: config.value.harnessCommit },
        gateMode: config.value.gateMode,
      });
    }
  }, [config, setHeader]);
  if (runs === null) return <LoadingState reading="the run list" />;
  if (!runs.ok) return <ErrorState title="The run list was refused" refusal={runs.refusal} />;
  if (runs.value.length === 0 || chosen === undefined) {
    return (
      <EmptyState title="No runs under the roots yet">
        Runs appear here once a run directory exists under a root this server was started with.
        Start one with <code className="mono">physgate decompose</code> and{" "}
        <code className="mono">physgate run</code>.
      </EmptyState>
    );
  }
  return (
    <div className="run-records">
      <nav className="run-picker" aria-label="Runs">
        {runs.value.map((run) => {
          const key = `${String(run.root)}/${run.name}`;
          const on = run === chosen;
          return (
            <a
              key={key}
              className={on ? "run-link run-link-on" : "run-link"}
              aria-current={on ? "page" : undefined}
              href={hrefFor("home", "run-records", new URLSearchParams({ run: key }))}
            >
              <span className="mono">{run.runId ?? run.name}</span>
              {run.gateMode !== null && <GateModeBadge mode={run.gateMode} />}
              {run.error !== null && <span className="muted">unreadable: {run.error}</span>}
            </a>
          );
        })}
      </nav>
      {config === null ? (
        <LoadingState reading="run.json" />
      ) : config.ok ? (
        <RunView key={configKey} listing={chosen} config={config.value} />
      ) : (
        <ErrorState title="The run's configuration was refused" refusal={config.refusal} />
      )}
    </div>
  );
}
