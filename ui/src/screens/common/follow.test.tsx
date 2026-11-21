// @vitest-environment happy-dom
/**
 * A running run's log is followed while its page is shown: asked again from the last line held,
 * every few seconds, only while the run is going and the page is not hidden, and at once when it
 * is shown again. A half-written last line is never rendered; a read that fails keeps the lines
 * held; a log that is not the one held is read again from its start. No line is shown twice and
 * none is dropped.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FIRST_READ_MS, FOLLOW_EVERY_MS, useFollowedLog } from "./follow";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const BASE = "/api/runs/0/r";
const ROUTE = /^\/api\/runs\/0\/r\/events\/from\/(\d+)$/;

function line(seq: number, day = "20"): string {
  return `${JSON.stringify({ seq, ts: `2026-11-${day}T12:00:00Z`, kind: "something_recorded" })}\n`;
}

/** The fake server's log: whole lines, and what the writer has half written after them. */
let log: string[] = [];
let torn = "";
let failing = false;
let asked: string[] = [];
let visibility: DocumentVisibilityState = "visible";

beforeEach(() => {
  vi.useFakeTimers();
  log = [line(0), line(1), line(2)];
  torn = "";
  failing = false;
  asked = [];
  visibility = "visible";
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => visibility,
  });
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string) => {
      asked.push(path);
      const found = ROUTE.exec(path);
      if (found === null) return Promise.resolve(new Response("{}", { status: 404 }));
      if (failing)
        return Promise.resolve(
          new Response(JSON.stringify({ error: "the server failed to read this" }), {
            status: 500,
          }),
        );
      const from = Number(found[1]);
      // The client's own guard is tested here: this server hands over the torn piece too.
      const body = { count: log.length, from, lines: log.slice(from).join("") + torn };
      return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
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

async function settle(ms = 0): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

function Shown({ going }: { readonly going: boolean }) {
  const read = useFollowedLog(BASE, going);
  const shown =
    read.result === null
      ? "reading"
      : read.result.ok
        ? read.result.value.map((e) => `${String(e.seq)}@${e.ts.slice(8, 10)}`).join(",")
        : `refused: ${read.result.refusal.error}`;
  return (
    <p>
      {shown}
      {read.failedAgain ? " (not refreshed)" : ""}
    </p>
  );
}

async function mount(going: boolean): Promise<HTMLElement> {
  const host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  act(() => {
    root?.render(<Shown going={going} />);
  });
  await settle();
  return host;
}

const from = (n: number) => `${BASE}/events/from/${String(n)}`;

describe("a going run's log is followed while its page is shown", () => {
  it("reads from the first line, then from the last line held, adding each new line once", async () => {
    const host = await mount(true);
    expect(asked).toEqual([from(0)]);
    expect(host.textContent).toBe("0@20,1@20,2@20");
    log.push(line(3), line(4));
    await settle(FOLLOW_EVERY_MS);
    expect(asked).toEqual([from(0), from(2)]);
    expect(host.textContent).toBe("0@20,1@20,2@20,3@20,4@20");
    await settle(FOLLOW_EVERY_MS);
    expect(asked.at(-1)).toBe(from(4));
    expect(host.textContent).toBe("0@20,1@20,2@20,3@20,4@20");
  });

  it("never renders a half-written last line, and renders it once it is whole", async () => {
    torn = '{"seq": 3, "ts": "2026-11-20T12:0';
    const host = await mount(true);
    expect(host.textContent).toBe("0@20,1@20,2@20");
    torn = '{"seq": 3, "ts": "2026-11-20T12:00:00Z", "kind": "somethi';
    await settle(FOLLOW_EVERY_MS);
    expect(host.textContent).toBe("0@20,1@20,2@20");
    torn = "";
    log.push(line(3));
    await settle(FOLLOW_EVERY_MS);
    expect(host.textContent).toBe("0@20,1@20,2@20,3@20");
  });

  it("asks nothing while the page is hidden, and at once when it is shown again", async () => {
    const host = await mount(true);
    visibility = "hidden";
    log.push(line(3));
    await settle(FOLLOW_EVERY_MS * 4);
    expect(asked).toEqual([from(0)]);
    visibility = "visible";
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await settle();
    expect(asked).toEqual([from(0), from(2)]);
    expect(host.textContent).toBe("0@20,1@20,2@20,3@20");
  });

  it("keeps the lines held when a read fails, says so, and catches up without a gap", async () => {
    const host = await mount(true);
    failing = true;
    log.push(line(3));
    await settle(FOLLOW_EVERY_MS);
    expect(host.textContent).toBe("0@20,1@20,2@20 (not refreshed)");
    failing = false;
    log.push(line(4));
    await settle(FOLLOW_EVERY_MS);
    expect(asked.at(-1)).toBe(from(2));
    expect(host.textContent).toBe("0@20,1@20,2@20,3@20,4@20");
  });

  it("reads a log that is not the one held again from its start, showing nothing of the old", async () => {
    const host = await mount(true);
    log = [line(0, "21"), line(1, "21"), line(2, "21"), line(3, "21")];
    await settle(FOLLOW_EVERY_MS);
    expect(asked).toEqual([from(0), from(2), from(0)]);
    expect(host.textContent).toBe("0@21,1@21,2@21,3@21");
  });
});

describe("the log is not followed when there is nothing to follow", () => {
  it("a run that is not going is read once, and never again on a tick or when shown", async () => {
    const host = await mount(false);
    log.push(line(3));
    await settle(FOLLOW_EVERY_MS * 4);
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
      window.dispatchEvent(new Event("focus"));
    });
    await settle();
    expect(asked).toEqual([from(0)]);
    expect(host.textContent).toBe("0@20,1@20,2@20");
  });

  it("reads once more when the run stops going, then never again", async () => {
    await mount(true);
    act(() => {
      root?.render(<Shown going={false} />);
    });
    await settle(FOLLOW_EVERY_MS * 4);
    expect(asked).toEqual([from(0), from(2)]);
  });

  it("lines written after the last tick are shown once the run stops, without a reload", async () => {
    const host = await mount(true);
    log.push(line(3));
    await settle(FOLLOW_EVERY_MS);
    expect(host.textContent).toBe("0@20,1@20,2@20,3@20");
    // The run writes its last lines between two ticks, and its status then reads it as ended.
    log.push(line(4), line(5));
    act(() => {
      root?.render(<Shown going={false} />);
    });
    await settle();
    expect(asked).toEqual([from(0), from(2), from(3)]);
    expect(host.textContent).toBe("0@20,1@20,2@20,3@20,4@20,5@20");
    await settle(FOLLOW_EVERY_MS * 4);
    expect(asked).toHaveLength(3);
  });
});

describe("a read is bounded and stopped with the page", () => {
  it("a read still asked when the page leaves the run is stopped, not only dropped", async () => {
    const signals: AbortSignal[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((path: string, init?: RequestInit) => {
        asked.push(path);
        if (init?.signal) signals.push(init.signal);
        return new Promise<Response>(() => undefined);
      }),
    );
    await mount(true);
    expect(signals).toHaveLength(1);
    act(() => {
      root?.unmount();
    });
    root = null;
    expect(signals[0]?.aborted).toBe(true);
  });

  it("a first read the server never answers is a refusal in plain words", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((path: string, init?: RequestInit) => {
        asked.push(path);
        return new Promise<Response>((_, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("stopped", "AbortError"));
          });
        });
      }),
    );
    const host = await mount(false);
    expect(host.textContent).toBe("reading");
    await settle(FIRST_READ_MS);
    expect(host.textContent).toBe(
      `refused: the server did not answer within ${String(FIRST_READ_MS / 1000)} s`,
    );
  });
});
