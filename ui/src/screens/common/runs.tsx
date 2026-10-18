/**
 * The runs a screen reads: the list, the chosen run with its configuration and where it stands,
 * and each run's human label. The choice lives in the address's ``run`` query, so a link or a
 * shortcut keeps it.
 *
 * A label needs the run's first event, so each listed run's log is read once per page. Only the
 * first ``FIRST_RUNS`` runs are read before the person asks for all of them: a root with many runs
 * would otherwise make every screen read every log.
 */
import { useEffect, useMemo, useState } from "react";

import { getJson, getLines, type Result } from "../../api/client";
import { runEvent, startedAt } from "../../api/events";
import { type RunConfig, runConfig, type RunListing, runListing } from "../../api/records";
import { type RunStatus, runStatus } from "../../api/run";
import type { Source } from "../../design/components/data/source";
import { type RunLabel, runLabels } from "../../words/runs";
import { useJson } from "./read";
import { useResult } from "./useResult";

/** How many runs' logs a screen reads for their labels before the person asks for all. */
export const FIRST_RUNS = 12;

export function runKey(run: RunListing): string {
  return `${String(run.root)}/${run.name}`;
}

export function runBase(run: RunListing): string {
  return `/api/runs/${String(run.root)}/${encodeURIComponent(run.name)}`;
}

/** The route base of the run a ``root/name`` key names. */
export function baseOfKey(key: string): string {
  const [root = "", ...name] = key.split("/");
  return `/api/runs/${root}/${encodeURIComponent(name.join("/"))}`;
}

/** Where a figure of ``config``'s run comes from: the run and the harness commit. */
export function runSource(config: RunConfig): Source {
  return { id: `run ${config.runId}`, commit: config.harnessCommit };
}

/** Whether the run is still going: its next step is neither done nor a halt. */
export function inProgress(status: RunStatus): boolean {
  return status.kind !== "done" && status.halted === null && status.kind !== "halted";
}

// Each run's start, read once per page: its log's run_started line, or nothing when the log
// cannot be read (the run then reads by its folder's name).
const starts = new Map<string, Promise<string | null>>();

function startOf(base: string): Promise<string | null> {
  let found = starts.get(base);
  if (found === undefined) {
    found = getLines(`${base}/events`, runEvent).then((r) => (r.ok ? startedAt(r.value) : null));
    starts.set(base, found);
  }
  return found;
}

/** The run list, read once per screen. */
export function useRunList(): Result<readonly RunListing[]> | null {
  return useResult(() => getJson("/api/runs", runListing), "/api/runs");
}

/**
 * Every listed run's start, for its label: the first ``FIRST_RUNS`` readable runs unless ``all``,
 * and always ``also`` (the chosen run), whose label the top bar shows.
 */
export function useStarts(
  runs: readonly RunListing[],
  all: boolean,
  also?: RunListing,
): ReadonlyMap<string, string | null> {
  const [found, setFound] = useState<ReadonlyMap<string, string | null>>(new Map());
  const readable = runs.filter((r) => r.error === null);
  const wanted = all ? readable : readable.slice(0, FIRST_RUNS);
  if (also !== undefined && !wanted.includes(also)) wanted.push(also);
  const key = wanted.map(runKey).join(",");
  useEffect(() => {
    let live = true;
    for (const run of wanted) {
      void startOf(runBase(run)).then((ts) => {
        if (live) setFound((current) => new Map(current).set(runKey(run), ts));
      });
    }
    return () => {
      live = false;
    };
    // The key names the runs asked for; the list is rebuilt every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return found;
}

/** Every listed run's label, from the starts read so far. */
export function useLabels(
  runs: readonly RunListing[],
  starts: ReadonlyMap<string, string | null>,
): ReadonlyMap<string, RunLabel> {
  return useMemo(
    () =>
      runLabels(
        runs.map((run) => ({
          key: runKey(run),
          name: run.name,
          runId: run.runId,
          started: starts.get(runKey(run)) ?? null,
        })),
      ),
    [runs, starts],
  );
}

export interface ChosenRun {
  readonly runs: Result<readonly RunListing[]> | null;
  readonly chosen: RunListing | undefined;
  readonly config: Result<RunConfig> | null;
  readonly status: Result<RunStatus> | null;
  /** The path every route over the chosen run starts with. */
  readonly base: string | null;
  readonly labels: ReadonlyMap<string, RunLabel>;
  readonly label: RunLabel | undefined;
  readonly showAll: () => void;
  readonly allShown: boolean;
  readonly again: () => void;
}

/** The run the query names, or the first readable one, with its configuration and status. */
export function useChosenRun(query: URLSearchParams): ChosenRun {
  const runs = useRunList();
  const listed = runs?.ok === true ? runs.value : [];
  const readable = listed.filter((run) => run.error === null);
  const wanted = query.get("run");
  const chosen = readable.find((run) => runKey(run) === wanted) ?? readable[0];
  const base = chosen === undefined ? null : runBase(chosen);
  const config = useJson(base === null ? null : `${base}/config`, runConfig);
  const status = useJson(base === null ? null : `${base}/status`, runStatus);
  const [all, setAll] = useState(false);
  const starts = useStarts(listed, all, chosen);
  const labels = useLabels(listed, starts);
  return {
    runs,
    chosen,
    config: config.result,
    status: status.result,
    base,
    labels,
    label: chosen === undefined ? undefined : labels.get(runKey(chosen)),
    showAll: () => {
      setAll(true);
    },
    allShown: all || readable.length <= FIRST_RUNS,
    again: () => {
      config.again();
      status.again();
    },
  };
}
