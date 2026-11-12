// @vitest-environment happy-dom
import { act, useEffect } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ViewDef } from "../screens/registry";
import { type DisplayChoices, DisplayProvider, useDisplayChoices } from "./display";
import { Shell } from "./Shell";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

/** Every root a test mounts, unmounted after it so no React work outlives the test's window. */
const roots: Root[] = [];

beforeEach(() => {
  window.localStorage.clear();
  // No server answers here: every read is refused at once, so none is still pending at teardown.
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify({ error: "no server in this test" }), { status: 503 }),
      ),
    ),
  );
});

afterEach(() => {
  act(() => {
    for (const root of roots.splice(0)) root.unmount();
  });
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
  window.location.hash = "";
  window.history.replaceState(null, "", "/");
  delete document.documentElement.dataset.theme;
  delete document.documentElement.dataset.density;
});

function mount(node: React.ReactNode): HTMLElement {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  roots.push(root);
  act(() => {
    root.render(node);
  });
  return host;
}

/** What the last render of ``Probe`` read from the display choices. */
let seen: DisplayChoices | null = null;

function Probe() {
  const choices = useDisplayChoices();
  useEffect(() => {
    seen = choices;
  });
  return <p data-theme-choice={choices.theme}>{choices.density}</p>;
}

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

describe("the display choices are read only inside their provider", () => {
  it("throws outside it, naming the provider, rather than drift from the top bar", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    expect(() => mount(<Probe />)).toThrow(/DisplayProvider/);
  });
});

describe("a choice made through the provider is drawn and kept", () => {
  it("sets the theme, draws it and stores it", () => {
    prefersDark(false);
    mount(
      <DisplayProvider>
        <Probe />
      </DisplayProvider>,
    );
    expect(seen?.theme).toBe("system");
    expect(document.documentElement.dataset.theme).toBe("light");
    act(() => {
      seen?.setTheme("dark");
    });
    expect(seen?.theme).toBe("dark");
    expect(seen?.drawn).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(window.localStorage.getItem("physgate.theme")).toBe("dark");
    act(() => {
      seen?.setTheme("system");
    });
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(window.localStorage.getItem("physgate.theme")).toBe("system");
  });

  it("sets the density, draws it and stores it", () => {
    mount(
      <DisplayProvider>
        <Probe />
      </DisplayProvider>,
    );
    expect(document.documentElement.dataset.density).toBe("compact");
    act(() => {
      seen?.setDensity("comfortable");
    });
    expect(seen?.density).toBe("comfortable");
    expect(document.documentElement.dataset.density).toBe("comfortable");
    expect(window.localStorage.getItem("physgate.density")).toBe("comfortable");
  });

  it("reports a theme fixed by the address, and stores nothing while it holds", () => {
    window.history.replaceState(null, "", "/?theme=dark");
    window.localStorage.setItem("physgate.theme", "light");
    mount(
      <DisplayProvider>
        <Probe />
      </DisplayProvider>,
    );
    expect(seen?.override).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    act(() => {
      seen?.setTheme("system");
    });
    expect(window.localStorage.getItem("physgate.theme")).toBe("light");
  });

  it("reports no override for an address that names none", () => {
    mount(
      <DisplayProvider>
        <Probe />
      </DisplayProvider>,
    );
    expect(seen?.override).toBeNull();
  });

  it("keeps working on the defaults when the storage throws", () => {
    prefersDark(false);
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    mount(
      <DisplayProvider>
        <Probe />
      </DisplayProvider>,
    );
    expect(seen?.theme).toBe("system");
    expect(seen?.density).toBe("compact");
    act(() => {
      seen?.setTheme("dark");
      seen?.setDensity("comfortable");
    });
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.documentElement.dataset.density).toBe("comfortable");
  });
});

describe("the top bar and a view change the same choices", () => {
  const view: ViewDef = {
    group: "run",
    area: "orchestration",
    slug: "probe",
    title: "Probe",
    icon: "activity",
    component: function ProbeView() {
      return <Probe />;
    },
  };

  it("the top bar's toggles reach the view", () => {
    prefersDark(false);
    window.location.hash = "#/orchestration/probe";
    const host = mount(<Shell views={[view]} />);
    expect(host.querySelector("[data-theme-choice]")?.getAttribute("data-theme-choice")).toBe(
      "system",
    );
    act(() => {
      host.querySelector<HTMLButtonElement>('button[title^="Theme"]')?.click();
    });
    expect(host.querySelector("[data-theme-choice]")?.getAttribute("data-theme-choice")).toBe(
      "light",
    );
    act(() => {
      host.querySelector<HTMLButtonElement>('button[title^="Density"]')?.click();
    });
    expect(host.querySelector("[data-theme-choice]")?.textContent).toBe("comfortable");
  });

  it("the view's choices reach the top bar", () => {
    prefersDark(false);
    window.location.hash = "#/orchestration/probe";
    const host = mount(<Shell views={[view]} />);
    act(() => {
      seen?.setTheme("dark");
    });
    expect(host.querySelector('button[title^="Theme"]')?.getAttribute("title")).toBe(
      "Theme: Dark. Change it",
    );
    expect(document.documentElement.dataset.theme).toBe("dark");
    act(() => {
      seen?.setDensity("comfortable");
    });
    const density = host.querySelector('button[title^="Density"]');
    expect(density?.getAttribute("title")).toBe("Density: comfortable. Change it");
    expect(density?.getAttribute("aria-pressed")).toBe("true");
  });
});
