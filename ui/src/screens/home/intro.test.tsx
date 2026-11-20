// @vitest-environment happy-dom
/**
 * Home says, first and in a few plain sentences, what this page is: whose runs it lists, what a
 * run is, and where to look.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import Home from "./Home";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const LISTED = {
  runs: [
    {
      root: 0,
      name: "bench-1",
      run_id: "bench-1",
      manifest_id: "m",
      gate_mode: "on",
      os_layer: null,
      started: "2026-11-16T19:52:00Z",
    },
  ],
};

let root: Root | null = null;

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string) =>
      Promise.resolve(
        path === "/api/runs"
          ? new Response(JSON.stringify(LISTED), { status: 200 })
          : new Response(JSON.stringify({ error: "not served here" }), { status: 404 }),
      ),
    ),
  );
});

afterEach(() => {
  act(() => {
    root?.unmount();
  });
  root = null;
  document.body.replaceChildren();
  vi.unstubAllGlobals();
});

async function mount(): Promise<HTMLElement> {
  const host = document.createElement("main");
  document.body.append(host);
  root = createRoot(host);
  act(() => {
    root?.render(<Home setHeader={() => undefined} query={new URLSearchParams()} />);
  });
  for (let i = 0; i < 8; i += 1)
    await act(async () => {
      await Promise.resolve();
    });
  return host;
}

describe("Home says what it is, first", () => {
  it("a short intro leads the page, before anything else on it", async () => {
    const host = await mount();
    const intro = host.querySelector(".pg-home-intro");
    expect(intro).not.toBeNull();
    expect(host.querySelector(".pg-screen")?.firstElementChild?.contains(intro ?? null)).toBe(true);
  });

  it("says, in plain words, what a run is and what this page lists", async () => {
    const text = (await mount()).querySelector(".pg-home-intro")?.textContent ?? "";
    expect(text).toContain("This is the operator's view of the design runs on this machine.");
    expect(text).toContain("physics gate");
    expect(text).toContain("comes to a person");
    expect(text.split(/\s+/).length).toBeLessThan(110);
  });
});
