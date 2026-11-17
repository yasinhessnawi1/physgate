/**
 * What Home reads: where every readable run stands, which is small; then, for the first runs in
 * Home's order (all of them once the person asks), its configuration, its event log and its
 * queue. Each is the record or its refusal. Home computes nothing from them but counts it labels
 * as a view. Where each run stands is read again while Home is shown.
 *
 * Home's order puts a run going first, then a run waiting on a person's decision, so neither
 * falls off Home's first screen because twelve runs started after it (``homeOrder``).
 */
import { useEffect, useMemo, useRef, useState } from "react";

import { getJson, getLines, type Result } from "../../api/client";
import { type RunEvent, runEvent, startedAt } from "../../api/events";
import { type QueueListing, queueListing } from "../../api/queue";
import { type RunConfig, runConfig, type RunListing } from "../../api/records";
import { type RunStatus, runStatus } from "../../api/run";
import { orderRuns } from "../../words/runs";
import { type Phase, phaseOf } from "../../words/standing";
import { STATUS_EVERY_MS, whileShown } from "../common/read";
import { FIRST_RUNS, inProgress, runBase, runKey } from "../common/runs";

export interface RunRead {
  readonly run: RunListing;
  readonly config: Result<RunConfig>;
  readonly status: Result<RunStatus>;
  readonly events: Result<readonly RunEvent[]>;
  readonly queue: Result<QueueListing>;
}

/** A run's records Home reads beyond where it stands. */
type Records = Omit<RunRead, "run" | "status">;

async function readRecords(run: RunListing): Promise<Records> {
  const base = runBase(run);
  const [config, events, queue] = await Promise.all([
    getJson(`${base}/config`, runConfig),
    getLines(`${base}/events`, runEvent),
    getJson(`${base}/queue`, queueListing),
  ]);
  return { config, events, queue };
}

/** How many status reads Home has in flight at once. */
export const STATUS_POOL = 4;

/** How long Home waits for one run's status before it lists that run as not read, in ms. */
export const STATUS_TIMEOUT_MS = 15_000;

/** How long Home waits for the statuses before it chooses which runs to read in full, in ms. */
export const STATUS_GRACE_MS = 3_000;

/** Whether Home may choose which runs to read in full. */
export function useSettled(
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  runs: readonly RunListing[],
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  statuses: ReadonlyMap<string, Result<RunStatus>>,
): boolean {
  return false;
}

/** The phases Home lists first, in this order: a run going, then one waiting on a person. */
export const ATTENTION_FIRST: readonly Phase[] = ["going", "waiting-person"];

/**
 * Home's order: runs going, then runs waiting on a person's decision, newest start first within
 * each; then every other run newest start first (``orderRuns``). A run whose status was not read,
 * or was refused, is among the rest.
 */
export function homeOrder<T extends RunListing>(
  runs: readonly T[],
  phases: ReadonlyMap<string, Phase>,
): readonly T[] {
  const rank = (run: T) => {
    const phase = phases.get(runKey(run));
    const at = phase === undefined ? -1 : ATTENTION_FIRST.indexOf(phase);
    return at < 0 ? ATTENTION_FIRST.length : at;
  };
  // The sort is stable, so each group keeps the newest-first order.
  return [...orderRuns(runs)].sort((a, b) => rank(a) - rank(b));
}

/**
 * The runs Home reads in full, in Home's order: every readable run when the person asked for all
 * or there are no more than ``FIRST_RUNS``; else the first ``FIRST_RUNS`` once every readable
 * run's phase is known, and ``null`` until then, so a run going is never left out for want of
 * its status.
 */
export function readTargets(
  runs: readonly RunListing[],
  all: boolean,
  phases: ReadonlyMap<string, Phase> | null,
): readonly RunListing[] | null {
  const readable = runs.filter((r) => r.error === null);
  if (all || readable.length <= FIRST_RUNS) return homeOrder(readable, phases ?? new Map());
  return phases === null ? null : homeOrder(readable, phases).slice(0, FIRST_RUNS);
}

/** Every run's phase by run key once each of ``runs`` has answered, else ``null``. */
export function phasesOf(
  runs: readonly RunListing[],
  statuses: ReadonlyMap<string, Result<RunStatus>>,
): ReadonlyMap<string, Phase> | null {
  const phases = new Map<string, Phase>();
  for (const run of runs) {
    const status = statuses.get(runKey(run));
    if (status === undefined) return null;
    if (status.ok) phases.set(runKey(run), phaseOf(status.value));
  }
  return phases;
}

/**
 * Where each of ``runs`` stands, by run key, as each answers: only its status route, read again
 * while Home is shown, so a run that starts going, ends or stops is seen without a reload.
 */
export function useStatuses(runs: readonly RunListing[]): ReadonlyMap<string, Result<RunStatus>> {
  const [found, setFound] = useState<ReadonlyMap<string, Result<RunStatus>>>(new Map());
  const key = runs.map(runKey).join(",");
  useEffect(() => {
    let live = true;
    const read = () => {
      for (const run of runs) {
        void getJson(`${runBase(run)}/status`, runStatus).then((status) => {
          if (live) setFound((now) => new Map(now).set(runKey(run), status));
        });
      }
    };
    read();
    const stop = whileShown(read, STATUS_EVERY_MS);
    return () => {
      live = false;
      stop();
    };
    // The key names the runs; the list is rebuilt every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return found;
}

/**
 * Each target run's records with where it stands, by run key, as they arrive. A target's
 * configuration, log and queue are read once, and again when its status names another step.
 */
export function useRunReads(
  targets: readonly RunListing[],
  statuses: ReadonlyMap<string, Result<RunStatus>>,
): ReadonlyMap<string, RunRead> {
  const [records, setRecords] = useState<ReadonlyMap<string, Records>>(new Map());
  // Each target asked for, with its status's step when it was asked (``null``: not read then).
  const asked = useRef(new Map<string, string | null>());
  const live = useRef(true);
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);
  const key = targets.map(runKey).join(",");
  useEffect(() => {
    for (const run of targets) {
      const k = runKey(run);
      const status = statuses.get(k);
      const step = status === undefined ? null : stepOf(status);
      const before = asked.current.get(k);
      if (before === undefined || (before !== null && step !== null && before !== step)) {
        asked.current.set(k, step);
        void readRecords(run).then((read) => {
          if (live.current) setRecords((now) => new Map(now).set(k, read));
        });
      } else if (before === null && step !== null) asked.current.set(k, step);
    }
    // The key names the runs; the list is rebuilt every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, statuses]);
  return useMemo(() => {
    const found = new Map<string, RunRead>();
    for (const run of targets) {
      const k = runKey(run);
      const read = records.get(k);
      const status = statuses.get(k);
      if (read !== undefined && status !== undefined) found.set(k, { run, status, ...read });
    }
    return found;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, records, statuses]);
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
