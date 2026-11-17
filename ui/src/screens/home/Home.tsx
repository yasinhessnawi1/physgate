/**
 * Home: the runs on this machine, grouped by the brief they ran; the run still going, with its
 * subtasks, its gate tally and its cost so far; the queue items waiting for a person; the latest
 * events across the runs; and each run's system as it recorded it. Every figure is read from a
 * run's records and names its source; every count Home makes is labelled as a view.
 */
import { useEffect, useMemo, useState } from "react";

import { type QueueItem } from "../../api/queue";
import { ledgerLine, type RunListing } from "../../api/records";
import { type CostRecord, costRecord, priceDates } from "../../api/records";
import { gateCheck } from "../../api/run";
import { Button } from "../../design/components/actions/Button";
import { Figure } from "../../design/components/data/Figure";
import { Id } from "../../design/components/data/Id";
import { SourceChip } from "../../design/components/data/SourceChip";
import { type Source, sourceAttribute } from "../../design/components/data/source";
import { Term } from "../../design/components/help/Term";
import { InProgressBadge } from "../../design/components/status/InProgressBadge";
import { RunPhaseBadge } from "../../design/components/status/RunPhaseBadge";
import { Detail } from "../../design/components/status/RunStanding";
import { EmptyState, ErrorState, LoadingState } from "../../design/components/status/States";
import { OsLayerBadge } from "../../design/components/system/OsLayerBadge";
import { GateModeBadge } from "../../design/components/verdict/GateMode";
import { Tally } from "../../design/components/verdict/Tally";
import { tallyOfChecks } from "../../design/tally";
import type { ViewProps } from "../../shell/header";
import { hrefFor } from "../../shell/route";
import { SOURCE_WORDS } from "../../words/queue";
import { clockTime, type RunLabel, utc } from "../../words/runs";
import { CostCaveat } from "../common/cost";
import { EngineWords } from "../common/engine";
import { useJson, useLines } from "../common/read";
import { RowView } from "../common/RowView";
import { type Row, rowsOf } from "../common/rows";
import { runBase, runKey, runSource, useLabels, useRunList } from "../common/runs";
import { phaseOf, standingOf } from "../../words/standing";
import { NoRunsYet } from "./NoRunsYet";
import { type RunEnd, runEnd, waitingFor } from "./runEnd";
import {
  activeRun,
  homeOrder,
  phasesOf,
  readTargets,
  type RunRead,
  type Stale,
  startOfRead,
  useRunReads,
  useOrderPhases,
  useSettled,
  useStatuses,
} from "./data";
import {
  STRIP_STATES,
  STRIP_WORDS,
  type StripCell,
  type StripState,
  strip,
  stripCounts,
} from "./strip";

/** How many recent events Home lists, across the runs read. */
const RECENT = 8;

/**
 * The strip's legend: each state with its count as "k of n", a view over the ledger. Never a
 * percentage: the counts are small, and a share of five subtasks would say more than they do.
 */
export function StripLegend({
  cells,
  counts,
}: {
  readonly cells: readonly StripCell[];
  readonly counts: Readonly<Record<StripState, number>>;
}) {
  return (
    <ul className="pg-strip-legend" aria-label="View: subtasks by state, counted from the ledger">
      {STRIP_STATES.filter((s) => s !== "tried" || counts.tried > 0).map((s) => (
        <li key={s}>
          <span className={`pg-strip-key pg-strip-${s}`} aria-hidden="true" />
          {STRIP_WORDS[s]}{" "}
          <span className="pg-count">
            {counts[s]} of {cells.length}
          </span>
        </li>
      ))}
    </ul>
  );
}

/**
 * The run's cost so far at the newest price sheet: the figure, which sheet, and, where the server
 * could not price every call, that the figure is a lower bound and by how many calls.
 */
export function CostSoFar({
  cost,
  source,
}: {
  readonly cost: CostRecord;
  readonly source: Source;
}) {
  return (
    <span className="pg-figure-line">
      <Figure {...cost.usd} decimals={2} source={source} partial atLeast={cost.lowerBound} />
      <span className="pg-panel-note">
        price sheet of {cost.pricesDate}
        <CostCaveat cost={cost} />
      </span>
    </span>
  );
}

function runHref(slug: string, run: RunListing, area: "orchestration" | "home" = "orchestration") {
  return hrefFor(area, slug, new URLSearchParams({ run: runKey(run) }));
}

function RunName({
  label,
  fallback,
}: {
  readonly label: RunLabel | undefined;
  readonly fallback: string;
}) {
  return (
    <span className="pg-run-name" title={label?.detail}>
      {label?.label ?? fallback}
    </span>
  );
}

/** A status kept from an earlier read: since when it is not refreshed, and why. */
function StaleWords({ stale }: { readonly stale: Stale | undefined }) {
  if (stale === undefined) return null;
  return (
    <span className="pg-run-stale pg-muted">
      Not refreshed since <time title={utc(stale.since)}>{clockTime(stale.since)}</time>:{" "}
      {stale.error}
    </span>
  );
}

export function statusWords(read: RunRead | undefined, stale?: Stale) {
  if (read === undefined) return <span className="pg-muted">Reading…</span>;
  if (!read.status.ok)
    return (
      <span className="pg-muted">Where it stands was not read: {read.status.refusal.error}</span>
    );
  const status = read.status.value;
  const phase = phaseOf(status);
  if (phase === "going")
    return stale === undefined ? (
      <InProgressBadge />
    ) : (
      <div className="pg-run-standing">
        <InProgressBadge /> <StaleWords stale={stale} />
      </div>
    );
  let end: RunEnd | null = null;
  if (phase === "done") {
    // A log that could not be read cannot show a run complete: it is not claimed.
    if (!read.events.ok) return <span className="pg-status">Ended · its log was not read</span>;
    const open = waitingFor(read.queue.ok ? read.queue.value.open : null, status.superseded);
    end = runEnd(read.events.value, open, status.completion);
  }
  const standing = standingOf(status, end);
  return (
    <div className="pg-run-standing">
      <RunPhaseBadge
        phase={standing.phase}
        {...(standing.word === null ? {} : { word: standing.word })}
      />{" "}
      <span className="pg-standing-sentence">{standing.sentence}</span>
      <Detail text={standing.detail} />
      <StaleWords stale={stale} />
    </div>
  );
}

/** Home's order of the runs, in the panel's words and as its table is named. */
const ORDER_NOTE =
  "View: going, then waiting on a person, then halted or stopped, then newest first";
const ORDER_LABEL = "Runs, going, waiting on a person, halted or stopped first, then newest first";

/** No run read in full yet. */
const NO_TARGETS: readonly RunListing[] = [];

export function Runs({
  runs,
  reads,
  labels,
  stale,
}: {
  readonly runs: readonly RunListing[];
  readonly reads: ReadonlyMap<string, RunRead>;
  readonly labels: ReadonlyMap<string, RunLabel>;
  /** The runs whose status is kept from an earlier read, by run key. */
  readonly stale?: ReadonlyMap<string, Stale>;
}) {
  // One list in Home's order (``homeOrder``): runs going, then runs waiting on a person, then runs
  // halted or stopped, then the rest, newest start first within each. Grouped by brief, dates would jump.
  // A run whose records are still read is listed at once, its standing "Reading…".
  const listed: { run: RunListing; read: RunRead | undefined }[] = [];
  const unread: RunListing[] = [];
  for (const run of runs) {
    const read = reads.get(runKey(run));
    if (run.error !== null || (read !== undefined && !read.config.ok)) unread.push(run);
    else listed.push({ run, read });
  }
  return (
    <section className="pg-card pg-panel" aria-label="Runs">
      <header className="pg-panel-head">
        <h2 className="pg-panel-title">Runs</h2>
        <span className="pg-panel-note">{ORDER_NOTE}</span>
      </header>
      <div className="pg-table-wrap" role="region" aria-label={ORDER_LABEL} tabIndex={0}>
        <table className="pg-table pg-runs-table" aria-label={ORDER_LABEL}>
          <thead>
            <tr>
              <th scope="col">Run</th>
              <th scope="col">Where it stands</th>
              <th scope="col">Gate mode</th>
              <th scope="col">
                <Term term="os-layer">OS layer</Term>
              </th>
              <th scope="col">Brief</th>
            </tr>
          </thead>
          <tbody>
            {listed.map(({ run, read }) => (
              <tr key={runKey(run)}>
                <td>
                  <a className="pg-run-row-link pg-hit" href={runHref("run-timeline", run)}>
                    <RunName label={labels.get(runKey(run))} fallback={`Run ${run.name}`} />
                  </a>
                </td>
                <td>{statusWords(read, stale?.get(runKey(run)))}</td>
                <td>{run.gateMode !== null && <GateModeBadge mode={run.gateMode} />}</td>
                <td>
                  <OsLayerBadge layer={run.osLayer} />
                </td>
                <td className="pg-runs-brief">
                  {read?.config.ok === true && (
                    <span title="The digest of the brief the run read: runs of one brief share it">
                      <Id value={read.config.value.briefSha256.slice(0, 8)} copy={false} />
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {unread.length > 0 && (
        <ul className="pg-run-rows">
          {unread.map((run) => {
            const read = reads.get(runKey(run));
            return (
              <li key={runKey(run)} className="pg-run-row">
                {run.error !== null ? (
                  <span className="pg-run-unread">
                    Run {run.name} could not be read: {run.error}
                  </span>
                ) : (
                  read !== undefined &&
                  !read.config.ok && (
                    <span className="pg-run-unread">
                      Run {run.name}: its configuration could not be read:{" "}
                      {read.config.refusal.error}
                    </span>
                  )
                )}
                <Id value={run.name} copy={false} />
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function ActiveRun({
  read,
  label,
}: {
  readonly read: RunRead;
  readonly label: RunLabel | undefined;
}) {
  const base = runBase(read.run);
  const ledger = useLines(`${base}/ledger`, ledgerLine);
  const checks = useLines(`${base}/gate-checks`, gateCheck);
  const prices = useJson("/api/prices", priceDates);
  const newest = prices.result?.ok === true ? prices.result.value.at(-1) : undefined;
  const cost = useJson(newest === undefined ? null : `${base}/cost/${newest}`, costRecord);
  if (!read.config.ok || !read.status.ok || !read.events.ok) return null;
  const config = read.config.value;
  const events = read.events.value;
  const status = read.status.value;
  const source = runSource(config);
  const implementers = [...new Set(Object.values(config.roleModels))];
  const reviewers = [...new Set(Object.values(config.reviewerModels))];
  return (
    <section
      className="pg-card pg-panel"
      aria-label="The run still going"
      data-source={sourceAttribute(source)}
    >
      <header className="pg-panel-head">
        <h2 className="pg-panel-title">
          <span className="pg-panel-over">Still going</span>{" "}
          <RunName label={label} fallback={`Run ${read.run.name}`} />
        </h2>
        <GateModeBadge mode={config.gateMode} />
        <InProgressBadge />
        <a className="pg-btn pg-btn-browse pg-btn-sm" href={runHref("run-timeline", read.run)}>
          Open the timeline
        </a>
      </header>
      {ledger.result === null ? (
        <LoadingState reading="the task ledger" rows={1} />
      ) : !ledger.result.ok ? (
        <ErrorState
          title="The subtasks could not be read"
          {...ledger.result.refusal}
          route={ledger.route}
          onRetry={ledger.again}
        />
      ) : (
        (() => {
          const cells = strip(ledger.result.value, events, status);
          const counts = stripCounts(cells);
          return (
            <div className="pg-strip-block">
              <ol className="pg-strip" aria-label="Subtasks, in the order planned">
                {cells.map((cell, i) => (
                  <li
                    key={cell.subtask}
                    className={`pg-strip-cell pg-strip-${cell.state}`}
                    title={`Subtask ${String(i + 1)} (${cell.subtask}): ${STRIP_WORDS[cell.state]}`}
                  >
                    <span className="pg-visually-hidden">
                      Subtask {i + 1}: {STRIP_WORDS[cell.state]}
                    </span>
                  </li>
                ))}
              </ol>
              <StripLegend cells={cells} counts={counts} />
            </div>
          );
        })()
      )}
      <div className="pg-active-figures">
        <div className="pg-active-figure">
          <span className="pg-label">
            <Term term="gate">Gate</Term> checks so far
          </span>
          {checks.result === null ? (
            <LoadingState reading="the gate checks" rows={1} />
          ) : !checks.result.ok ? (
            <ErrorState
              title="The gate checks could not be read"
              {...checks.result.refusal}
              route={checks.route}
              onRetry={checks.again}
            />
          ) : config.gateMode === "off" ? (
            <span className="pg-muted">The gate is off in this run: nothing was checked.</span>
          ) : (
            <Tally
              {...tallyOfChecks(checks.result.value)}
              observed={config.gateMode === "observe"}
              partial
              compact
            />
          )}
        </div>
        <div className="pg-active-figure">
          <span className="pg-label">
            Cost so far · <Term term="list-price">List-price estimate</Term>
          </span>
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
            <CostSoFar cost={cost.result.value} source={source} />
          )}
        </div>
        <div className="pg-active-figure">
          <span className="pg-label">Builder model</span>
          <span className="mono">{implementers.join(", ") || "not recorded"}</span>
        </div>
        <div className="pg-active-figure">
          <span className="pg-label">Reviewer model</span>
          <span className="mono">{reviewers.join(", ") || "not recorded"}</span>
        </div>
      </div>
      <SourceChip {...source} />
    </section>
  );
}

function NeedsYou({
  reads,
  labels,
}: {
  readonly reads: readonly RunRead[];
  readonly labels: ReadonlyMap<string, RunLabel>;
}) {
  const open: { read: RunRead; item: QueueItem }[] = reads.flatMap((read) =>
    read.queue.ok ? read.queue.value.open.map((item) => ({ read, item })) : [],
  );
  const refused = reads.filter((read) => !read.queue.ok);
  return (
    <section className="pg-card pg-panel" aria-label="Needs you">
      <header className="pg-panel-head">
        <h2 className="pg-panel-title">Needs you</h2>
        <span className="pg-panel-note">
          View: <span className="pg-count">{open.length}</span> open{" "}
          <Term term="queue-item">{open.length === 1 ? "queue item" : "queue items"}</Term>
        </span>
      </header>
      {open.length === 0 && refused.length === 0 ? (
        <p className="pg-panel-empty">No queue item is waiting in the runs read.</p>
      ) : (
        <ul className="pg-needs">
          {open.map(({ read, item }) => (
            <li key={`${runKey(read.run)}/${item.itemId}`} className="pg-need">
              <a
                className="pg-need-link pg-hit"
                href={hrefFor(
                  "collaboration",
                  "approval-queue",
                  new URLSearchParams({ run: runKey(read.run), item: item.itemId }),
                )}
              >
                <span className="pg-need-why">{SOURCE_WORDS[item.source].why}</span>
                <span className="pg-need-meta">
                  <RunName label={labels.get(runKey(read.run))} fallback={`Run ${read.run.name}`} />
                  {" · "}
                  {SOURCE_WORDS[item.source].kind}
                </span>
              </a>
              <Id value={item.itemId} copy={false} />
            </li>
          ))}
          {refused.map((read) =>
            read.queue.ok ? null : (
              <li key={runKey(read.run)} className="pg-need">
                <ErrorState
                  title={`The queue of run ${read.run.name} could not be read`}
                  {...read.queue.refusal}
                />
              </li>
            ),
          )}
        </ul>
      )}
    </section>
  );
}

function RecentActivity({ reads }: { readonly reads: readonly RunRead[] }) {
  const rows: { read: RunRead; row: Row }[] = reads
    .flatMap((read) =>
      read.events.ok && read.config.ok
        ? rowsOf(
            read.events.value,
            read.config.value,
            undefined,
            read.status.ok && phaseOf(read.status.value) === "going",
          ).map((row) => ({ read, row }))
        : [],
    )
    .sort((a, b) => b.row.ts.localeCompare(a.row.ts) || b.row.seq - a.row.seq)
    .slice(0, RECENT);
  return (
    <section className="pg-card pg-panel" aria-label="Recent activity">
      <header className="pg-panel-head">
        <h2 className="pg-panel-title">Recent activity</h2>
        <span className="pg-panel-note">View: the latest {RECENT} events across the runs read</span>
      </header>
      {rows.length === 0 ? (
        <p className="pg-panel-empty">No event is recorded in the runs read.</p>
      ) : (
        <div className="pg-rows">
          {rows.map(({ read, row }) => (
            <div
              key={`${runKey(read.run)}/${row.key}`}
              data-source={
                read.config.ok ? sourceAttribute(runSource(read.config.value)) : undefined
              }
            >
              <RowView row={{ ...row, depth: 0 }} />
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function SystemPanel({
  reads,
  labels,
}: {
  readonly reads: readonly RunRead[];
  readonly labels: ReadonlyMap<string, RunLabel>;
}) {
  const readable = reads.filter((r) => r.config.ok);
  return (
    <section className="pg-card pg-panel" aria-label="System">
      <header className="pg-panel-head">
        <h2 className="pg-panel-title">System, as each run recorded it</h2>
      </header>
      <div className="pg-table-wrap" role="region" aria-label="System, per run" tabIndex={0}>
        <table className="pg-table" aria-label="System, per run">
          <thead>
            <tr>
              <th scope="col">Run</th>
              <th scope="col">Gate mode</th>
              <th scope="col">Engine · auth</th>
              <th scope="col">Builder models</th>
              <th scope="col">Reviewer models</th>
              <th scope="col">
                <Term term="os-layer">OS layer</Term>
              </th>
            </tr>
          </thead>
          <tbody>
            {readable.map((read) =>
              read.config.ok ? (
                <tr key={runKey(read.run)}>
                  <td>
                    <RunName
                      label={labels.get(runKey(read.run))}
                      fallback={`Run ${read.run.name}`}
                    />
                  </td>
                  <td>
                    <GateModeBadge mode={read.config.value.gateMode} />
                  </td>
                  <td>
                    <EngineWords auth={read.config.value.auth} />
                  </td>
                  <td className="mono">
                    {[...new Set(Object.values(read.config.value.roleModels))].join(", ") ||
                      "not recorded"}
                  </td>
                  <td className="mono">
                    {[...new Set(Object.values(read.config.value.reviewerModels))].join(", ") ||
                      "not recorded"}
                  </td>
                  <td>
                    <OsLayerBadge layer={read.run.osLayer} />
                  </td>
                </tr>
              ) : null,
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/**
 * What this page is, said first, for a person who has not seen it before: what a run is, what
 * stands between an agent's work and the design, and what Home lists.
 */
export function HomeIntro() {
  return (
    <div className="pg-home-intro">
      <p>
        This is the operator's view of the design runs on this machine. In a run, AI agents design a
        mechatronic system from a brief: the work is split into subtasks, an agent does each, a
        physics gate checks the design's numbers (their units, ranges and balances) before a
        reviewer reads the work, and anything the run cannot settle comes to a person.
      </p>
      <p>
        Home lists the runs, the questions a run has left for a person to decide, and the latest
        activity. Open a run for its timeline, its design and its gate checks.
      </p>
    </div>
  );
}

export default function Home({ setHeader }: ViewProps) {
  const runs = useRunList();
  const [all, setAll] = useState(false);
  const listed = useMemo(() => (runs?.ok === true ? runs.value : []), [runs]);
  const readable = useMemo(() => listed.filter((r) => r.error === null), [listed]);
  // Where every readable run stands, first: Home's order needs it, and it is small.
  const { found: statuses, stale, minutes } = useStatuses(readable);
  // The runs are listed at once; their records are read once the statuses have answered, or
  // after a short wait, so a run going is among those read and no slow status holds Home up.
  const settled = useSettled(readable, statuses);
  const answered = useMemo(() => phasesOf(readable, statuses), [readable, statuses]);
  // The order is settled once and moved only when a minute's re-read ends, so a row does not
  // move under a person's pointer as the statuses answer.
  const phases = useOrderPhases(answered, settled, minutes);
  const targets = readTargets(listed, all, phases);
  const reads = useRunReads(settled ? targets : NO_TARGETS, statuses);
  const starts = useMemo(
    () => new Map([...reads].map(([k, read]) => [k, startOfRead(read)] as const)),
    [reads],
  );
  const labels = useLabels(listed, starts);
  const read = targets.flatMap((run) => {
    const found = reads.get(runKey(run));
    return found === undefined ? [] : [found];
  });
  const active = activeRun(read);
  const activeLabel = active === undefined ? undefined : labels.get(runKey(active.run));
  const activeConfig = active?.config.ok === true ? active.config.value : undefined;
  useEffect(() => {
    if (runs?.ok === true && runs.value.length === 0)
      setHeader({ title: "Home", runState: "none" });
    else if (runs?.ok === false) setHeader({ title: "Home", runState: "unread" });
    else if (activeConfig !== undefined)
      setHeader({
        title: "Home",
        source: runSource(activeConfig),
        gateMode: activeConfig.gateMode,
        inProgress: true,
        ...(activeLabel === undefined ? {} : { run: activeLabel }),
      });
    else setHeader({ title: "Home" });
  }, [runs, activeConfig, activeLabel, setHeader]);

  if (runs === null) return <LoadingState reading="the run list" />;
  if (!runs.ok)
    return (
      <ErrorState title="The run list could not be read" {...runs.refusal} route="/api/runs" />
    );
  if (runs.value.length === 0) return <NoRunsYet />;
  const pending = targets.length - read.length;
  const ordered = homeOrder(listed, phases);
  return (
    <div className="pg-screen pg-home">
      <HomeIntro />
      <header className="pg-screen-head">
        <p className="pg-screen-lead">
          {readable.length === 0
            ? "No run here can be read; each says why below."
            : active === undefined
              ? "No run is going now."
              : "One run is still going; its figures are partial and read so far."}
        </p>
      </header>
      {readable.length === 0 && (
        <EmptyState title="No run here can be read">
          Each run listed below says why it could not be read.
        </EmptyState>
      )}
      {pending > 0 && <LoadingState reading="the runs' records" rows={1} />}
      {active !== undefined && <ActiveRun read={active} label={activeLabel} />}
      {readable.length > 0 && (
        <div className="pg-home-grid">
          <NeedsYou reads={read} labels={labels} />
          <RecentActivity reads={read} />
        </div>
      )}
      <Runs
        runs={all ? ordered : ordered.filter((r) => r.error !== null || targets.includes(r))}
        reads={reads}
        labels={labels}
        stale={stale}
      />
      {readable.length > targets.length && (
        <Button
          onClick={() => {
            setAll(true);
          }}
        >
          Show all runs
        </Button>
      )}
      {read.length > 0 && <SystemPanel reads={read} labels={labels} />}
    </div>
  );
}
