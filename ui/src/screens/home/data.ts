/**
 * What Home reads: for each of the first runs listed (all of them once the person asks), its
 * configuration, where it stands, its event log and its queue. Each is the record or its
 * refusal. Home computes nothing from them but counts it labels as a view. Where each run stands
 * is read again while Home is shown.
 */
import { useEffect, useRef, useState } from "react";

import { getJson, getLines, type Result } from "../../api/client";
import { type RunEvent, runEvent, startedAt } from "../../api/events";
import { type QueueListing, queueListing } from "../../api/queue";
import { type RunConfig, runConfig, type RunListing } from "../../api/records";
import { type RunStatus, runStatus } from "../../api/run";
import { STATUS_EVERY_MS, whileShown } from "../common/read";
import { FIRST_RUNS, inProgress, runBase, runKey } from "../common/runs";
import type { Phase } from "../../words/standing";

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

/** Home's order of the runs. */
export function homeOrder<T extends RunListing>(
  runs: readonly T[],
  phases: ReadonlyMap<string, Phase>,
): readonly T[] {
  // Red-row stub: the list order, unchanged.
  return phases.size < 0 ? [] : runs;
}

/** The runs Home reads in full: the first ``FIRST_RUNS`` readable ones, or all of them. */
export function readTargets(
  runs: readonly RunListing[],
  all: boolean,
  phases: ReadonlyMap<string, Phase> | null,
): readonly RunListing[] | null {
  // Red-row stub: the first twelve as listed, whatever the phases.
  if (phases !== null && phases.size < 0) return null;
  const readable = runs.filter((r) => r.error === null);
  return all ? readable : readable.slice(0, FIRST_RUNS);
}

/** Each target run's records, by run key, as they arrive. */
export function useRunReads(targets: readonly RunListing[]): ReadonlyMap<string, RunRead> {
  const [found, setFound] = useState<ReadonlyMap<string, RunRead>>(new Map());
  // What was read so far, for the timer's reads to compare a run's step against.
  const latest = useRef(found);
  useEffect(() => {
    latest.current = found;
  }, [found]);
  const key = targets.map(runKey).join(",");
  useEffect(() => {
    let live = true;
    for (const run of targets) {
      void readRun(run).then((read) => {
        if (live) setFound((current) => new Map(current).set(runKey(run), read));
      });
    }
    // Where each run stands is read again while Home is shown: only the status, and the whole
    // record of a run whose step changed, so a run that ends or stops is seen without a reload.
    const stop = whileShown(() => {
      for (const run of targets) {
        void getJson(`${runBase(run)}/status`, runStatus).then((status) => {
          const before = live ? latest.current.get(runKey(run)) : undefined;
          if (before === undefined) return;
          if (stepOf(before.status) !== stepOf(status))
            void readRun(run).then((read) => {
              if (live) setFound((now) => new Map(now).set(runKey(run), read));
            });
          setFound((now) => {
            const was = now.get(runKey(run));
            return was === undefined ? now : new Map(now).set(runKey(run), { ...was, status });
          });
        });
      }
    }, STATUS_EVERY_MS);
    return () => {
      live = false;
      stop();
    };
    // The key names the runs; the list is rebuilt every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return found;
}

/** A status's step and halt, to tell when a run's whole record must be read again. */
function stepOf(status: Result<RunStatus>): string {
  if (!status.ok) return "unread";
  const s = status.value;
  return `${s.kind}|${s.subtask ?? ""}|${s.halted?.reason ?? ""}|${s.owedHalt?.cause ?? ""}`;
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
