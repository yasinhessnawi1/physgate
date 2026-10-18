// @vitest-environment happy-dom
import { act, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { OsLayer } from "../design/components/system/OsLayerBadge";
import { VIEWS, type ViewDef } from "../views/registry";
import { AREA_IDS } from "./areas";
import { GROUPS } from "./groups";
import type { Header, ViewProps } from "./header";
import { parseHash } from "./route";
import { Shell } from "./Shell";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  document.body.innerHTML = "";
  document.head.innerHTML = "";
  window.location.hash = "";
  vi.restoreAllMocks();
});

function mount(views: readonly ViewDef[] = []) {
  const host = document.createElement("div");
  document.body.append(host);
  act(() => {
    createRoot(host).render(<Shell views={views} />);
  });
  return host;
}

/** A view that reports a header and draws nothing else. */
function reporting(header: Header): ViewDef {
  function Reporter({ setHeader }: ViewProps) {
    useEffect(() => {
      setHeader(header);
    }, [setHeader]);
    return <p>reported</p>;
  }
  return {
    group: "run",
    area: "orchestration",
    slug: "probe",
    title: "Probe",
    icon: "activity",
    component: Reporter,
  };
}

describe("the view registry", () => {
  it("is not empty; every view names one of the groups and one of today's address areas", () => {
    expect(VIEWS.length).toBeGreaterThan(0);
    const groups = new Set(GROUPS.map((g) => g.id));
    for (const view of VIEWS) {
      expect(groups.has(view.group)).toBe(true);
      expect(AREA_IDS).toContain(view.area);
    }
  });

  it("has no two views at one address", () => {
    const keys = VIEWS.map((v) => `${v.area}/${v.slug}`);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("puts the run records (today's home screen) under Home and Queue", () => {
    const records = VIEWS.find((v) => v.slug === "run-records");
    expect(records?.area).toBe("home");
    expect(records?.group).toBe("home");
  });
});

describe("the shell", () => {
  it("groups the navigation as the design's shell does, in order", () => {
    expect(GROUPS.map((g) => g.name)).toEqual([
      "Home and Queue",
      "This run",
      "Analyse",
      "Reference",
    ]);
  });

  it("lists only registered views, under their groups, and no empty group", () => {
    window.location.hash = "#/home/run-records";
    const host = mount(VIEWS);
    const links = [...host.querySelectorAll('nav[aria-label="Areas"] section .pg-nav-link')];
    expect(links.map((l) => l.textContent)).toEqual(
      GROUPS.flatMap((g) => VIEWS.filter((v) => v.group === g.id).map((v) => v.title)),
    );
    const shown = [...host.querySelectorAll(".pg-nav-heading")].map((h) => h.textContent);
    expect(shown).toEqual(
      GROUPS.filter((g) => VIEWS.some((v) => v.group === g.id)).map((g) => g.name),
    );
    expect(shown).not.toContain("Analyse");
  });

  it("shows an address with nothing registered as an empty state, not a blank page", () => {
    window.location.hash = "#/simulation";
    const host = mount([]);
    expect(host.querySelector(".pg-state-empty")?.textContent).toContain(
      "Nothing is registered at this address",
    );
    expect(host.querySelector(".pg-page-title")?.textContent).toBe("Nothing here");
  });

  it("parses a route from the hash", () => {
    const route = parseHash("#/home/run-records?run=0/run-on");
    expect([route.area, route.view, route.query.get("run")]).toEqual([
      "home",
      "run-records",
      "0/run-on",
    ]);
    expect(parseHash("").area).toBe("home");
  });
});

describe("the top bar", () => {
  const states: [OsLayer | null, string][] = [
    [{ state: "present", mechanism: "seatbelt" }, "OS layer · Seatbelt"],
    [{ state: "absent", reason: "bwrap missing", noOsProtection: false }, "OS layer absent"],
    [{ state: "absent", reason: "native Windows", noOsProtection: true }, "No OS protection"],
    [null, "OS layer not recorded"],
  ];

  it.each(states)(
    "the run chip shows the gate mode, in progress and the OS layer: %j",
    (layer, words) => {
      window.location.hash = "#/orchestration/probe";
      const host = mount([
        reporting({
          title: "Probe",
          source: { id: "0/run-on", commit: "0123456789" },
          gateMode: "observe",
          inProgress: true,
          osLayer: layer,
        }),
      ]);
      const chip = host.querySelector('[aria-label="The run shown"]');
      expect(chip?.textContent).toContain("Observe · not gated");
      expect(chip?.textContent).toContain("In progress · partial");
      expect(chip?.textContent).toContain(words);
      expect(chip?.querySelector(".pg-source")?.getAttribute("aria-label")).toContain("0/run-on");
    },
  );

  it("keeps the title whole, in the breadcrumb, after its group", () => {
    window.location.hash = "#/orchestration/probe";
    const host = mount([
      reporting({ title: "A very long screen title that must never be cut short" }),
    ]);
    const crumbs = [...host.querySelectorAll(".pg-breadcrumb li")].map((li) => li.textContent);
    expect(crumbs).toEqual(["This run", "A very long screen title that must never be cut short"]);
  });

  it("names the operator from the page, and says read only without the act token", () => {
    const meta = document.createElement("meta");
    meta.name = "physgate-operator";
    meta.content = "Yasin K.";
    document.head.append(meta);
    const host = mount([]);
    expect(host.querySelector(".pg-avatar")?.getAttribute("aria-label")).toBe("Yasin K.");
    expect(host.querySelector(".pg-read-only")?.textContent).toContain("Read only");
  });
});

describe("the collaborator's dock is a placeholder", () => {
  it("⌘J and Ctrl+J toggle it; open, it holds the one sentence and nothing else", () => {
    const host = mount([]);
    expect(host.querySelector(".pg-dock-panel")).toBeNull();
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "j", metaKey: true }));
    });
    const panel = host.querySelector(".pg-dock-panel");
    expect(panel?.textContent).toBe("The collaborator is not available in this build.");
    expect(
      panel?.querySelectorAll("input, textarea, button, [contenteditable], .pg-msg, .pg-change"),
    ).toHaveLength(0);
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "j", ctrlKey: true }));
    });
    expect(host.querySelector(".pg-dock-panel")).toBeNull();
  });

  it("the rail shows the collaborator's icon and no count", () => {
    const host = mount([]);
    const rail = host.querySelector(".pg-dock-rail");
    expect(rail?.querySelector('[data-icon="messages-square"]')).not.toBeNull();
    expect(rail?.textContent).toBe("");
  });
});

describe("theme and density", () => {
  function prefersDark(dark: boolean) {
    vi.spyOn(window, "matchMedia").mockImplementation(
      (query: string) =>
        ({
          matches: dark && query.includes("dark"),
          media: query,
          addEventListener: () => undefined,
          removeEventListener: () => undefined,
        }) as unknown as MediaQueryList,
    );
  }

  it("follows the system until a theme is chosen, then keeps the choice", () => {
    prefersDark(true);
    const host = mount([]);
    expect(document.documentElement.dataset.theme).toBe("dark");
    const toggle = host.querySelector<HTMLButtonElement>('button[title^="Theme"]');
    act(() => {
      toggle?.click();
    });
    expect(window.localStorage.getItem("physgate.theme")).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("switches density at run time and keeps it", () => {
    const host = mount([]);
    expect(document.documentElement.dataset.density).toBe("compact");
    act(() => {
      host.querySelector<HTMLButtonElement>('button[title^="Density"]')?.click();
    });
    expect(document.documentElement.dataset.density).toBe("comfortable");
    expect(window.localStorage.getItem("physgate.density")).toBe("comfortable");
  });

  it("renders the same when the storage throws", () => {
    prefersDark(false);
    const ids = (html: string) => html.replace(/_r_[a-z0-9]+_/g, "_id_");
    const normal = ids(mount([]).innerHTML);
    document.body.innerHTML = "";
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const host = mount([]);
    expect(ids(host.innerHTML)).toBe(normal);
    act(() => {
      host.querySelector<HTMLButtonElement>('button[title^="Density"]')?.click();
    });
    expect(document.documentElement.dataset.density).toBe("comfortable");
  });
});

describe("a two-key shortcut survives a change of route between its keys", () => {
  it("g, then the route changes, then t: still goes to the timeline", () => {
    window.location.hash = "#/orchestration/gate-checks?run=0/a";
    mount([]);
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "g" }));
    });
    // The route changes between the two keys, as a link or another shortcut would change it.
    act(() => {
      window.location.hash = "#/orchestration/gate-checks?run=0/b";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "t" }));
    });
    expect(window.location.hash).toBe("#/orchestration/run-timeline?run=0%2Fb");
  });
});
