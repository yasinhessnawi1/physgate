/**
 * One run as it happened: a row per recorded event, the run's own lines first-level, each
 * subtask's beneath, each attempt's beneath that, every row a sentence with its actor. Above it,
 * the run's gate tally and cost so far. An attempt's rows open the attempt inspector: its
 * sessions with their seals, its gate checks, its reviews, and why it failed.
 */
import { useEffect, useMemo, useState } from "react";

import { runEvent } from "../../api/events";
import { queueListing } from "../../api/queue";
import { costRecord, priceDates } from "../../api/records";
import { gateCheck, trace as runTrace } from "../../api/run";
import { Segmented } from "../../design/components/actions/Segmented";
import { Figure } from "../../design/components/data/Figure";
import { Id } from "../../design/components/data/Id";
import { SourceChip } from "../../design/components/data/SourceChip";
import { sourceAttribute } from "../../design/components/data/source";
import { Term } from "../../design/components/help/Term";
import { InProgressBadge } from "../../design/components/status/InProgressBadge";
import { EmptyState, ErrorState, LoadingState } from "../../design/components/status/States";
import { GateModeBadge } from "../../design/components/verdict/GateMode";
import { Tally } from "../../design/components/verdict/Tally";
import { tallyOfChecks } from "../../design/tally";
import type { ViewProps } from "../../shell/header";
import { InspectorPortal } from "../../shell/inspector";
import { hrefFor } from "../../shell/route";
import { CostCaveat } from "../common/cost";
import { useJson, useLines } from "../common/read";
import { RowView } from "../common/RowView";
import { type Row, rowsOf, subtaskNames, subtaskRoles } from "../common/rows";
import { RunSwitcher } from "../common/RunSwitcher";
import { inProgress, runSource, useChosenRun } from "../common/runs";
import { AttemptInspector } from "./AttemptInspector";

const AREA = "orchestration";
const SLUG = "run-timeline";

type Who = "all" | "harness" | "agents";

function shownFor(who: Who, row: Row): boolean {
  if (who === "all") return true;
  if (who === "harness") return row.actor.kind === "deterministic";
  return row.actor.kind === "agent" || row.actor.kind === "unmapped";
}

/** ``subtask:attempt`` from the address, or ``null``. */
export function parseAttempt(
  value: string | null,
): { readonly subtask: string; readonly attempt: number } | null {
  const found = value === null ? null : /^(.+):(\d{1,4})$/.exec(value);
  if (found === null) return null;
  return { subtask: found[1] ?? "", attempt: Number(found[2]) };
}

export default function RunTimeline({ setHeader, query }: ViewProps) {
  const chosen = useChosenRun(query);
  const { runs, config, status, base, label } = chosen;
  const events = useLines(base === null ? null : `${base}/events`, runEvent);
  const checks = useLines(base === null ? null : `${base}/gate-checks`, gateCheck);
  const trace = useJson(base === null ? null : `${base}/trace`, runTrace);
  const queue = useJson(base === null ? null : `${base}/queue`, queueListing);
  const prices = useJson("/api/prices", priceDates);
  const newest = prices.result?.ok === true ? prices.result.value.at(-1) : undefined;
  const cost = useJson(
    base === null || newest === undefined ? null : `${base}/cost/${newest}`,
    costRecord,
  );
  const [who, setWho] = useState<Who>("all");
  const going = status?.ok === true && inProgress(status.value);
  const configValue = config?.ok === true ? config.value : undefined;

  useEffect(() => {
    if (runs?.ok === true && runs.value.length === 0)
      setHeader({ title: "Run timeline", runState: "none" });
    else if (
      config?.ok === false ||
      runs?.ok === false ||
      events.result?.ok === false ||
      checks.result?.ok === false
    )
      setHeader({ title: "Run timeline", runState: "unread" });
    else if (configValue !== undefined)
      setHeader({
        title: "Run timeline",
        source: runSource(configValue),
        gateMode: configValue.gateMode,
        osLayer: configValue.osLayer,
        inProgress: going,
        ...(label === undefined ? {} : { run: label }),
      });
  }, [runs, config, configValue, going, label, setHeader, events.result, checks.result]);

  const rows = useMemo(
    () =>
      events.result?.ok === true && configValue !== undefined
        ? rowsOf(
            events.result.value,
            configValue,
            checks.result?.ok === true ? checks.result.value : [],
          )
        : [],
    [events.result, configValue, checks.result],
  );

  if (runs === null) return <LoadingState reading="the run list" />;
  if (!runs.ok)
    return (
      <ErrorState title="The run list could not be read" {...runs.refusal} route="/api/runs" />
    );
  if (chosen.chosen === undefined || base === null)
    return (
      <EmptyState title="No run to show yet">
        A run's timeline appears here once a run is recorded on this machine.
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
  if (config === null || events.result === null || checks.result === null)
    return (
      <div className="pg-screen">
        {switcher}
        <LoadingState reading="the run's history" />
      </div>
    );
  for (const [answer, what, read] of [
    [config, "The run's configuration could not be read", chosen.again],
    [events.result, "The run's event log could not be read", events.again],
    [checks.result, "The run's gate checks could not be read", checks.again],
  ] as const) {
    if (!answer.ok)
      return (
        <div className="pg-screen">
          {switcher}
          <ErrorState title={what} {...answer.refusal} onRetry={read} />
        </div>
      );
  }
  if (!config.ok || !events.result.ok || !checks.result.ok) return null;
  const cfg = config.value;
  const source = runSource(cfg);
  const log = events.result.value;
  const names = subtaskNames(log);
  const roles = subtaskRoles(log);
  const selected = parseAttempt(query.get("attempt"));
  const select = (row: Row) => {
    if (row.subtask === null || row.attempt === null) return undefined;
    const subtask = row.subtask;
    const attempt = row.attempt;
    return () => {
      const next = new URLSearchParams(query);
      next.set("attempt", `${subtask}:${String(attempt)}`);
      window.location.hash = hrefFor(AREA, SLUG, next).slice(1);
    };
  };
  const shown = rows.filter((row) => shownFor(who, row));
  const counts = tallyOfChecks(checks.result.value);
  return (
    <div className="pg-screen pg-timeline" data-source={sourceAttribute(source)}>
      {switcher}
      <header className="pg-run-head">
        <div className="pg-run-head-title">
          <h2 className="pg-screen-title" title={label?.detail}>
            {label?.label ?? `Run ${chosen.chosen.name}`}
          </h2>
          <GateModeBadge mode={cfg.gateMode} />
          {going && <InProgressBadge />}
          <Id value={cfg.runId} />
        </div>
        <div className="pg-run-head-facts">
          <span className="pg-figure-line">
            <span className="pg-label">
              Cost{going ? " so far" : ""} · <Term term="list-price">List-price estimate</Term>
            </span>
            {cost.result === null ? (
              <span className="pg-muted">Reading…</span>
            ) : cost.result.ok ? (
              <>
                <Figure {...cost.result.value.usd} source={source} partial={going} />
                <span className="pg-panel-note">
                  price sheet of {cost.result.value.pricesDate}
                  <CostCaveat cost={cost.result.value} />
                </span>
              </>
            ) : (
              <span className="pg-muted">not read: {cost.result.refusal.error}</span>
            )}
          </span>
          <span className="pg-figure-line">
            <span className="pg-label">
              <Term term="gate">Gate</Term> checks{going ? " so far" : ""}
            </span>
            {cfg.gateMode === "off" ? (
              <span className="pg-muted">The gate is off in this run: nothing was checked.</span>
            ) : log.length > 0 && checks.result.value.length === 0 ? (
              <span className="pg-muted">No gate checks recorded</span>
            ) : (
              <Tally {...counts} observed={cfg.gateMode === "observe"} partial={going} compact />
            )}
          </span>
        </div>
      </header>
      <div className="pg-toolbar">
        <Segmented
          label="Show rows by who did it"
          value={who}
          onChange={setWho}
          options={[
            { value: "all", label: "Everyone" },
            { value: "harness", label: "Harness" },
            { value: "agents", label: "Agents" },
          ]}
        />
        <span className="pg-panel-note pg-toolbar-end">
          Select an attempt's row to inspect the <Term term="attempt">attempt</Term>
        </span>
      </div>
      {log.length === 0 ? (
        <EmptyState title="Nothing is recorded in this run yet">
          The run's rows appear here as its log records them.
        </EmptyState>
      ) : (
        <section className="pg-card pg-rows-card" aria-label="Timeline">
          {shown.map((row) => {
            const open = select(row);
            const on =
              selected !== null &&
              row.subtask === selected.subtask &&
              row.attempt === selected.attempt;
            return (
              <RowView
                key={row.key}
                row={row}
                {...(open === undefined ? {} : { onSelect: open, selected: on })}
              />
            );
          })}
        </section>
      )}
      <SourceChip {...source} />
      {selected !== null && (
        <InspectorPortal>
          <AttemptInspector
            base={base}
            config={cfg}
            subtask={selected.subtask}
            attempt={selected.attempt}
            name={names.get(selected.subtask) ?? selected.subtask}
            role={roles[selected.subtask]}
            runLabel={label?.label ?? `Run ${chosen.chosen.name}`}
            events={log}
            checks={checks.result.value}
            trace={trace.result}
            queue={queue.result}
          />
        </InspectorPortal>
      )}
    </div>
  );
}
