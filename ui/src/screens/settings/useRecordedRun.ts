/**
 * The run Settings shows, and what it recorded. Built from the shared run parts, but reading the
 * configuration once and through the Settings guard alone: a field that guard cannot read leaves
 * only its own row, and its own part of the top bar's chip, out.
 *
 * With no run named in the address, it opens on the newest of the runs whose labels are read: the
 * one whose first event is the latest. Until those are read, no run's configuration is asked for,
 * so it never asks for one run and then shows another.
 */
import { useState } from "react";

import type { Result } from "../../api/client";
import type { RunListing } from "../../api/records";
import { type RunStatus, runStatus } from "../../api/run";
import { type RecordedSystem, recordedSystem } from "../../api/settings";
import { instant, type RunLabel } from "../../words/runs";
import { type Read, useJson } from "../common/read";
import { FIRST_RUNS, runBase, runKey, useLabels, useRunList, useStarts } from "../common/runs";

export interface RecordedRun {
  readonly runs: Result<readonly RunListing[]> | null;
  /** The run shown; ``undefined`` while it is chosen, or when there is none to show. */
  readonly chosen: RunListing | undefined;
  /** The newest run is not known yet: its candidates' starts are still being read. */
  readonly choosing: boolean;
  readonly base: string | null;
  readonly config: Read<RecordedSystem>;
  readonly status: Read<RunStatus>;
  readonly labels: ReadonlyMap<string, RunLabel>;
  readonly label: RunLabel | undefined;
  readonly showAll: () => void;
  readonly allShown: boolean;
}

/** The run among ``runs`` whose start is the latest; the first when no start can be read. */
export function newestRun(
  runs: readonly RunListing[],
  starts: ReadonlyMap<string, string | null>,
): RunListing | undefined {
  let newest: RunListing | undefined;
  let at = Number.NEGATIVE_INFINITY;
  for (const run of runs) {
    const ts = starts.get(runKey(run));
    const when = ts === null || ts === undefined ? Number.NaN : instant(ts);
    if (!Number.isNaN(when) && when > at) {
      newest = run;
      at = when;
    }
  }
  return newest ?? runs[0];
}

export function useRecordedRun(query: URLSearchParams): RecordedRun {
  const runs = useRunList();
  const listed = runs?.ok === true ? runs.value : [];
  const readable = listed.filter((run) => run.error === null);
  const wanted = query.get("run");
  const named = readable.find((run) => runKey(run) === wanted);
  const [all, setAll] = useState(false);
  const starts = useStarts(listed, all, named);
  const labels = useLabels(listed, starts);
  const candidates = readable.slice(0, FIRST_RUNS);
  const known = candidates.every((run) => starts.has(runKey(run)));
  const chosen = named ?? (known ? newestRun(candidates, starts) : undefined);
  const base = chosen === undefined ? null : runBase(chosen);
  const config = useJson(base === null ? null : `${base}/config`, recordedSystem);
  const status = useJson(base === null ? null : `${base}/status`, runStatus);
  return {
    runs,
    chosen,
    choosing: named === undefined && readable.length > 0 && !known,
    base,
    config,
    status,
    labels,
    label: chosen === undefined ? undefined : labels.get(runKey(chosen)),
    showAll: () => {
      setAll(true);
    },
    allShown: all || readable.length <= FIRST_RUNS,
  };
}
