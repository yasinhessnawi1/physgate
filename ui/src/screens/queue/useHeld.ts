import { useEffect, useState } from "react";

import type { Result } from "../../api/client";

/** What a held read shows, and whether its latest read failed while an earlier one stands. */
export interface Held<T> {
  readonly result: Result<T> | null;
  /** The latest read failed; ``result`` is the last one that worked. */
  readonly failedAgain: boolean;
}

/**
 * A request read again under a new ``key`` within one ``scope``, its last answer held while the
 * next is read: a screen that reads a record again while it is open never blanks, and what a
 * person is typing beside it stays. A read that fails after one that worked keeps the one that
 * worked, and says so in ``failedAgain``; a first read that fails is shown as failed. A new scope
 * (another run) starts empty, as ``useResult`` does.
 */
export function useHeldResult<T>(
  load: (() => Promise<Result<T>>) | null,
  scope: string,
  key: string,
): Held<T> {
  const [state, setState] = useState<{
    scope: string;
    result: Result<T>;
    failedAgain: boolean;
  } | null>(null);
  useEffect(() => {
    if (load === null) return;
    let live = true;
    void load().then((result) => {
      if (!live) return;
      setState((held) =>
        !result.ok && held !== null && held.scope === scope && held.result.ok
          ? { ...held, failedAgain: true }
          : { scope, result, failedAgain: false },
      );
    });
    return () => {
      live = false;
    };
    // The scope and key name the request; the loader is rebuilt every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope, key]);
  return state?.scope === scope
    ? { result: state.result, failedAgain: state.failedAgain }
    : { result: null, failedAgain: false };
}
