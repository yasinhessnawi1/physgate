/**
 * The gate's per-check records for one run, in its mode, counted by the one tally with unchecked
 * apart, each check with what it measured, its bound and, where it did not pass, why. Beside it,
 * the same plan in another gate mode, when the operator picks a run of the same brief and seed.
 */
import { useEffect } from "react";

import { getLines } from "../../api/client";
import { gateCheck } from "../../api/run";
import { EmptyState, ErrorState, LoadingState } from "../../design/components/States";
import type { ViewProps } from "../../shell/header";
import { hrefFor } from "../../shell/route";
import { useConfigs } from "../common/configs";
import { RunPicker, runKey, runSource, useChosenRun } from "../common/runs";
import { useResult } from "../common/useResult";
import { GateChecksSummary } from "./GateChecksSummary";
import { GateChecksTable } from "./GateChecksTable";
import { PairedRun } from "./PairedRun";
import { pairable } from "./pairing";

const AREA = "orchestration";
const SLUG = "gate-checks";

export default function GateChecks({ setHeader, query }: ViewProps) {
  const { runs, chosen, config, base } = useChosenRun(query);
  const checks = useResult(
    base === null ? null : () => getLines(`${base}/gate-checks`, gateCheck),
    `${String(base)}/gate-checks`,
  );
  const configs = useConfigs(runs?.ok === true ? runs.value : null);
  useEffect(() => {
    if (config?.ok === true)
      setHeader({
        title: "Gate checks",
        source: runSource(config.value),
        gateMode: config.value.gateMode,
      });
  }, [config, setHeader]);
  if (runs === null) return <LoadingState reading="the run list" />;
  if (!runs.ok) return <ErrorState title="The run list was refused" refusal={runs.refusal} />;
  if (chosen === undefined)
    return (
      <EmptyState title="No runs under the roots yet">
        A run's gate checks appear here once a run directory exists under a root this server was
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
      {config === null || checks === null ? (
        <LoadingState reading="the gate events" />
      ) : !config.ok ? (
        <ErrorState title="The run's configuration was refused" refusal={config.refusal} />
      ) : !checks.ok ? (
        <ErrorState title="Gate checks: not shown" refusal={checks.refusal} />
      ) : (
        <div className="view">
          <div className="view">
            <GateChecksSummary
              checks={checks.value}
              mode={config.value.gateMode}
              source={runSource(config.value)}
              manifestId={config.value.manifestId}
            >
              <GateChecksTable checks={checks.value} />
            </GateChecksSummary>
          </div>
          <div className="view">
            {configs === null ? (
              <LoadingState reading="the other runs' configurations" />
            ) : configs.ok ? (
              <PairedRun
                candidates={pairable(config.value, configs.value)}
                pairKey={query.get("pair")}
                pairHref={pairHref}
              />
            ) : (
              <ErrorState title="The other runs could not be read" refusal={configs.refusal} />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
