/**
 * Evidence: what the recorded runs measured, read-only. Five tabs over the evaluation's read
 * routes: the runs side by side with their kind, settings and pins; the two gaps each time they
 * were measured, as the gap trend's reader read them; a run's spend per role; two runs compared,
 * or the refusal naming the settings that differ; and the gate's catches per kind of run. Every
 * figure is a route's answer and names the run it came from; none is made here.
 *
 * There is no headline figure: no reportable run exists yet, and an ablation or development run's
 * number is never one. Nothing here writes, starts a run or decides: the screen only reads.
 */
import "./evidence.css";

import { useEffect } from "react";

import { Segmented } from "../../design/components/actions/Segmented";
import { EmptyState, ErrorState, LoadingState } from "../../design/components/status/States";
import { useJson } from "../../screens/common/read";
import type { ViewProps } from "../../shell/header";
import {
  CATCHES_ROUTE,
  evidenceCatches,
  evidenceGaps,
  evidenceRuns,
  GAPS_ROUTE,
  type RunRow,
  RUNS_ROUTE,
} from "./api";
import { evidenceAddress, go } from "./address";
import { CatchesTab } from "./Catches";
import { CompareTab } from "./Compare";
import { GapsTab } from "./Gaps";
import { RunsTab } from "./Runs";
import { SpendTab } from "./Spend";
import { EVIDENCE_COPY } from "./words";

export const TABS = ["runs", "gaps", "spend", "compare", "catches"] as const;
export type Tab = (typeof TABS)[number];

const TAB_WORDS: Readonly<Record<Tab, string>> = {
  runs: EVIDENCE_COPY.runsTab,
  gaps: EVIDENCE_COPY.gapsTab,
  spend: EVIDENCE_COPY.spendTab,
  compare: EVIDENCE_COPY.compareTab,
  catches: EVIDENCE_COPY.catchesTab,
};

/** The tab the address names, or the runs. */
export function tabOf(query: URLSearchParams): Tab {
  const named = query.get("tab");
  return TABS.find((tab) => tab === named) ?? "runs";
}

function Catches() {
  const catches = useJson(CATCHES_ROUTE, evidenceCatches);
  if (catches.result === null) return <LoadingState reading={EVIDENCE_COPY.readingCatches} />;
  if (!catches.result.ok)
    return (
      <ErrorState
        title={EVIDENCE_COPY.catchesRefused}
        {...catches.result.refusal}
        route={catches.route}
        onRetry={catches.again}
      />
    );
  return <CatchesTab catches={catches.result.value} />;
}

/** The gap trend: read from its own route, needing no run, so it shows with none. */
function Gaps() {
  const gaps = useJson(GAPS_ROUTE, evidenceGaps);
  if (gaps.result === null) return <LoadingState reading={EVIDENCE_COPY.readingGaps} />;
  if (!gaps.result.ok)
    return (
      <ErrorState
        title={EVIDENCE_COPY.gapsRefused}
        {...gaps.result.refusal}
        route={gaps.route}
        onRetry={gaps.again}
      />
    );
  return <GapsTab trend={gaps.result.value} />;
}

function Body({
  tab,
  rows,
  query,
}: {
  readonly tab: Tab;
  readonly rows: readonly RunRow[];
  readonly query: URLSearchParams;
}) {
  if (rows.length === 0) return <EmptyState title={EVIDENCE_COPY.noRun} icon="microscope" />;
  if (tab === "spend") return <SpendTab rows={rows} query={query} />;
  if (tab === "compare") return <CompareTab rows={rows} query={query} />;
  if (tab === "catches") return <Catches />;
  return <RunsTab rows={rows} />;
}

export default function Evidence({ setHeader, query }: ViewProps) {
  useEffect(() => {
    setHeader({ title: EVIDENCE_COPY.title });
  }, [setHeader]);
  const tab = tabOf(query);
  // The gap trend reads no run, so the runs are not asked for on its tab.
  const runs = useJson(tab === "gaps" ? null : RUNS_ROUTE, evidenceRuns);
  return (
    <div className="pg-screen pg-evidence">
      <p className="pg-screen-lead">{EVIDENCE_COPY.lead}</p>
      <Segmented
        label={EVIDENCE_COPY.tabs}
        value={tab}
        onChange={(next) => {
          go(evidenceAddress(query, { tab: next }));
        }}
        options={TABS.map((value) => ({ value, label: TAB_WORDS[value] }))}
      />
      <section className="evidence-panel" aria-label={TAB_WORDS[tab]} data-tab={tab}>
        {tab === "gaps" ? (
          <Gaps />
        ) : runs.result === null ? (
          <LoadingState reading={EVIDENCE_COPY.readingRuns} />
        ) : runs.result.ok ? (
          <Body tab={tab} rows={runs.result.value} query={query} />
        ) : (
          <ErrorState
            title={EVIDENCE_COPY.runsRefused}
            {...runs.result.refusal}
            route={runs.route}
            onRetry={runs.again}
          />
        )}
      </section>
    </div>
  );
}
