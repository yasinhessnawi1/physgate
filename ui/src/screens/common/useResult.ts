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
