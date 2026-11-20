/**
 * What Home reads: where every readable run stands, which is small; then, for the first runs in
 * Home's order (all of them once the person asks), its configuration, its event log and its
 * queue. Each is the record or its refusal. Home computes nothing from them but counts it labels
 * as a view. Where each run stands is read again while Home is shown.
 *
 * Home's order puts a run going first, then a run waiting on a person's decision, then one halted
 * or stopped, so none falls off Home's first screen because twelve runs started after it
 * (``homeOrder``). Home lists the runs at once in the run list's order, settles its order once,
 * when the first round of statuses has answered or after a short wait, and moves a row after that
 * only when a minute's re-read ends (``useOrderPhases``).
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

/**
 * Whether Home may choose which runs to read in full: once every one of ``runs`` has answered
 * where it stands (or been given up), or ``STATUS_GRACE_MS`` after Home began to read them,
 * whichever is first. One slow status never keeps Home from reading the others.
 */
export function useSettled(
  runs: readonly RunListing[],
  statuses: ReadonlyMap<string, Result<RunStatus>>,
): boolean {
  // The runs whose wait has passed, named by their key: a new set of runs waits again.
  const [lateFor, setLateFor] = useState<string | null>(null);
  const key = runs.map(runKey).join(",");
  useEffect(() => {
    const timer = setTimeout(() => {
      setLateFor(key);
    }, STATUS_GRACE_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [key]);
  return lateFor === key || runs.every((run) => statuses.has(runKey(run)));
}

/**
 * The groups Home lists first, in this order: a run going; one waiting on a person's decision;
 * one halted, owing a halt, or that appears to have stopped, which a person should look at.
 */
export const ATTENTION_FIRST: readonly (readonly Phase[])[] = [
  ["going"],
  ["waiting-person"],
  ["halted", "halt-owed", "stopped"],
];

/**
 * Home's order: runs going, then runs waiting on a person's decision, then runs halted or that
 * appear stopped, newest start first within each; then every other run newest start first
 * (``orderRuns``). A run whose status was not read, or was refused, is among the rest.
 */
export function homeOrder<T extends RunListing>(
  runs: readonly T[],
  phases: ReadonlyMap<string, Phase>,
): readonly T[] {
  const rank = (run: T) => {
    const phase = phases.get(runKey(run));
    const at =
      phase === undefined ? -1 : ATTENTION_FIRST.findIndex((group) => group.includes(phase));
    return at < 0 ? ATTENTION_FIRST.length : at;
  };
  // The sort is stable, so each group keeps the newest-first order.
  return [...orderRuns(runs)].sort((a, b) => rank(a) - rank(b));
}

/**
 * The runs Home reads in full, in Home's order as far as the statuses read so far tell it: every
 * readable run when the person asked for all or there are no more than ``FIRST_RUNS``; else the
 * first ``FIRST_RUNS``. A run whose status answers later moves up, when it needs attention, as the
 * order is taken again.
 */
export function readTargets(
  runs: readonly RunListing[],
  all: boolean,
  phases: ReadonlyMap<string, Phase>,
): readonly RunListing[] {
  const readable = runs.filter((r) => r.error === null);
  const ordered = homeOrder(readable, phases);
  return all || readable.length <= FIRST_RUNS ? ordered : ordered.slice(0, FIRST_RUNS);
}

/** The phase of each of ``runs`` whose status has answered, by run key. */
export function phasesOf(
  runs: readonly RunListing[],
  statuses: ReadonlyMap<string, Result<RunStatus>>,
): ReadonlyMap<string, Phase> {
  const phases = new Map<string, Phase>();
  for (const run of runs) {
    const status = statuses.get(runKey(run));
    if (status?.ok === true) phases.set(runKey(run), phaseOf(status.value));
  }
  return phases;
}

/**
 * Where each of ``runs`` stands, by run key, as each answers: only its status route, read again
 * while Home is shown, so a run that starts going, ends or stops is seen without a reload. At
 * most ``STATUS_POOL`` are asked at once, each given up after ``STATUS_TIMEOUT_MS``.
 */
/**
 * A status kept from an earlier read because the read after it failed: when the kept answer was
 * read (the browser's clock, as an ISO time), and why the later read failed.
 */
export interface Stale {
  readonly since: string;
  readonly error: string;
}

/** What Home knows of where its runs stand. */
export interface Statuses {
  /**
   * Each run's latest good answer, by run key; its refusal only while no answer has been good,
   * so one failed re-read never turns a run going into one not read.
   */
  readonly found: ReadonlyMap<string, Result<RunStatus>>;
  /** The runs whose answer is kept from an earlier read because a later one failed. */
  readonly stale: ReadonlyMap<string, Stale>;
  /** How many of the minute's re-reads have ended: Home moves its rows only when this changes. */
  readonly minutes: number;
}

/** No phase yet: the run list's own order. */
const NO_PHASES: ReadonlyMap<string, Phase> = new Map();

/**
 * The phases Home orders its rows by: none (the run list's order) until ``settled``; then the
 * phases as they stand at that moment, held; then taken again each time a minute's re-read ends
 * (``minutes`` changes), and at no other time. So a row a person aims at does not move under the
 * pointer as statuses answer in the first seconds, or as a re-read on showing the page answers.
 * The order held is for one set of runs (``runs``, their keys): another set, such as the run list
 * read after Home's first render with none, waits to settle again.
 */
export function useOrderPhases(
  phases: ReadonlyMap<string, Phase>,
  settled: boolean,
  minutes: number,
  runs: string,
): ReadonlyMap<string, Phase> {
  const [held, setHeld] = useState<{
    readonly phases: ReadonlyMap<string, Phase>;
    readonly minutes: number;
    readonly runs: string;
  } | null>(null);
  const mine = held?.runs === runs ? held : null;
  // Taken while rendering, so the first settled render is already in the settled order.
  if (settled && (mine === null || mine.minutes !== minutes)) {
    setHeld({ phases, minutes, runs });
    return phases;
  }
  return mine?.phases ?? NO_PHASES;
}

interface Known {
  readonly found: ReadonlyMap<string, Result<RunStatus>>;
  /** When each run's kept good answer was read. */
  readonly at: ReadonlyMap<string, string>;
  readonly stale: ReadonlyMap<string, Stale>;
  readonly minutes: number;
}

const NOTHING_KNOWN: Known = { found: new Map(), at: new Map(), stale: new Map(), minutes: 0 };

/** ``known`` with ``status`` the answer for ``k``: a failure keeps an earlier good answer. */
function withAnswer(known: Known, k: string, status: Result<RunStatus>, now: string): Known {
  const before = known.found.get(k);
  const since = known.at.get(k);
  if (!status.ok && before?.ok === true && since !== undefined)
    return {
      ...known,
      stale: new Map(known.stale).set(k, { since, error: status.refusal.error }),
    };
  const stale = new Map(known.stale);
  stale.delete(k);
  const at = new Map(known.at);
  if (status.ok) at.set(k, now);
  else at.delete(k);
  return { ...known, found: new Map(known.found).set(k, status), at, stale };
}

/**
 * Where each of ``runs`` stands, by run key, as each answers: only its status route, read again
 * while Home is shown, so a run that starts going, ends or stops is seen without a reload. Every
 * round (the first, the minute's, one on showing the page again) feeds one queue: at most
 * ``STATUS_POOL`` are asked at once however the rounds overlap, a run asked or waiting its turn is
 * never asked twice, and each is given up after ``STATUS_TIMEOUT_MS``. A read that fails keeps
 * the run's last good answer, marked as stale since it was read.
 */
export function useStatuses(runs: readonly RunListing[]): Statuses {
  const [known, setKnown] = useState<Known>(NOTHING_KNOWN);
  const key = runs.map(runKey).join(",");
  useEffect(() => {
    let live = true;
    // The runs whose status is asked or waiting its turn: a re-read never asks one twice.
    const busy = new Set<string>();
    const queue: { readonly run: RunListing; readonly round: { left: number } }[] = [];
    let asking = 0;
    const ask = async (run: RunListing): Promise<Result<RunStatus>> => {
      try {
        return await getJson(`${runBase(run)}/status`, runStatus, {
          timeoutMs: STATUS_TIMEOUT_MS,
        });
      } catch (error) {
        const why = error instanceof Error ? error.message : String(error);
        return { ok: false, refusal: { status: 0, error: why, context: {} } };
      }
    };
    // The rounds begun by the minute's interval: when one ends, Home may move its rows.
    const minuteRounds = new WeakSet<{ left: number }>();
    const pump = () => {
      while (asking < STATUS_POOL) {
        const next = queue.shift();
        if (next === undefined) return;
        asking += 1;
        const k = runKey(next.run);
        void ask(next.run).then((status) => {
          asking -= 1;
          busy.delete(k);
          next.round.left -= 1;
          const ended = next.round.left === 0 && minuteRounds.has(next.round);
          if (live)
            setKnown((now) => {
              const answered = withAnswer(now, k, status, new Date().toISOString());
              return ended ? { ...answered, minutes: answered.minutes + 1 } : answered;
            });
          pump();
        });
      }
    };
    const read = (round: { left: number }) => {
      const due = runs.filter((run) => !busy.has(runKey(run)));
      round.left = due.length;
      for (const run of due) {
        busy.add(runKey(run));
        queue.push({ run, round });
      }
      pump();
    };
    read({ left: 0 });
    const stop = whileShown((why) => {
      const round = { left: 0 };
      if (why === "interval") minuteRounds.add(round);
      read(round);
      // A minute's round with nothing left to ask (every run still asked) ends at once.
      if (round.left === 0 && why === "interval" && live)
        setKnown((now) => ({ ...now, minutes: now.minutes + 1 }));
    }, STATUS_EVERY_MS);
    return () => {
      live = false;
      stop();
    };
    // The key names the runs; the list is rebuilt every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return useMemo(
    () => ({ found: known.found, stale: known.stale, minutes: known.minutes }),
    [known],
  );
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
