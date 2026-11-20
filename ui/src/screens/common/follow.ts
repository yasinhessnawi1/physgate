/**
 * A run's log, followed while the run is going: read once from its first line, then asked again
 * from the last line held every few seconds while the page is shown, and at once when it is shown
 * again (a tab brought back, a window focused). A run that is not going is read once and never
 * asked again; a hidden page asks nothing. Each answer is joined to the lines held after its
 * overlap (``follow``), so a line is never shown twice or left out, and a log that is not the one
 * held is read again from its first line. A read that fails keeps the lines held and says so.
 */
import { useEffect, useRef, useState } from "react";

import { getJson, type ReadOptions, type Result } from "../../api/client";
import type { RunEvent } from "../../api/events";
import { type Followed, follow, logTail } from "../../api/tail";
import { whileShown } from "./read";

/** How often a going run's log is asked again while its page is shown, in milliseconds. */
export const FOLLOW_EVERY_MS = 5_000;

export interface FollowedRead {
  /** ``null`` while the first read is made. */
  readonly result: Result<readonly RunEvent[]> | null;
  /** The route the log is first read from, for the details of a refusal. */
  readonly route: string | null;
  /** Read the log again from its first line. */
  readonly again: () => void;
  /** The latest read failed; ``result`` is the last one that worked. */
  readonly failedAgain: boolean;
}

interface Shown {
  readonly path: string;
  readonly result: Result<readonly RunEvent[]>;
  readonly failedAgain: boolean;
}

/** The log of the run whose routes start with ``base``, followed while ``going``. */
export function useFollowedLog(
  base: string | null,
  going: boolean,
  everyMs: number = FOLLOW_EVERY_MS,
): FollowedRead {
  const path = base === null ? null : `${base}/events/from`;
  const [n, setN] = useState(0);
  const [shown, setShown] = useState<Shown | null>(null);
  // The lines held, by the path they were read from and the read-again count they belong to.
  const held = useRef<{ path: string; n: number; followed: Followed | null } | null>(null);

  useEffect(() => {
    if (path === null) return;
    let live = true;
    let asking = false;
    const fresh = held.current?.path !== path || held.current.n !== n;
    if (fresh) held.current = { path, n, followed: null };
    // A read on a tick is given up before the next tick is due, so reads never pile up.
    const onTick: ReadOptions = { timeoutMs: Math.max(everyMs - 1_000, 1_000) };

    const read = (options: ReadOptions = {}) => {
      if (asking) return;
      asking = true;
      const followed = held.current?.followed ?? null;
      const from = followed === null ? 0 : Math.max(followed.raw.length - 1, 0);
      void getJson(`${path}/${String(from)}`, logTail, options).then((answer) => {
        asking = false;
        if (!live) return;
        if (!answer.ok) {
          setShown((was) =>
            was !== null && was.path === path && was.result.ok
              ? { ...was, failedAgain: true }
              : { path, result: answer, failedAgain: false },
          );
          return;
        }
        let step;
        try {
          step = follow(followed, answer.value);
        } catch (error) {
          const message = error instanceof Error ? error.message : String(error);
          const refused = {
            ok: false as const,
            refusal: { status: 0, error: message, context: {} },
          };
          setShown((was) =>
            was !== null && was.path === path && was.result.ok
              ? { ...was, failedAgain: true }
              : { path, result: refused, failedAgain: false },
          );
          return;
        }
        if (step.kind === "again") {
          // Not the log held: read it again from its first line, showing the old until it comes.
          held.current = { path, n, followed: null };
          read(options);
          return;
        }
        const grown = step.followed;
        if (grown === followed) {
          // Nothing new: the lines on screen stand, and no longer say a read failed.
          setShown((was) =>
            was !== null && was.path === path && was.failedAgain
              ? { ...was, failedAgain: false }
              : was,
          );
          return;
        }
        held.current = { path, n, followed: grown };
        setShown({ path, result: { ok: true, value: grown.events }, failedAgain: false });
      });
    };

    // The first read of a path is made at once; after it, only a going run's shown page asks,
    // on the interval and when it is shown again.
    if (fresh) read();
    if (!going) {
      return () => {
        live = false;
      };
    }
    const stop = whileShown(() => {
      read(onTick);
    }, everyMs);
    return () => {
      live = false;
      stop();
    };
  }, [path, n, going, everyMs]);

  const current = shown?.path === path ? shown : null;
  return {
    result: current?.result ?? null,
    route: path === null ? null : `${path}/0`,
    again: () => {
      setN((v) => v + 1);
    },
    failedAgain: current?.failedAgain ?? false,
  };
}
