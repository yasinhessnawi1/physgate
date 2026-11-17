// @vitest-environment happy-dom
/**
 * Home lists the runs at once, whatever their number, and no single run's status holds the page
 * up: the list starts in the run list's order and is re-ordered as each status answers; a status
 * that does not answer in time is given up; and only a few statuses are read at once, on the
 * first load, on the minute's re-read and when the page is shown again.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Result } from "../../api/client";
import type { RunListing } from "../../api/records";
import type { RunStatus } from "../../api/run";
import { STATUS_EVERY_MS } from "../common/read";
import { FIRST_RUNS } from "../common/runs";
import {
  phasesOf,
  readTargets,
  STATUS_GRACE_MS,
  STATUS_POOL,
  STATUS_TIMEOUT_MS,
  useSettled,
  useStatuses,
} from "./data";
import { Runs } from "./Home";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const run = (name: string, started: string): RunListing => ({
  root: 0,
  name,
  runId: name,
  manifestId: "m",
  gateMode: "on",
  osLayer: null,
  error: null,
  started,
});

/** ``n`` runs, one a day from 1 Nov, the newest last in the list as given. */
const days = (n: number): RunListing[] =>
  Array.from({ length: n }, (_, i) =>
    run(`bench-${String(i + 1)}`, `2026-11-${String(i + 1).padStart(2, "0")}T10:00:00Z`),
  );

const GOING: Result<RunStatus> = {
  ok: true,
  value: {
    kind: "attempt",
    subtask: "s1",
    halted: null,
    owedHalt: null,
    completion: { owner: false, modules: [] },
    waiting: [],
    superseded: {},
  } as unknown as RunStatus,
};

describe("Home lists the runs at once, before every status has answered", () => {
  const many = days(FIRST_RUNS + 3);

  it("with no status answered yet, chooses the newest twelve to read, in the run list's order", () => {
    const targets = readTargets(many, false, phasesOf(many, new Map()));
    expect(targets).not.toBeNull();
    expect((targets ?? []).map((r) => r.name)).toEqual(
      Array.from({ length: FIRST_RUNS }, (_, i) => `bench-${String(FIRST_RUNS + 3 - i)}`),
    );
  });

  it("a status that answers re-orders the list: an old run going moves to the top", () => {
    const phases = phasesOf(many, new Map([["0/bench-1", GOING]]));
    expect(phases?.get("0/bench-1")).toBe("going");
    const targets = readTargets(many, false, phases) ?? [];
    expect(targets[0]?.name).toBe("bench-1");
    expect(targets).toHaveLength(FIRST_RUNS);
  });

  it("the table lists each run chosen while its records are still read, not an empty table", () => {
    const chosen = days(3);
    const host = document.createElement("div");
    host.innerHTML = renderToStaticMarkup(
      <Runs runs={chosen} reads={new Map()} labels={new Map()} />,
    );
    const rows = host.querySelectorAll("tbody tr");
    expect(rows).toHaveLength(3);
    expect(rows[0]?.textContent).toContain("Reading");
    expect(host.textContent).not.toContain("not read yet");
  });
});

/** Status requests asked and not yet answered, each with what answers it. */
let waiting: { path: string; answer: () => void }[] = [];
let asked: string[] = [];

/** A fetch whose answers wait until the test gives them, and that honours an abort. */
function heldFetch(path: string, init?: RequestInit): Promise<Response> {
  asked.push(path);
  return new Promise<Response>((resolve, reject) => {
    const entry = {
      path,
      answer: () => {
        resolve(new Response(JSON.stringify({}), { status: 200 }));
      },
    };
    waiting.push(entry);
    init?.signal?.addEventListener("abort", () => {
      waiting = waiting.filter((w) => w !== entry);
      reject(new DOMException("The read was given up", "AbortError"));
    });
  });
}

let root: Root | null = null;

beforeEach(() => {
  vi.useFakeTimers();
  waiting = [];
  asked = [];
  vi.stubGlobal("fetch", vi.fn(heldFetch));
});

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

function Statuses({ runs }: { readonly runs: readonly RunListing[] }) {
  const found = useStatuses(runs);
  return (
    <ul>
      {runs.map((r) => {
        const s = found.get(`0/${r.name}`);
        return (
          <li key={r.name}>
            {s === undefined ? "reading" : s.ok ? "read" : `refused: ${s.refusal.error}`}
          </li>
        );
      })}
    </ul>
  );
}

async function mount(runs: readonly RunListing[]): Promise<HTMLElement> {
  const host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  act(() => {
    root?.render(<Statuses runs={runs} />);
  });
  await settle();
  return host;
}

describe("no run's status holds Home up", () => {
  it("a status that does not answer in time is given up, and the run is listed as not read", async () => {
    const host = await mount(days(1));
    expect(host.textContent).toBe("reading");
    await settle(STATUS_TIMEOUT_MS);
    expect(host.textContent).toMatch(/^refused: .*did not answer/);
  });

  it("reads only a few statuses at once on the first load, then the rest as each answers", async () => {
    await mount(days(20));
    expect(asked.length).toBeGreaterThan(0);
    expect(asked.length).toBeLessThanOrEqual(STATUS_POOL);
    while (waiting.length > 0) {
      for (const w of waiting.splice(0)) w.answer();
      await settle();
      expect(waiting.length).toBeLessThanOrEqual(STATUS_POOL);
    }
    expect(asked).toHaveLength(20);
  });

  it("showing the page again while statuses are still read asks nothing twice and stays in the cap", async () => {
    await mount(days(20));
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await settle();
    expect(asked.length).toBeLessThanOrEqual(STATUS_POOL);
    expect(new Set(asked).size).toBe(asked.length);
  });

  it("the minute's re-read is capped too", async () => {
    await mount(days(20));
    while (waiting.length > 0) {
      for (const w of waiting.splice(0)) w.answer();
      await settle();
    }
    asked = [];
    await settle(STATUS_EVERY_MS);
    expect(asked.length).toBeGreaterThan(0);
    expect(asked.length).toBeLessThanOrEqual(STATUS_POOL);
  });
});

function Settled({ runs }: { readonly runs: readonly RunListing[] }) {
  return <p>{useSettled(runs, useStatuses(runs)) ? "settled" : "waiting"}</p>;
}

describe("Home chooses which runs to read in full once the statuses answer, or after a short wait", () => {
  async function mountSettled(runs: readonly RunListing[]): Promise<HTMLElement> {
    const host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
    act(() => {
      root?.render(<Settled runs={runs} />);
    });
    await settle();
    return host;
  }

  it("every status answered: chosen at once", async () => {
    const host = await mountSettled(days(3));
    expect(host.textContent).toBe("waiting");
    for (const w of waiting.splice(0)) w.answer();
    await settle();
    expect(host.textContent).toBe("settled");
  });

  it("one status hanging: chosen after the short wait, long before that status is given up", async () => {
    const host = await mountSettled(days(3));
    for (const w of waiting.splice(0, 2)) w.answer();
    await settle();
    expect(host.textContent).toBe("waiting");
    expect(STATUS_GRACE_MS).toBeLessThan(STATUS_TIMEOUT_MS);
    await settle(STATUS_GRACE_MS);
    expect(host.textContent).toBe("settled");
  });
});
