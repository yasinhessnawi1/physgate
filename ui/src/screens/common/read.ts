/**
 * Reading one route for a screen: the record or the server's refusal, never part of either, with
 * the route it came from, and a way to read it again. A new path starts a new read and never
 * shows the old path's answer. Where a run stands is read live (``useLiveJson``): again on an
 * interval while the page is shown, and when it is shown again.
 */
import { useEffect, useState } from "react";

import { getJson, getLines, type Result } from "../../api/client";
import { useResult } from "./useResult";

export interface Read<T> {
  /** ``null`` while it is read. */
  readonly result: Result<T> | null;
  /** The route asked, for the details of a refusal. */
  readonly route: string | null;
  readonly again: () => void;
}

function useAgain(): [number, () => void] {
  const [n, setN] = useState(0);
  return [
    n,
    () => {
      setN((v) => v + 1);
    },
  ];
}

/** One JSON record from ``path``, held to ``guard``; nothing is asked while ``path`` is null. */
export function useJson<T>(path: string | null, guard: (value: unknown) => T): Read<T> {
  const [n, again] = useAgain();
  const result = useResult(
    path === null ? null : () => getJson(path, guard),
    `${String(path)}#${String(n)}`,
  );
  return { result, route: path, again };
}

/** A JSON-lines record from ``path``, every line held to ``guard``. */
export function useLines<T>(path: string | null, guard: (value: unknown) => T): Read<readonly T[]> {
  const [n, again] = useAgain();
  const result = useResult(
    path === null ? null : () => getLines(path, guard),
    `${String(path)}#${String(n)}`,
  );
  return { result, route: path, again };
}

/** How often a page re-reads where its run stands while it is shown, in milliseconds. */
export const STATUS_EVERY_MS = 60_000;

/** Why a page reads again: its interval came round, or it was shown again. */
export type Again = "interval" | "shown";

/**
 * Call ``read`` every ``everyMs`` while the page is shown, and at once when it is shown again
 * (its tab brought back, its window focused), telling it which. Returns what stops it.
 */
export function whileShown(read: (why: Again) => void, everyMs: number): () => void {
  const shown = () => document.visibilityState !== "hidden";
  const timer = setInterval(() => {
    if (shown()) read("interval");
  }, everyMs);
  const again = () => {
    if (shown()) read("shown");
  };
  document.addEventListener("visibilitychange", again);
  window.addEventListener("focus", again);
  return () => {
    clearInterval(timer);
    document.removeEventListener("visibilitychange", again);
    window.removeEventListener("focus", again);
  };
}

/**
 * One JSON record from ``path``, read again every ``everyMs`` while the page is shown and when it
 * is shown again. The last answer stays until a newer one arrives; an answer to an earlier read
 * that arrives after a later one is dropped.
 */
export function useLiveJson<T>(
  path: string | null,
  guard: (value: unknown) => T,
  everyMs: number = STATUS_EVERY_MS,
): Read<T> {
  const [n, again] = useAgain();
  const [state, setState] = useState<{ path: string; result: Result<T> } | null>(null);
  useEffect(() => {
    if (path === null) return;
    let live = true;
    let asked = 0;
    let shown = 0;
    const read = () => {
      const mine = ++asked;
      void getJson(path, guard).then((result) => {
        if (!live || mine < shown) return;
        shown = mine;
        setState({ path, result });
      });
    };
    read();
    const stop = whileShown(read, everyMs);
    return () => {
      live = false;
      stop();
    };
    // The path and the count name the request; the guard is rebuilt every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, n, everyMs]);
  return { result: state?.path === path ? state.result : null, route: path, again };
}
