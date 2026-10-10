/** Where the app is: an area, optionally a view in it, and the view's query. From the hash. */
export interface Route {
  readonly area: string;
  readonly view: string | null;
  readonly query: URLSearchParams;
}

/** Parse ``#/<area>/<view>?<query>``. Anything else is Home. */
export function parseHash(hash: string): Route {
  const [path = "", search = ""] = hash.replace(/^#/, "").split("?", 2);
  const parts = path.split("/").filter((part) => part !== "");
  return { area: parts[0] ?? "home", view: parts[1] ?? null, query: new URLSearchParams(search) };
}

export function hrefFor(area: string, view: string | null, query?: URLSearchParams): string {
  const search = query !== undefined && query.size > 0 ? `?${query.toString()}` : "";
  return `#/${area}${view === null ? "" : `/${view}`}${search}`;
}
