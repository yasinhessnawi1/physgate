// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useChosenRun } from "./runs";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
afterEach(() => {
  act(() => {
    root?.unmount();
  });
  root = null;
  vi.restoreAllMocks();
});

const listed = (name: string, started: string) => ({
  root: 0,
  name,
  run_id: name,
  manifest_id: "m",
  gate_mode: "on",
  os_layer: null,
  started,
});

function Probe() {
  const chosen = useChosenRun(new URLSearchParams("run=0/bench-old"));
  return <span className="probe">{chosen.label?.label ?? "none"}</span>;
}

describe("a run screen reads only its own run's records", () => {
  it("labels every run from the run list, reading no other run's log", async () => {
    const asked: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      asked.push(url);
      if (url === "/api/runs")
        return Promise.resolve(
          new Response(
            JSON.stringify({
              runs: [
                listed("bench-old", "2026-11-03T17:17:00Z"),
                listed("bench-new", "2026-11-16T19:52:00Z"),
              ],
            }),
          ),
        );
      return Promise.resolve(new Response(JSON.stringify({ error: "x" }), { status: 404 }));
    });
    const host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
    act(() => {
      root?.render(<Probe />);
    });
    for (let i = 0; i < 12; i += 1)
      await act(async () => {
        await Promise.resolve();
      });
    expect(host.querySelector(".probe")?.textContent).toMatch(/^Run bench-old · 3 Nov, \d\d:\d\d$/);
    expect(asked.filter((url) => url.endsWith("/events"))).toEqual([]);
  });
});
