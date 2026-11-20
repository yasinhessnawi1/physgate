/**
 * The runs a screen reads: the list, the chosen run with its configuration and where it stands,
 * and each run's human label. The choice lives in the address's ``run`` query, so a link or a
 * shortcut keeps it.
 *
 * A label needs the run's start, which the run list names (the time of its log's first line), so
 * no run's log is read to label it.
 */
import { useMemo, useState } from "react";

import { getJson, type Result } from "../../api/client";
import { runEvent } from "../../api/events";
import { type RunConfig, runConfig, type RunListing, runListing } from "../../api/records";
import { type RunStatus, runStatus } from "../../api/run";
import type { Source } from "../../design/components/data/source";
import { orderRuns, type RunLabel, runLabels } from "../../words/runs";
import { queueListing } from "../../api/queue";
import { type Phase, phaseOf, type Standing, standingOf } from "../../words/standing";
import { runEnd, waitingFor } from "../home/runEnd";
import { useJson, useLines, useLiveJson } from "./read";
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

/** A run whose log ends at an incident owes its halt: said so, with the incident's cause. */
export function haltOwedWords(status: RunStatus): string | null {
  return status.owedHalt === null ? null : `Halt owed · ${status.owedHalt.cause}`;
}

/**
 * A halt taken, in plain words where the reason has them: a run halted on the account's usage
 * limit waits for it to reset, and a resume after the reset goes on. Any other reason is shown as
 * recorded, never guessed at.
 */
const HALT_WORDS: Readonly<Record<string, string>> = {
  usage_limit: "Waiting for the usage limit to reset",
};

/** A run's halt, in words: "Waiting for the usage limit to reset", or "Halted · <reason>". */
export function haltedWords(status: RunStatus): string | null {
  if (status.halted === null) return null;
  return HALT_WORDS[status.halted.reason] ?? `Halted · ${status.halted.reason}`;
}

/**
 * Whether the run is still going: its next step is work, neither done, a halt taken or owed, nor
 * a person's decision, and its log is not silent longer than a living run is (``phaseOf``).
 */
export function inProgress(status: RunStatus): boolean {
  return phaseOf(status) === "going";
}

/** Where the run a screen shows stands, or ``undefined`` until its status is read. */
export function phaseOfResult(status: Result<RunStatus> | null): Phase | undefined {
  return status?.ok === true ? phaseOf(status.value) : undefined;
}

/** The run list, read once per screen, newest start first (``orderRuns``). */
export function useRunList(): Result<readonly RunListing[]> | null {
  return useResult(
    () => getJson("/api/runs", (value) => orderRuns(runListing(value))),
    "/api/runs",
  );
}

/**
 * Every listed run's start, for its label, as the run list names it: no run's log is read for
 * it, so a screen reads only its own run's records. Every listed run is labelled.
 */
export function useStarts(runs: readonly RunListing[]): ReadonlyMap<string, string | null> {
  return useMemo(() => new Map(runs.map((run) => [runKey(run), run.started ?? null])), [runs]);
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
          started: run.started ?? starts.get(runKey(run)) ?? null,
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
  /** Where the chosen run stands, in words, once its status is read. */
  readonly standing: Standing | undefined;
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
  // Read again while the page is open, so a run that stops, or goes on, is seen without a reload.
  const status = useLiveJson(base === null ? null : `${base}/status`, runStatus);
  // An ended run's words need its log and queue: read only for a run that has ended.
  const ended = status.result?.ok === true && status.result.value.kind === "done";
  const endEvents = useLines(ended && base !== null ? `${base}/events` : null, runEvent);
  const endQueue = useJson(ended && base !== null ? `${base}/queue` : null, queueListing);
  const standing = useMemo(() => {
    if (status.result?.ok !== true) return undefined;
    const value = status.result.value;
    const events = endEvents.result;
    const queue = endQueue.result;
    const end =
      value.kind === "done" && events?.ok === true && queue !== null
        ? runEnd(
            events.value,
            waitingFor(queue.ok ? queue.value.open : null, value.superseded),
            value.completion,
          )
        : null;
    return standingOf(value, end);
  }, [status.result, endEvents.result, endQueue.result]);
  const [all, setAll] = useState(false);
  const starts = useStarts(listed);
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
    standing,
  };
}
