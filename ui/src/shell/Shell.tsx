import {
  type ComponentType,
  type CSSProperties,
  type ReactNode,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { actToken, pageOperator } from "../api/client";
import { Button } from "../design/components/actions/Button";
import { Kbd } from "../design/components/actions/Kbd";
import { Avatar } from "../design/components/actor/Avatar";
import { SourceChip } from "../design/components/data/SourceChip";
import { Icon } from "../design/components/icons/Icon";
import { InProgressBadge } from "../design/components/status/InProgressBadge";
import { EmptyState, LoadingState } from "../design/components/status/States";
import { OsLayerBadge } from "../design/components/system/OsLayerBadge";
import { GateModeBadge } from "../design/components/verdict/GateMode";
import markUrl from "../design/brand/mark.svg?url";
import type { ViewDef } from "../views/registry";
import { GROUPS, groupById } from "./groups";
import type { Header } from "./header";
import { InspectorContext } from "./inspector";
import { Notifications } from "./notifications";
import { Palette, type PaletteEntry, PaletteProvider, usePaletteRegistry } from "./palette";
import {
  DENSITY_KEY,
  type DensityChoice,
  densityChoice,
  nextTheme,
  prefersDark,
  readStored,
  resolvedTheme,
  THEME_KEY,
  type ThemeChoice,
  themeChoice,
  themeOverride,
  writeStored,
} from "./prefs";
import { hrefFor, parseHash, type Route } from "./route";
import { chordTarget, notAShortcut } from "./shortcuts";

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
 * The two-key shortcuts. The listener is added once, for the shell's life: re-adding it whenever
 * the route changed lost a first key pressed across that change. The current query is read
 * through a ref, so a chord keeps the run that is chosen when it completes.
 */
function useShortcuts(query: URLSearchParams) {
  const current = useRef(query);
  useEffect(() => {
    current.current = query;
  }, [query]);
  useEffect(() => {
    let first: { key: string; at: number } | null = null;
    const onKey = (event: KeyboardEvent) => {
      if (notAShortcut(event)) return;
      const href = chordTarget(first, event.key, event.timeStamp, current.current);
      if (href !== null) {
        first = null;
        event.preventDefault();
        window.location.hash = href.slice(1);
        return;
      }
      first = event.key === "g" ? { key: "g", at: event.timeStamp } : null;
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, []);
}

/** The display choices, stored per viewer, following the system's theme until one is chosen. */
function useDisplay() {
  const override = themeOverride(window.location.search);
  const [theme, setTheme] = useState<ThemeChoice>(
    () => override ?? themeChoice(readStored(THEME_KEY)),
  );
  const [density, setDensity] = useState<DensityChoice>(() =>
    densityChoice(readStored(DENSITY_KEY)),
  );
  const [dark, setDark] = useState(prefersDark);
  useEffect(() => {
    let query: MediaQueryList | null = null;
    try {
      query = window.matchMedia("(prefers-color-scheme: dark)");
    } catch {
      return;
    }
    const onChange = (event: MediaQueryListEvent) => {
      setDark(event.matches);
    };
    query.addEventListener("change", onChange);
    return () => {
      query.removeEventListener("change", onChange);
    };
  }, []);
  const drawn = resolvedTheme(theme, dark);
  useEffect(() => {
    document.documentElement.dataset.theme = drawn;
  }, [drawn]);
  useEffect(() => {
    document.documentElement.dataset.density = density;
  }, [density]);
  return {
    theme,
    drawn,
    density,
    cycleTheme: () => {
      const next = nextTheme(theme);
      setTheme(next);
      if (override === null) writeStored(THEME_KEY, next);
    },
    toggleDensity: () => {
      const next = density === "compact" ? "comfortable" : "compact";
      setDensity(next);
      writeStored(DENSITY_KEY, next);
    },
  };
}

const THEME_WORDS: Readonly<Record<ThemeChoice, string>> = {
  light: "Light",
  dark: "Dark",
  system: "System",
};

/** The pages the shell shows outside the navigation: the component gallery, and About. */
export type Pages = Readonly<Record<"gallery" | "about", ComponentType>>;

const HOME_GROUP = GROUPS[0];

/**
 * The app shell: the navigation, built from the registry and grouped as the design draws it; the
 * top bar (where you are, the run's chip, search, notifications, theme, density, the operator);
 * the content; the inspector region; and the collaborator's dock, which is a placeholder in this
 * build. It renders whatever views it is given and imports none.
 */
export function Shell({
  views,
  pages,
}: {
  readonly views: readonly ViewDef[];
  readonly pages?: Pages;
}) {
  const route = useRoute();
  useShortcuts(route.query);
  const display = useDisplay();
  const registry = usePaletteRegistry();
  const [navCollapsed, setNavCollapsed] = useState(false);
  const [dockOpen, setDockOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [noticesOpen, setNoticesOpen] = useState(false);
  const [inspectorElement, setInspectorElement] = useState<HTMLElement | null>(null);
  const [inspectorShown, setInspectorShown] = useState(false);
  // The inspector closed by the person, for the view and selection it was closed on: a new view
  // or a new selection opens it again.
  const [closedAt, setClosedAt] = useState<string | null>(null);
  const inspector = useMemo(
    () => ({ element: inspectorElement, setShown: setInspectorShown }),
    [inspectorElement],
  );

  const page = route.area === "gallery" || route.area === "about" ? route.area : null;
  const inArea = views.filter((view) => view.area === route.area);
  const view =
    page !== null
      ? undefined
      : route.view === null
        ? route.area === "home"
          ? inArea[0]
          : undefined
        : inArea.find((v) => v.slug === route.view);
  // A view reports its header for itself; a report is kept only while that view is shown, so
  // moving to another view never shows the last one's source or gate mode.
  const viewKey = `${route.area}/${view?.slug ?? ""}`;
  const [reported, setReported] = useState<{ key: string; header: Header } | null>(null);
  const header: Header | null =
    reported?.key === viewKey ? reported.header : view === undefined ? null : { title: view.title };
  const setHeader = useCallback(
    (next: Header) => {
      setReported({ key: viewKey, header: next });
    },
    [viewKey],
  );
  const selectionKey = `${viewKey}?${route.query.toString()}`;
  const inspectorClosed = closedAt === selectionKey;

  // ⌘K or Ctrl+K opens the palette, ⌘J or Ctrl+J the dock. Escape closes what is open, in order:
  // a dialog first (it handles its own Escape), then the palette (a dialog too), then
  // notifications.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const modal = document.querySelector("dialog[open]") !== null;
      if ((event.metaKey || event.ctrlKey) && !event.altKey) {
        const key = event.key.toLowerCase();
        if (key === "k" && !modal) {
          event.preventDefault();
          setPaletteOpen(true);
        } else if (key === "j" && !modal) {
          event.preventDefault();
          setDockOpen((o) => !o);
        }
        return;
      }
      if (event.key === "Escape" && !modal) setNoticesOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  const byGroup = [...views].sort(
    (a, b) => GROUPS.findIndex((g) => g.id === a.group) - GROUPS.findIndex((g) => g.id === b.group),
  );
  const goTo: PaletteEntry[] = byGroup.map((v) => {
    const run = route.query.get("run");
    return {
      id: `go-${v.area}-${v.slug}`,
      section: "Go to",
      label: v.title,
      run: () => {
        window.location.hash = hrefFor(
          v.area,
          v.slug,
          new URLSearchParams(run === null ? undefined : { run }),
        ).slice(1);
      },
    };
  });

  const operator = pageOperator();
  const readOnly = actToken() === null;
  const group = view === undefined ? undefined : groupById(view.group);
  const title =
    page === "gallery"
      ? "Component gallery"
      : page === "about"
        ? "About physgate"
        : (header?.title ?? "Nothing here");
  // Only the gallery opens the inspector region for now; today's views keep their own inspectors.
  const hasInspector = page === "gallery";
  const inspectorOpen = hasInspector && inspectorShown && !inspectorClosed;
  const Page = page === null ? undefined : pages?.[page];

  let content: ReactNode;
  if (Page !== undefined)
    content = (
      <Suspense fallback={<LoadingState reading="the page" />}>
        <Page />
      </Suspense>
    );
  else if (view === undefined)
    content = (
      <EmptyState title="Nothing is registered at this address" icon="search">
        This build has no view here. Every view it has is listed in the navigation.
      </EmptyState>
    );
  else
    content = (
      <Suspense fallback={<LoadingState reading="the view" />}>
        <view.component setHeader={setHeader} query={route.query} />
      </Suspense>
    );

  return (
    <PaletteProvider registry={registry}>
      <InspectorContext.Provider value={inspector}>
        <div
          className="pg-shell"
          data-nav={navCollapsed ? "collapsed" : "expanded"}
          data-dock={dockOpen ? "open" : "rail"}
          data-inspector={inspectorOpen ? "open" : "closed"}
        >
          <nav className="pg-nav" aria-label="Areas">
            <div className="pg-brand">
              <span className="pg-brand-mark" aria-hidden="true">
                <span
                  className="pg-icon pg-mark"
                  style={{ "--pg-icon": `url("${markUrl}")` } as CSSProperties}
                />
              </span>
              <span className="pg-brand-words">
                <span className="pg-brand-name">physgate</span>
                <span className="pg-brand-role">Operator</span>
              </span>
              <Button
                variant="ghost"
                size="sm"
                icon={navCollapsed ? "panel-right" : "panel-right-close"}
                title={navCollapsed ? "Expand the navigation" : "Collapse the navigation"}
                pressed={navCollapsed}
                onClick={() => {
                  setNavCollapsed((c) => !c);
                }}
              />
            </div>
            {GROUPS.map((g) => {
              const listed = views.filter((v) => v.group === g.id);
              if (listed.length === 0) return null;
              return (
                <section key={g.id} className="pg-nav-group" aria-label={g.name}>
                  <h2 className="pg-nav-heading">{g.name}</h2>
                  <ul className="pg-nav-items">
                    {listed.map((v) => (
                      <li key={`${v.area}/${v.slug}`}>
                        <a
                          className={v === view ? "pg-nav-link pg-nav-link-on" : "pg-nav-link"}
                          aria-current={v === view ? "page" : undefined}
                          href={hrefFor(v.area, v.slug)}
                          title={v.title}
                        >
                          <Icon name={v.icon} size={16} />
                          <span className="pg-nav-word">{v.title}</span>
                        </a>
                      </li>
                    ))}
                  </ul>
                </section>
              );
            })}
            <div className="pg-nav-foot">
              <a className="pg-nav-link" href="#/about" title="About physgate and its licences">
                <Icon name="book-open" size={16} />
                <span className="pg-nav-word">About and licences</span>
              </a>
              <p className="pg-nav-note">
                Local only · <span className="mono">{window.location.host}</span>
              </p>
            </div>
          </nav>
          <div className="pg-main">
            <header className="pg-topbar">
              <nav className="pg-breadcrumb" aria-label="Where you are">
                <ol>
                  <li className="pg-crumb-group">
                    {(group ?? (page === null ? undefined : HOME_GROUP))?.name ?? "physgate"}
                  </li>
                  <li aria-current="page">
                    <h1 className="pg-page-title">{title}</h1>
                  </li>
                </ol>
              </nav>
              {header !== null &&
                (header.source !== undefined ||
                  header.gateMode !== undefined ||
                  header.osLayer !== undefined ||
                  header.inProgress === true) && (
                  <div className="pg-run-chip" role="group" aria-label="The run shown">
                    {header.source !== undefined && (
                      <SourceChip id={header.source.id} commit={header.source.commit} compact />
                    )}
                    {header.gateMode !== undefined && <GateModeBadge mode={header.gateMode} />}
                    {header.inProgress === true && <InProgressBadge />}
                    {header.osLayer !== undefined && <OsLayerBadge layer={header.osLayer} />}
                  </div>
                )}
              <div className="pg-topbar-tools">
                <button
                  type="button"
                  className="pg-btn pg-btn-browse pg-search"
                  aria-haspopup="dialog"
                  onClick={() => {
                    setPaletteOpen(true);
                  }}
                >
                  <Icon name="search" />
                  <span className="pg-search-label">Search</span>
                  <Kbd>⌘K</Kbd>
                </button>
                <span className="pg-notices-anchor">
                  <Button
                    variant="ghost"
                    icon="bell"
                    title="Notifications"
                    pressed={noticesOpen}
                    onClick={() => {
                      setNoticesOpen((o) => !o);
                    }}
                  />
                  {noticesOpen && (
                    <Notifications
                      onClose={() => {
                        setNoticesOpen(false);
                      }}
                    />
                  )}
                </span>
                <Button
                  variant="ghost"
                  icon={display.drawn === "dark" ? "moon" : "sun"}
                  title={`Theme: ${THEME_WORDS[display.theme]}. Change it`}
                  onClick={display.cycleTheme}
                />
                <Button
                  variant="ghost"
                  icon="table"
                  title={`Density: ${display.density}. Change it`}
                  pressed={display.density === "comfortable"}
                  onClick={display.toggleDensity}
                />
                {readOnly && (
                  <span
                    className="pg-status pg-read-only"
                    title="This page was opened without the operator's address"
                  >
                    <Icon name="eye" size={12} />
                    Read only
                  </span>
                )}
                {operator !== null && <Avatar name={operator} size="md" />}
              </div>
            </header>
            <div className="pg-body">
              <main className="pg-content">{content}</main>
              {hasInspector && (
                <aside
                  className="pg-inspector-region"
                  aria-label="Inspector"
                  hidden={!inspectorOpen}
                >
                  <div className="pg-inspector-close">
                    <Button
                      variant="ghost"
                      size="sm"
                      icon="x"
                      title="Close the inspector"
                      onClick={() => {
                        setClosedAt(selectionKey);
                      }}
                    />
                  </div>
                  <div ref={setInspectorElement} className="pg-inspector-slot" />
                </aside>
              )}
            </div>
          </div>
          <aside className="pg-dock" aria-label="Collaborator">
            <div className="pg-dock-rail">
              <Button
                variant="ghost"
                icon="messages-square"
                title="Collaborator (⌘J)"
                pressed={dockOpen}
                onClick={() => {
                  setDockOpen((o) => !o);
                }}
              />
            </div>
            {dockOpen && (
              <div className="pg-dock-panel" id="pg-dock-panel">
                <EmptyState
                  title="The collaborator is not available in this build."
                  icon="messages-square"
                />
              </div>
            )}
          </aside>
          <Palette
            open={paletteOpen}
            goTo={goTo}
            onClose={() => {
              setPaletteOpen(false);
            }}
          />
        </div>
      </InspectorContext.Provider>
    </PaletteProvider>
  );
}
