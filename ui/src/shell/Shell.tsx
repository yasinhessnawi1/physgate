import { Suspense, useCallback, useEffect, useState } from "react";

import { GateModeBadge } from "../design/components/GateMode";
import { InProgressBadge } from "../design/components/Figure";
import { SourceChip } from "../design/components/SourceChip";
import { EmptyState, LoadingState } from "../design/components/States";
import type { ViewDef } from "../views/registry";
import { type Area, AREAS, areaById } from "./areas";

const HOME: Area = { id: "home", number: "0", name: "Home" };
import type { Header } from "./header";
import { hrefFor, parseHash, type Route } from "./route";

function useRoute(): Route {
  const [route, setRoute] = useState(() => parseHash(window.location.hash));
  useEffect(() => {
    const onChange = () => {
      setRoute(parseHash(window.location.hash));
    };
    window.addEventListener("hashchange", onChange);
    return () => {
      window.removeEventListener("hashchange", onChange);
    };
  }, []);
  return route;
}

/**
 * The app shell: a sidebar grouped as Home and the four focus areas, a top bar with the area,
 * the title and the record the page's figures come from, and the content beside them. Under
 * 760 px the sidebar stacks above the content. It renders whatever views it is given.
 */
export function Shell({ views }: { views: readonly ViewDef[] }) {
  const route = useRoute();
  const area = areaById(route.area) ?? HOME;
  const inArea = views.filter((view) => view.area === area.id);
  const view =
    route.view === null
      ? area.id === "home"
        ? inArea[0]
        : undefined
      : inArea.find((v) => v.slug === route.view);
  // A view reports its header for itself; a report is kept only while that view is shown, so
  // moving to another view never shows the last one's source or gate mode.
  const viewKey = `${area.id}/${view?.slug ?? ""}`;
  const [reported, setReported] = useState<{ key: string; header: Header } | null>(null);
  const header: Header =
    reported?.key === viewKey ? reported.header : { title: view?.title ?? area.name };
  const setHeader = useCallback(
    (next: Header) => {
      setReported({ key: viewKey, header: next });
    },
    [viewKey],
  );
  return (
    <div className="shell">
      <nav className="sidebar" aria-label="Areas">
        <div className="sidebar-brand">
          <span className="sidebar-name">physgate</span>
          <span className="sidebar-role">Operator</span>
        </div>
        {AREAS.map((a) => (
          <section key={a.id} className="nav-area" aria-label={a.name}>
            <a className="nav-area-title" href={hrefFor(a.id, null)}>
              <span className="mono">{a.number}</span> · {a.name}
            </a>
            <ul className="nav-items">
              {views
                .filter((v) => v.area === a.id)
                .map((v) => (
                  <li key={v.slug}>
                    <a
                      className={v === view ? "nav-link nav-link-on" : "nav-link"}
                      aria-current={v === view ? "page" : undefined}
                      href={hrefFor(a.id, v.slug)}
                    >
                      {v.title}
                    </a>
                  </li>
                ))}
            </ul>
          </section>
        ))}
        <p className="sidebar-foot">
          Local only · <span className="mono">{window.location.host}</span>
          <br />
          No outbound requests · held-out tier never served
        </p>
      </nav>
      <div className="main">
        <header className="topbar">
          <div className="topbar-titles">
            <span className="topbar-area">
              <span className="mono">{area.number}</span> · {area.name}
            </span>
            <h1 className="page-title">{header.title}</h1>
          </div>
          <div className="topbar-badges">
            {header.source !== undefined && <SourceChip source={header.source} />}
            {header.gateMode !== undefined && <GateModeBadge mode={header.gateMode} />}
            {header.inProgress === true && <InProgressBadge />}
          </div>
        </header>
        <main className="content">
          {view === undefined ? (
            <EmptyState title={inArea.length === 0 ? "No views in this area yet" : "Choose a view"}>
              {inArea.length === 0
                ? "This area's views arrive with later work. Nothing here reads any record yet."
                : "Pick one from the sidebar."}
            </EmptyState>
          ) : (
            <Suspense fallback={<LoadingState reading="the view" />}>
              <view.component setHeader={setHeader} query={route.query} />
            </Suspense>
          )}
        </main>
      </div>
    </div>
  );
}
