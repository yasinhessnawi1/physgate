import { useEffect, useState } from "react";

import type { Result } from "../../api/client";

/**
 * A request's result, keyed by what was asked. ``null`` while it is read; a new key starts a new
 * read and never shows the old key's answer. A ``null`` loader asks for nothing.
 */
export function useResult<T>(
  load: (() => Promise<Result<T>>) | null,
  key: string,
): Result<T> | null {
  const [state, setState] = useState<{ key: string; result: Result<T> } | null>(null);
  useEffect(() => {
    if (load === null) return;
    let live = true;
    void load().then((result) => {
      if (live) setState({ key, result });
    });
    return () => {
      live = false;
    };
    // The key names the request; the loader is rebuilt every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return state?.key === key ? state.result : null;
}

/**
 * A request read again under a new ``key`` within one ``scope``, its last answer held while the
 * next is read: a screen that reads a record again while it is open never blanks, and what a
 * person is typing beside it stays. A new scope (another run) starts empty, as ``useResult`` does.
 */
export function useHeldResult<T>(
  load: (() => Promise<Result<T>>) | null,
  scope: string,
  key: string,
): Result<T> | null {
  const [state, setState] = useState<{
    scope: string;
    key: string;
    result: Result<T>;
  } | null>(null);
  useEffect(() => {
    if (load === null) return;
    let live = true;
    void load().then((result) => {
      if (live) setState({ scope, key, result });
    });
    return () => {
      live = false;
    };
    // The scope and key name the request; the loader is rebuilt every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope, key]);
  return state?.scope === scope ? state.result : null;
}
