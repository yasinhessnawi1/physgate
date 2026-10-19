/**
 * Reading one route for a screen: the record or the server's refusal, never part of either, with
 * the route it came from, and a way to read it again. A new path starts a new read and never
 * shows the old path's answer.
 */
import { useState } from "react";

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
