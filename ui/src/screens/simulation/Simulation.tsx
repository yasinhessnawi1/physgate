/**
 * Simulation: what a run's simulations recorded, each record as its session sealed it.
 *
 * The rail lists the run's subtasks and attempts from the run's listing, which the server reads
 * from the event log alone; an attempt's records are read when it is opened, and one record's
 * samples when that record is. Each record is drawn as plots of its sealed columns with the
 * server's summary as text and every row as a table; below them, what was read off each record
 * and what the gate's own records say about those quantities. A slot for 3D and multi-domain
 * tool views is registered and empty.
 *
 * Nothing here is a what-if, and nothing writes.
 */
import "./simulation.css";

import { useEffect, useState } from "react";

import { runEvent } from "../../api/events";
import {
  type AttemptRecord,
  attemptRecords,
  attemptRoute,
  type ListedAttempt,
  type SeriesListing,
  seriesListing,
  seriesRoute,
} from "../../api/series";
import type { RunConfig } from "../../api/records";
import { Segmented } from "../../design/components/actions/Segmented";
import { sourceAttribute } from "../../design/components/data/source";
import { EmptyState, ErrorState, LoadingState } from "../../design/components/status/States";
import type { ViewProps } from "../../shell/header";
import { runErrorTitle, SERIES_COPY } from "../../words/series";
import { useJson, useLines } from "../common/read";
import { subtaskNames } from "../common/rows";
import { RunSwitcher } from "../common/RunSwitcher";
import { inProgress, runKey, runSource, useChosenRun } from "../common/runs";
import { BoundTable, rowAnchor } from "./BoundTable";
import { chooseView, groupsOf } from "./model";
import { Rail } from "./Rail";
import { RecordView } from "./RecordView";
import { TOOL_VIEWS, type ToolViewDef } from "./toolViews";

const AREA = "simulation";
const SLUG = "series";
/** The choice of view that shows the record's plots rather than a tool view. */
const SERIES_VIEW = "series";

function showRow(row: number) {
  const cell = document.getElementById(rowAnchor(row));
  cell?.scrollIntoView({ block: "center" });
  cell?.focus();
}

/**
 * Whether no session of the run left anything of a simulation: no record sealed, no file set
 * aside, and no quantity read off a record. A run whose roles ran no simulation reads so.
 */
function recordedNothing(listing: SeriesListing): boolean {
  return listing.attempts.every(
    (a) =>
      a.kind === "attempt" &&
      a.records.length === 0 &&
      a.setAside.length === 0 &&
      a.checks.length === 0 &&
      a.superseded.length === 0,
  );
}

/**
 * The record the screen shows: the one the address names, or else the first the rail lists that
 * the server read as sealed, or else the first it lists.
 */
function shownRecord(
  records: readonly AttemptRecord[],
  wanted: string | null,
): AttemptRecord | undefined {
  const ordered = groupsOf(records).flatMap((g) => g.records);
  return (
    ordered.find((r) => r.recordId !== null && r.recordId === wanted) ??
    ordered.find((r) => r.kind === "shown") ??
    ordered[0]
  );
}

/** The tool views, as tabs beside the plots, or the empty slot that says none is added. */
function ToolSlot({
  views,
  chosen,
  onChoose,
}: {
  readonly views: readonly ToolViewDef[];
  readonly chosen: string;
  readonly onChoose: (id: string) => void;
}) {
  if (views.length === 0) return null;
  return (
    <Segmented
      label={SERIES_COPY.views}
      value={chosen}
      onChange={onChoose}
      options={[
        { value: SERIES_VIEW, label: SERIES_COPY.recordedSeries, icon: "chart-line" },
        ...views.map((v) => ({ value: v.id, label: v.title, icon: v.icon })),
      ]}
    />
  );
}

function Body({
  listing,
  base,
  run,
  config,
  going,
  names,
  query,
  toolViews,
}: {
  readonly listing: SeriesListing;
  readonly base: string;
  readonly run: string;
  readonly config: RunConfig;
  readonly going: boolean;
  readonly names: ReadonlyMap<string, string>;
  readonly query: URLSearchParams;
  readonly toolViews: readonly ToolViewDef[];
}) {
  const choice = chooseView(listing, query);
  const attempt: ListedAttempt | null = choice?.attempt ?? null;
  const route =
    attempt === null || attempt.records.length === 0
      ? null
      : attemptRoute(base, attempt.subtaskId, attempt.attempt);
  const records = useJson(route, attemptRecords);
  const [view, setView] = useState(SERIES_VIEW);
  // Focus moves into the record when the person chooses one, never on the screen's first draw.
  const recordKey = `${attempt?.subtaskId ?? ""}/${String(attempt?.attempt ?? 0)}/${String(choice?.record)}`;
  const [openedOn] = useState(recordKey);
  const focus = recordKey !== openedOn;
  const read = records.result?.ok === true ? records.result.value.records : null;
  const record = read === null || choice === null ? undefined : shownRecord(read, choice.record);
  const checks = attempt?.checks ?? [];
  const checked = checks.flatMap((check, row) =>
    check.kind === "check" &&
    record !== undefined &&
    record.kind === "shown" &&
    check.recordId === record.recordId &&
    (check.sessionId === null || check.sessionId === record.sessionId)
      ? [{ check, row }]
      : [],
  );
  const titles = new Map(
    (read ?? []).flatMap((r) => (r.kind === "shown" ? [[r.recordId, r.title] as const] : [])),
  );
  const notSealed = new Set(
    (read ?? []).flatMap((r) => (r.kind === "refused" && r.refused === "seal" ? [r.recordId] : [])),
  );
  const tool = toolViews.find((v) => v.id === view);
  return (
    <div className="pg-sim">
      <Rail
        listing={listing}
        run={run}
        chosen={attempt}
        record={record?.recordId ?? null}
        records={records.result}
        recordsRoute={records.route}
        onRecordsAgain={records.again}
        names={names}
        going={going}
      />
      <div className="pg-sim-main">
        <ToolSlot views={toolViews} chosen={view} onChoose={setView} />
        {attempt === null ? null : tool !== undefined ? (
          <tool.component
            run={run}
            subtask={attempt.subtaskId}
            attempt={attempt.attempt}
            record={record?.recordId ?? null}
          />
        ) : attempt.records.length === 0 ? (
          <EmptyState title={SERIES_COPY.noSealed} icon="chart-line">
            {going ? SERIES_COPY.inProgress : undefined}
          </EmptyState>
        ) : records.result === null ? (
          <LoadingState reading={SERIES_COPY.readingRun} />
        ) : !records.result.ok ? (
          <ErrorState
            title={SERIES_COPY.attemptError}
            {...records.result.refusal}
            route={records.route}
            onRetry={records.again}
          />
        ) : record === undefined ? (
          <EmptyState title={SERIES_COPY.noSealed} icon="chart-line" />
        ) : (
          <RecordView
            key={`${attempt.subtaskId}/${String(attempt.attempt)}/${record.recordId ?? ""}`}
            record={record}
            base={base}
            subtask={attempt.subtaskId}
            attempt={attempt.attempt}
            runId={config.runId}
            role={attempt.ownerRole}
            checks={checked}
            tolerance={listing.tolerance}
            onShowRow={showRow}
            focus={focus}
          />
        )}
        {toolViews.length === 0 && (
          <EmptyState title={SERIES_COPY.slotTitle} icon="box">
            {SERIES_COPY.slotBody}
          </EmptyState>
        )}
        {attempt !== null && (
          <BoundTable
            checks={checks}
            tolerance={listing.tolerance}
            run={run}
            graphSource={runSource(config)}
            titles={titles}
            notSealed={notSealed}
          />
        )}
      </div>
    </div>
  );
}

/** The screen, with the tool views it offers: the registry's, or a test's. */
export function SimulationScreen({
  setHeader,
  query,
  toolViews = TOOL_VIEWS,
}: ViewProps & { readonly toolViews?: readonly ToolViewDef[] }) {
  const chosen = useChosenRun(query);
  const { runs, config, status, base, label } = chosen;
  const listing = useJson(base === null ? null : seriesRoute(base), seriesListing);
  const events = useLines(base === null ? null : `${base}/events`, runEvent);
  const configValue = config?.ok === true ? config.value : undefined;
  const going = status?.ok === true && inProgress(status.value);
  useEffect(() => {
    if (runs?.ok === true && runs.value.length === 0)
      setHeader({ title: SERIES_COPY.title, runState: "none" });
    else if (config?.ok === false || runs?.ok === false || listing.result?.ok === false)
      setHeader({ title: SERIES_COPY.title, runState: "unread" });
    else if (configValue !== undefined)
      setHeader({
        title: SERIES_COPY.title,
        source: runSource(configValue),
        gateMode: configValue.gateMode,
        osLayer: configValue.osLayer,
        inProgress: going,
        ...(label === undefined ? {} : { run: label }),
      });
  }, [runs, config, configValue, going, label, setHeader, listing.result]);
  const lede = <p className="pg-screen-lead">{SERIES_COPY.lede}</p>;
  if (runs === null)
    return (
      <div className="pg-screen">
        {lede}
        <LoadingState reading="the run list" />
      </div>
    );
  if (!runs.ok)
    return (
      <div className="pg-screen">
        {lede}
        <ErrorState title="The run list could not be read" {...runs.refusal} route="/api/runs" />
      </div>
    );
  if (chosen.chosen === undefined || base === null)
    return (
      <div className="pg-screen">
        {lede}
        <EmptyState title={SERIES_COPY.noRunTitle}>{SERIES_COPY.noRunBody}</EmptyState>
      </div>
    );
  const run = runKey(chosen.chosen);
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
  const names =
    events.result?.ok === true ? subtaskNames(events.result.value) : new Map<string, string>();
  let body;
  if (config === null || listing.result === null)
    body = <LoadingState reading={SERIES_COPY.readingRun} />;
  else if (!config.ok)
    body = (
      <ErrorState
        title="The run's configuration could not be read"
        {...config.refusal}
        onRetry={chosen.again}
      />
    );
  else if (!listing.result.ok && listing.result.refusal.status === 404)
    // The run has no event log yet: no session of it has ended, so none has sealed a record.
    body = (
      <EmptyState title={SERIES_COPY.noRecordsTitle} icon="chart-line">
        {`${SERIES_COPY.noRecordsBody} ${SERIES_COPY.inProgress}`}
      </EmptyState>
    );
  else if (!listing.result.ok)
    body = (
      <ErrorState
        title={runErrorTitle(listing.result.refusal.error)}
        {...listing.result.refusal}
        route={listing.route}
        onRetry={listing.again}
      />
    );
  else if (recordedNothing(listing.result.value))
    body = (
      <EmptyState title={SERIES_COPY.noRecordsTitle} icon="chart-line">
        {going
          ? `${SERIES_COPY.noRecordsBody} ${SERIES_COPY.inProgress}`
          : SERIES_COPY.noRecordsBody}
      </EmptyState>
    );
  else
    body = (
      <div data-source={sourceAttribute(runSource(config.value))}>
        <Body
          listing={listing.result.value}
          base={base}
          run={run}
          config={config.value}
          going={going}
          names={names}
          query={query}
          toolViews={toolViews}
        />
      </div>
    );
  return (
    <div className="pg-screen">
      {switcher}
      {lede}
      {body}
    </div>
  );
}

export default function Simulation(props: ViewProps) {
  return <SimulationScreen {...props} />;
}
