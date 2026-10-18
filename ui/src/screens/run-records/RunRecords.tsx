/**
 * Everything one run wrote, read end to end: its configuration and manifest, what it cost at a
 * chosen price sheet and what it spent by attribution, its task ledger, its sealed transcripts
 * with their seals, the gate's records, and the decision sequence. A record the server refuses
 * is shown as the refusal, with its reason, and nothing of it is shown partial.
 */
import { useEffect, useState } from "react";

import { getLines } from "../../api/client";
import { runEvent } from "../../api/events";
import {
  costRecord,
  gateEventLine,
  ledgerLine,
  type LedgerLine,
  priceDates,
  type RunConfig,
} from "../../api/records";
import { decisions as decisionSequence, tokens as tokenAccount } from "../../api/run";
import { Button } from "../../design/components/actions/Button";
import { Figure } from "../../design/components/data/Figure";
import { Id } from "../../design/components/data/Id";
import { Quantity } from "../../design/components/data/Quantity";
import { SourceChip } from "../../design/components/data/SourceChip";
import { sourceAttribute } from "../../design/components/data/source";
import { Term } from "../../design/components/help/Term";
import { EmptyState, ErrorState, LoadingState } from "../../design/components/status/States";
import { StatusTag } from "../../design/components/status/StatusTag";
import { OsLayerBadge } from "../../design/components/system/OsLayerBadge";
import { GateModeBadge, GateOutcome } from "../../design/components/verdict/GateMode";
import { VerdictBadge } from "../../design/components/verdict/VerdictBadge";
import type { ViewProps } from "../../shell/header";
import { checkWords } from "../../words/checks";
import { nodeLabel } from "../../words/humanise";
import type { RunLabel } from "../../words/runs";
import { CostCaveat } from "../common/cost";
import { useJson, useLines } from "../common/read";
import { subtaskNames } from "../common/rows";
import { RunSwitcher } from "../common/RunSwitcher";
import { inProgress, runSource, useChosenRun } from "../common/runs";
import { useResult } from "../common/useResult";
import { latestLines } from "../home/strip";
import { TokensCard } from "./Cards";

const AREA = "home";
const SLUG = "run-records";
/** How many transcripts are read and checked against their seal without being asked. */
const FIRST_SEALS = 5;

function ledgerGate(mode: RunConfig["gateMode"], result: LedgerLine["gate"]) {
  if (result === null) return <span className="pg-muted">not run</span>;
  if (result === "skipped") return <span className="pg-muted">skipped · gate off</span>;
  return <GateOutcome mode={mode} outcome={result} />;
}

function ledgerReview(result: LedgerLine["review"]) {
  if (result === null) return <span className="pg-muted">not run</span>;
  if (result === "skipped") return <span className="pg-muted">skipped</span>;
  return <VerdictBadge verdict={result} />;
}

function Seal({
  base,
  session,
  auto,
}: {
  readonly base: string;
  readonly session: string;
  readonly auto: boolean;
}) {
  const [asked, setAsked] = useState(auto);
  const read = useResult(
    asked ? () => getLines(`${base}/trajectories/${encodeURIComponent(session)}`, (v) => v) : null,
    `${base}/trajectories/${session}`,
  );
  if (!asked)
    return (
      <Button
        size="sm"
        onClick={() => {
          setAsked(true);
        }}
      >
        Check this seal
      </Button>
    );
  if (read === null) return <span className="pg-muted">Checking the seal…</span>;
  if (read.ok)
    return (
      <span className="pg-figure-line">
        <StatusTag status="seal-holds" />
        <span className="pg-panel-note">read whole; it matched its seal</span>
      </span>
    );
  return (
    <span className="pg-figure-line">
      <StatusTag status="seal-tampered" />
      <span className="pg-panel-note">refused: {read.refusal.error}</span>
    </span>
  );
}

function Records({
  base,
  config,
  label,
  going,
  query,
}: {
  readonly base: string;
  readonly config: RunConfig;
  readonly label: RunLabel | undefined;
  readonly going: boolean;
  readonly query: URLSearchParams;
}) {
  const source = runSource(config);
  const ledger = useLines(`${base}/ledger`, ledgerLine);
  const gates = useLines(`${base}/gate-events`, gateEventLine);
  const events = useLines(`${base}/events`, runEvent);
  const tokens = useJson(`${base}/tokens`, tokenAccount);
  const sequence = useJson(`${base}/decisions`, decisionSequence);
  const prices = useJson("/api/prices", priceDates);
  const dates = prices.result?.ok === true ? prices.result.value : [];
  const [sheet, setSheet] = useState<string | null>(query.get("prices"));
  const chosenSheet = sheet !== null && dates.includes(sheet) ? sheet : dates.at(-1);
  const cost = useJson(
    chosenSheet === undefined ? null : `${base}/cost/${chosenSheet}`,
    costRecord,
  );
  const names =
    events.result?.ok === true ? subtaskNames(events.result.value) : new Map<string, string>();
  const escalated = new Set(
    events.result?.ok === true
      ? events.result.value.flatMap((e) => (e.kind === "escalated" ? [e.subtask] : []))
      : [],
  );
  const sealed =
    events.result?.ok === true
      ? events.result.value.flatMap((e) => (e.kind === "session_ended" && e.sealed ? [e] : []))
      : [];
  return (
    <div className="pg-records" data-source={sourceAttribute(source)}>
      <section className="pg-card pg-panel" aria-label="Configuration">
        <h2 className="pg-panel-title">Configuration</h2>
        <dl className="pg-facts">
          <dt>Run</dt>
          <dd>
            {label?.label ?? `Run ${config.runId}`} <Id value={config.runId} />
          </dd>
          <dt>Gate mode</dt>
          <dd>
            <GateModeBadge mode={config.gateMode} />
          </dd>
          <dt>
            <Term term="manifest">Manifest</Term>
          </dt>
          <dd>
            <Id value={config.manifestId} />
          </dd>
          <dt>Harness commit</dt>
          <dd>
            {config.harnessCommit === null ? (
              <span className="pg-muted">no commit recorded</span>
            ) : (
              <Id value={config.harnessCommit} />
            )}
          </dd>
          <dt>Engine</dt>
          <dd>
            Claude Code · <span className="mono">{config.auth}</span>
          </dd>
          <dt>Builder models</dt>
          <dd className="mono">
            {Object.entries(config.roleModels)
              .map(([role, model]) => `${role}: ${model}`)
              .join(", ") || "not recorded"}
          </dd>
          <dt>Reviewer models</dt>
          <dd className="mono">
            {Object.entries(config.reviewerModels)
              .map(([role, model]) => `${role}: ${model}`)
              .join(", ") || "not recorded"}
          </dd>
          <dt>
            Brief <Term term="digest">digest</Term>
          </dt>
          <dd>
            <Id value={config.briefSha256} />
          </dd>
          <dt>
            <Term term="seed">Seed</Term>
          </dt>
          <dd>
            <Id value={String(config.seed)} copy={false} />
          </dd>
          <dt>
            <Term term="os-layer">OS layer</Term>
          </dt>
          <dd>
            <OsLayerBadge layer={config.osLayer} />
          </dd>
        </dl>
        <SourceChip {...source} />
      </section>

      <section className="pg-card pg-panel" aria-label="Cost">
        <header className="pg-panel-head">
          <h2 className="pg-panel-title">Cost{going ? " so far" : ""}</h2>
          {dates.length > 1 && (
            <span className="pg-field">
              <label className="pg-visually-hidden" htmlFor="price-sheet">
                Price sheet
              </label>
              <select
                id="price-sheet"
                value={chosenSheet}
                onChange={(e) => {
                  setSheet(e.target.value);
                }}
              >
                {dates.map((d) => (
                  <option key={d} value={d}>
                    Price sheet of {d}
                  </option>
                ))}
              </select>
            </span>
          )}
        </header>
        {cost.result === null ? (
          <LoadingState reading="the cost" rows={1} />
        ) : !cost.result.ok ? (
          <ErrorState
            title="The cost could not be read"
            {...cost.result.refusal}
            route={cost.route}
            onRetry={cost.again}
          />
        ) : (
          <>
            <p className="pg-panel-note">
              A <Term term="list-price">list-price estimate</Term>, at the price sheet of{" "}
              {cost.result.value.pricesDate}
              {going || cost.result.value.partial ? "; partial: the figures can still change" : ""}.
              <CostCaveat cost={cost.result.value} />
            </p>
            <div className="pg-figure-line">
              <Figure
                {...cost.result.value.usd}
                source={source}
                size="lg"
                partial={going || cost.result.value.partial}
              />
              <Figure
                {...cost.result.value.nok}
                source={source}
                size="lg"
                partial={going || cost.result.value.partial}
              />
            </div>
          </>
        )}
      </section>

      {tokens.result === null ? (
        <LoadingState reading="the token account" />
      ) : !tokens.result.ok ? (
        <ErrorState
          title="The token account could not be read"
          {...tokens.result.refusal}
          route={tokens.route}
          onRetry={tokens.again}
        />
      ) : (
        <TokensCard
          tokens={tokens.result.value}
          cost={cost.result?.ok === true ? cost.result.value : null}
          source={source}
        />
      )}

      <section className="pg-card pg-panel" aria-label="Task ledger">
        <h2 className="pg-panel-title">Task ledger</h2>
        {ledger.result === null ? (
          <LoadingState reading="the task ledger" />
        ) : !ledger.result.ok ? (
          <ErrorState
            title="The task ledger could not be read. Nothing of it is shown."
            {...ledger.result.refusal}
            route={ledger.route}
            onRetry={ledger.again}
          />
        ) : ledger.result.value.length === 0 ? (
          <EmptyState title="No ledger lines yet">The run has dispatched nothing.</EmptyState>
        ) : (
          <>
            <p className="pg-panel-note">
              View: each subtask's latest line of {ledger.result.value.length} ledger lines.
            </p>
            <div
              className="pg-table-wrap"
              role="region"
              aria-label="Task ledger table"
              tabIndex={0}
            >
              <table className="pg-table" aria-label="Task ledger">
                <thead>
                  <tr>
                    <th scope="col">Subtask</th>
                    <th scope="col">Role</th>
                    <th scope="col">Attempts</th>
                    <th scope="col">Gate</th>
                    <th scope="col">Review</th>
                    <th scope="col">Where it stands</th>
                  </tr>
                </thead>
                <tbody>
                  {latestLines(ledger.result.value).map((line) => (
                    <tr key={line.id}>
                      <td>
                        {names.get(line.id) ?? "Subtask"} <Id value={line.id} copy={false} />
                      </td>
                      <td>{line.role}</td>
                      <td className="pg-count">{line.attempts}</td>
                      <td>{ledgerGate(config.gateMode, line.gate)}</td>
                      <td>{ledgerReview(line.review)}</td>
                      <td>
                        {line.mergeCommit !== null ? (
                          <>
                            merged <Id value={line.mergeCommit.slice(0, 7)} copy={false} />
                          </>
                        ) : escalated.has(line.id) ? (
                          "set aside for a person to decide"
                        ) : (
                          <span className="pg-muted">not merged</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
        <SourceChip {...source} />
      </section>

      <section className="pg-card pg-panel" aria-label="Trajectories">
        <h2 className="pg-panel-title">
          <Term term="sealed">Sealed</Term> transcripts
        </h2>
        {events.result === null ? (
          <LoadingState reading="the event log" />
        ) : !events.result.ok ? (
          <ErrorState
            title="The event log could not be read"
            {...events.result.refusal}
            route={events.route}
            onRetry={events.again}
          />
        ) : sealed.length === 0 ? (
          <EmptyState title="No sealed transcript">
            No session of this run ended with a captured stream.
          </EmptyState>
        ) : (
          <ul className="pg-list">
            {sealed.map((s, i) => (
              <li key={s.sessionId} className="pg-list-row">
                <span className="pg-list-row-main">
                  <span>
                    {names.get(s.subtask) ?? "Subtask"}, attempt {s.attempt}
                  </span>
                  <Id value={s.sessionId} />
                </span>
                <Seal base={base} session={s.sessionId} auto={i < FIRST_SEALS} />
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="pg-card pg-panel" aria-label="Gate records">
        <h2 className="pg-panel-title">The gate's records</h2>
        {gates.result === null ? (
          <LoadingState reading="the gate's records" />
        ) : !gates.result.ok ? (
          <ErrorState
            title="The gate's records could not be read"
            {...gates.result.refusal}
            route={gates.route}
            onRetry={gates.again}
          />
        ) : gates.result.value.length === 0 ? (
          <EmptyState title="No gate records">The gate has not run in this run.</EmptyState>
        ) : (
          <details className="pg-details" open>
            <summary>{gates.result.value.length} records, as the gate wrote them</summary>
            <div
              className="pg-table-wrap"
              role="region"
              aria-label="Gate records table"
              tabIndex={0}
            >
              <table className="pg-table" aria-label="Gate records">
                <thead>
                  <tr>
                    <th scope="col">Check</th>
                    <th scope="col">Outcome</th>
                    <th scope="col">Value</th>
                    <th scope="col">Reviewer approved before the gate?</th>
                  </tr>
                </thead>
                <tbody>
                  {gates.result.value.map((g, i) => (
                    <tr key={String(i)}>
                      <td>
                        {checkWords(g.check).name}
                        {g.node === null ? "" : ` · ${nodeLabel(g.node)}`}{" "}
                        <Id value={`seq ${String(g.seq)}`} copy={false} />
                      </td>
                      <td>
                        <GateOutcome mode={g.mode} outcome={g.outcome} />
                      </td>
                      <td>
                        {g.value === null ? (
                          <span className="pg-muted">none recorded</span>
                        ) : (
                          <Quantity {...g.value} />
                        )}
                      </td>
                      <td>
                        {g.reviewerHadPassed === null
                          ? "not reviewed"
                          : g.reviewerHadPassed
                            ? "yes"
                            : "no"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        )}
      </section>

      <section className="pg-card pg-panel" aria-label="Decision sequence">
        <h2 className="pg-panel-title">The run's decision sequence</h2>
        {sequence.result === null ? (
          <LoadingState reading="the decision sequence" />
        ) : !sequence.result.ok ? (
          <ErrorState
            title="The decision sequence could not be read"
            {...sequence.result.refusal}
            route={sequence.route}
            onRetry={sequence.again}
          />
        ) : (
          <details className="pg-details">
            <summary>{sequence.result.value.length} steps, in the order the run took them</summary>
            <ol className="pg-list">
              {sequence.result.value.map((d) => (
                <li key={d.seq} className="pg-list-row">
                  <span className="pg-list-row-main">
                    <span>
                      {d.step}
                      {d.subtask === null ? "" : ` · ${names.get(d.subtask) ?? d.subtask}`}
                      {d.attempt === null ? "" : ` · attempt ${String(d.attempt)}`}
                      {d.verdict === null ? "" : ` · ${d.verdict}`}
                      {d.reason === null ? "" : ` · ${d.reason}`}
                    </span>
                    <Id value={`seq ${String(d.seq)}`} copy={false} />
                  </span>
                </li>
              ))}
            </ol>
          </details>
        )}
      </section>
    </div>
  );
}

export default function RunRecords({ setHeader, query }: ViewProps) {
  const chosen = useChosenRun(query);
  const { runs, config, status, base, label } = chosen;
  const configValue = config?.ok === true ? config.value : undefined;
  const going = status?.ok === true && inProgress(status.value);
  useEffect(() => {
    if (runs?.ok === true && runs.value.length === 0)
      setHeader({ title: "Run records", runState: "none" });
    else if (config?.ok === false || runs?.ok === false)
      setHeader({ title: "Run records", runState: "unread" });
    else if (configValue !== undefined)
      setHeader({
        title: "Run records",
        source: runSource(configValue),
        gateMode: configValue.gateMode,
        osLayer: configValue.osLayer,
        inProgress: going,
        ...(label === undefined ? {} : { run: label }),
      });
  }, [runs, config, configValue, going, label, setHeader]);
  if (runs === null) return <LoadingState reading="the run list" />;
  if (!runs.ok)
    return (
      <ErrorState title="The run list could not be read" {...runs.refusal} route="/api/runs" />
    );
  if (chosen.chosen === undefined || base === null)
    return (
      <EmptyState title="No run to show yet">
        A run's records appear here once a run is recorded on this machine.
      </EmptyState>
    );
  return (
    <div className="pg-screen">
      <RunSwitcher
        runs={runs.value}
        chosen={chosen.chosen}
        labels={chosen.labels}
        area={AREA}
        slug={SLUG}
        allShown={chosen.allShown}
        showAll={chosen.showAll}
      />
      {config === null ? (
        <LoadingState reading="the run's configuration" />
      ) : !config.ok ? (
        <ErrorState
          title="The run's configuration could not be read"
          {...config.refusal}
          onRetry={chosen.again}
        />
      ) : (
        <Records
          key={base}
          base={base}
          config={config.value}
          label={label}
          going={going}
          query={query}
        />
      )}
    </div>
  );
}
