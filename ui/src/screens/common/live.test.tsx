// @vitest-environment happy-dom
/**
 * Where a run stands is read again while its page is open: on an interval while the page is
 * shown, and at once when it is shown again, so a run that stops (or goes on) is seen without a
 * reload. The last answer stays on screen while the next is read.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { RunListing } from "../../api/records";
import { useRunReads } from "../home/data";
import { STATUS_EVERY_MS, useLiveJson } from "./read";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let asked: string[] = [];
let answer = "first";

beforeEach(() => {
  vi.useFakeTimers();
  asked = [];
  answer = "first";
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string) => {
      asked.push(path);
      const body = path.endsWith("/events") ? "" : JSON.stringify({ said: answer });
      return Promise.resolve(new Response(body, { status: 200 }));
    }),
  );
});

let root: Root | null = null;
afterEach(() => {
  act(() => {
    root?.unmount();
  });
  root = null;
  document.body.replaceChildren();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

async function settle(): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
}

function Shown({ path }: { readonly path: string }) {
  const read = useLiveJson(path, (v) => (v as { said: string }).said);
  return <p>{read.result === null ? "reading" : read.result.ok ? read.result.value : "refused"}</p>;
}

async function mount(node: React.ReactNode): Promise<HTMLElement> {
  const host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  act(() => {
    root?.render(node);
  });
  await settle();
  return host;
}

describe("a run's status is read again while its page is open", () => {
  it("re-reads on the interval and shows the newer answer", async () => {
    const host = await mount(<Shown path="/api/runs/0/r/status" />);
    expect(host.textContent).toBe("first");
    expect(asked).toHaveLength(1);
    answer = "second";
    await act(async () => {
      await vi.advanceTimersByTimeAsync(STATUS_EVERY_MS);
    });
    expect(asked).toHaveLength(2);
    expect(host.textContent).toBe("second");
  });

  it("re-reads at once when the page is shown again", async () => {
    await mount(<Shown path="/api/runs/0/r/status" />);
    expect(asked).toHaveLength(1);
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await settle();
    expect(asked).toHaveLength(2);
  });

  it("keeps the last answer on screen while the next is read", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((path: string) => {
        asked.push(path);
        // The second read never answers.
        return asked.length === 1
          ? Promise.resolve(new Response(JSON.stringify({ said: "first" }), { status: 200 }))
          : new Promise<Response>(() => undefined);
      }),
    );
    const host = await mount(<Shown path="/api/runs/0/r/status" />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(STATUS_EVERY_MS);
    });
    expect(asked).toHaveLength(2);
    expect(host.textContent).toBe("first");
  });

  it("Home reads each run's status again on the interval, not its whole record", async () => {
    const run = { root: 0, name: "r", runId: "r", error: null } as unknown as RunListing;
    function Home() {
      useRunReads([run]);
      return null;
    }
    await mount(<Home />);
    const status = "/api/runs/0/r/status";
    expect(asked.filter((p) => p === status)).toHaveLength(1);
    const before = asked.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(STATUS_EVERY_MS);
    });
    expect(asked.filter((p) => p === status)).toHaveLength(2);
    // Only the status: nothing else was asked again.
    expect(asked.slice(before)).toEqual([status]);
  });
});
