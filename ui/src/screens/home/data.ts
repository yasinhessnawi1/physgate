/**
 * What Home reads: for each of the first runs listed (all of them once the person asks), its
 * configuration, where it stands, its event log and its queue. Each is the record or its
 * refusal. Home computes nothing from them but counts it labels as a view.
 */
import { useEffect, useState } from "react";

import { getJson, getLines, type Result } from "../../api/client";
import { type RunEvent, runEvent, startedAt } from "../../api/events";
import { type QueueListing, queueListing } from "../../api/queue";
import { type RunConfig, runConfig, type RunListing } from "../../api/records";
import { type RunStatus, runStatus } from "../../api/run";
import { FIRST_RUNS, inProgress, runBase, runKey } from "../common/runs";

export interface RunRead {
  readonly run: RunListing;
  readonly config: Result<RunConfig>;
  readonly status: Result<RunStatus>;
  readonly events: Result<readonly RunEvent[]>;
  readonly queue: Result<QueueListing>;
}

async function readRun(run: RunListing): Promise<RunRead> {
  const base = runBase(run);
  const [config, status, events, queue] = await Promise.all([
    getJson(`${base}/config`, runConfig),
    getJson(`${base}/status`, runStatus),
    getLines(`${base}/events`, runEvent),
    getJson(`${base}/queue`, queueListing),
  ]);
  return { run, config, status, events, queue };
}

/** The runs Home reads in full: the first ``FIRST_RUNS`` readable ones, or all of them. */
export function readTargets(runs: readonly RunListing[], all: boolean): readonly RunListing[] {
  const readable = runs.filter((r) => r.error === null);
  return all ? readable : readable.slice(0, FIRST_RUNS);
}

/** Each target run's records, by run key, as they arrive. */
export function useRunReads(targets: readonly RunListing[]): ReadonlyMap<string, RunRead> {
  const [found, setFound] = useState<ReadonlyMap<string, RunRead>>(new Map());
  const key = targets.map(runKey).join(",");
  useEffect(() => {
    let live = true;
    for (const run of targets) {
      void readRun(run).then((read) => {
        if (live) setFound((current) => new Map(current).set(runKey(run), read));
      });
    }
    return () => {
      live = false;
    };
    // The key names the runs; the list is rebuilt every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return found;
}

/** When a run started, from its log; ``null`` when the log was refused. */
export function startOfRead(read: RunRead): string | null {
  return read.events.ok ? startedAt(read.events.value) : null;
}

/** The latest-started run among those read that is still going, if any. */
export function activeRun(reads: readonly RunRead[]): RunRead | undefined {
  return reads
    .filter((r) => r.status.ok && inProgress(r.status.value))
    .sort((a, b) => (startOfRead(b) ?? "").localeCompare(startOfRead(a) ?? ""))[0];
}
