/**
 * The gate's per-check records for one run, in its mode: the tally with unchecked after the
 * separator, each check with what it measured, its bound and, where it did not pass, why. Beside
 * it, the same design run with the gate in another mode, when the person picks one. A run whose
 * gate was off says so and shows no result.
 */
import { useEffect, useState } from "react";

import { runEvent } from "../../api/events";
import { gateCheck } from "../../api/run";
import { Segmented } from "../../design/components/actions/Segmented";
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
import { hrefFor } from "../../shell/route";
import { useConfigs } from "../common/configs";
import { useLines } from "../common/read";
import { subtaskNames } from "../common/rows";
import { RunSwitcher } from "../common/RunSwitcher";
import { inProgress, runKey, runSource, useChosenRun } from "../common/runs";
import { ChecksTable, type Filter, kept } from "./ChecksTable";
import { PairedRun } from "./PairedRun";
import { pairable } from "./pairing";

const AREA = "orchestration";
const SLUG = "gate-checks";

export default function GateChecks({ setHeader, query }: ViewProps) {
  const chosen = useChosenRun(query);
  const { runs, config, status, base, label } = chosen;
  const checks = useLines(base === null ? null : `${base}/gate-checks`, gateCheck);
  const events = useLines(base === null ? null : `${base}/events`, runEvent);
  const configs = useConfigs(runs?.ok === true ? runs.value : null);
  const [filter, setFilter] = useState<Filter>("all");
  const configValue = config?.ok === true ? config.value : undefined;
  const going = status?.ok === true && inProgress(status.value);
  useEffect(() => {
    if (runs?.ok === true && runs.value.length === 0)
      setHeader({ title: "Gate checks", runState: "none" });
    else if (config?.ok === false || runs?.ok === false || checks.result?.ok === false)
      setHeader({ title: "Gate checks", runState: "unread" });
    else if (configValue !== undefined)
      setHeader({
        title: "Gate checks",
        source: runSource(configValue),
        gateMode: configValue.gateMode,
        osLayer: configValue.osLayer,
        inProgress: going,
        ...(label === undefined ? {} : { run: label }),
      });
  }, [runs, config, configValue, going, label, setHeader, checks.result]);
  if (runs === null) return <LoadingState reading="the run list" />;
  if (!runs.ok)
    return (
      <ErrorState title="The run list could not be read" {...runs.refusal} route="/api/runs" />
    );
  if (chosen.chosen === undefined || base === null)
    return (
      <EmptyState title="No run to show yet">
        A run's gate checks appear here once a run is recorded on this machine.
      </EmptyState>
    );
  const pairHref = (key: string | null) => {
    const next = new URLSearchParams(query);
    if (chosen.chosen !== undefined) next.set("run", runKey(chosen.chosen));
    if (key === null) next.delete("pair");
    else next.set("pair", key);
    return hrefFor(AREA, SLUG, next);
  };
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
  if (config === null || checks.result === null)
    return (
      <div className="pg-screen">
        {switcher}
        <LoadingState reading="the gate's records" />
      </div>
    );
  if (!config.ok)
    return (
      <div className="pg-screen">
        {switcher}
        <ErrorState
          title="The run's configuration could not be read"
          {...config.refusal}
          onRetry={chosen.again}
        />
      </div>
    );
  if (!checks.result.ok)
    return (
      <div className="pg-screen">
        {switcher}
        <ErrorState
          title="The gate checks could not be read. Nothing is shown rather than a partial list."
          {...checks.result.refusal}
          route={checks.route}
          onRetry={checks.again}
        />
      </div>
    );
  const cfg = config.value;
  const source = runSource(cfg);
  const all = checks.result.value;
  const names =
    events.result?.ok === true ? subtaskNames(events.result.value) : new Map<string, string>();
  const shown = kept(all, filter);
  return (
    <div className="pg-screen">
      {switcher}
      <div className="pg-split">
        <section
          className="pg-card pg-panel"
          aria-label="Gate checks"
          data-source={sourceAttribute(source)}
        >
          <header className="pg-panel-head">
            <h2 className="pg-panel-title">
              <Term term="gate">Gate</Term> checks of {label?.label ?? `Run ${chosen.chosen.name}`}
            </h2>
            <GateModeBadge mode={cfg.gateMode} />
            {going && <InProgressBadge />}
          </header>
          <p className="pg-panel-note pg-figure-line">
            Read from the gate's records of this run, manifest{" "}
            <Id value={cfg.manifestId.slice(0, 12)} copy={false} />
            <SourceChip {...source} />
          </p>
          {cfg.gateMode === "off" ? (
            <EmptyState title="The gate did not run">
              This run's gate mode is off: every gate stage was skipped and recorded as skipped. No
              check result exists, so none is shown.
            </EmptyState>
          ) : all.length === 0 ? (
            <EmptyState title="No gate checks recorded">
              The gate has not run in this run.
            </EmptyState>
          ) : (
            <>
              <div className="pg-toolbar">
                <Tally
                  {...tallyOfChecks(all)}
                  observed={cfg.gateMode === "observe"}
                  partial={going}
                />
                <span className="pg-toolbar-end">
                  <Segmented
                    label="Show checks"
                    value={filter}
                    onChange={setFilter}
                    options={[
                      { value: "all", label: "All" },
                      { value: "not-passed", label: "Not passed" },
                      { value: "unchecked", label: "Unchecked" },
                    ]}
                  />
                </span>
              </div>
              <p className="pg-panel-note">
                View: counted from {all.length} gate records, one per check and scope that passed
                and one per failing, warning or <Term term="unchecked">unchecked</Term> instance.
              </p>
              {shown.length === 0 ? (
                <p className="pg-panel-empty">No check matches this filter.</p>
              ) : (
                <ChecksTable checks={shown} names={names} source={source} />
              )}
            </>
          )}
        </section>
        {configs === null ? (
          <LoadingState reading="the other runs' configurations" />
        ) : configs.ok ? (
          <PairedRun
            candidates={pairable(cfg, configs.value)}
            labels={chosen.labels}
            pairKey={query.get("pair")}
            pairHref={pairHref}
          />
        ) : (
          <ErrorState title="The other runs could not be read" {...configs.refusal} />
        )}
      </div>
    </div>
  );
}
