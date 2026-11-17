// @vitest-environment happy-dom
/**
 * Where Home's runs stand, read again and again: a re-read that fails keeps the last good answer
 * and says since when it is not refreshed, so a run going stays going and its records are not
 * read again; the reads never exceed their cap however the rounds overlap; and Home's order is
 * settled once, after the first round or the short wait, and moved only when a minute's re-read
 * ends, so a row a person aims at in the first seconds is the row they click.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { RunListing } from "../../api/records";
import { runStatus } from "../../api/run";
import { clockTime } from "../../words/runs";
import { STATUS_EVERY_MS } from "../common/read";
import {
  homeOrder,
  phasesOf,
  type RunRead,
  STATUS_GRACE_MS,
  STATUS_POOL,
  STATUS_TIMEOUT_MS,
  useOrderPhases,
  useRunReads,
  useSettled,
  useStatuses,
} from "./data";
import { statusWords } from "./Home";

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

/** ``n`` runs, one a day from 1 Nov: bench-1 the oldest. */
const days = (n: number): RunListing[] =>
  Array.from({ length: n }, (_, i) =>
    run(`bench-${String(i + 1)}`, `2026-11-${String(i + 1).padStart(2, "0")}T10:00:00Z`),
  );

const GOING = {
  next_step: { kind: "attempt", subtask_id: "s1" },
  halted: null,
  owed_halt: null,
  completion: { owner: false, modules: [] },
};
const DONE = { ...GOING, next_step: { kind: "done", subtask_id: null } };

/** Status requests asked and not yet answered. */
let waiting: { path: string; answer: (body: unknown) => void }[] = [];
let asked: string[] = [];

/** A fetch whose status answers wait for the test, and that honours an abort; any other path is refused at once. */
function heldFetch(path: string, init?: RequestInit): Promise<Response> {
  asked.push(path);
  if (!path.endsWith("/status"))
    return Promise.resolve(new Response(JSON.stringify({ error: "not here" }), { status: 404 }));
  return new Promise<Response>((resolve, reject) => {
    const entry = {
      path,
      answer: (body: unknown) => {
        resolve(new Response(JSON.stringify(body), { status: 200 }));
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
  vi.setSystemTime(new Date("2026-11-17T10:00:00Z"));
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

/** Answer every status asked, and every one asked as those answer, with ``body(name)``. */
async function answerAll(body: (name: string) => unknown): Promise<void> {
  while (waiting.length > 0) {
    for (const w of waiting.splice(0))
      w.answer(body(/\/runs\/0\/([^/]+)\//.exec(w.path)?.[1] ?? ""));
    await settle();
  }
}

function render(node: React.ReactNode): HTMLElement {
  const host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  act(() => {
    root?.render(node);
  });
  return host;
}

function Standing({ runs }: { readonly runs: readonly RunListing[] }) {
  const { found, stale } = useStatuses(runs);
  return (
    <ul>
      {runs.map((r) => {
        const k = `0/${r.name}`;
        const s = found.get(k);
        const late = stale.get(k);
        return (
          <li key={k}>
            {s === undefined ? "reading" : s.ok ? s.value.kind : "refused"}
            {late === undefined ? "" : ` | not refreshed since ${late.since}: ${late.error}`}
          </li>
        );
      })}
    </ul>
  );
}

describe("a status re-read that fails keeps the last good answer", () => {
  it("the run stays where it stood, marked as not refreshed since that answer", async () => {
    const host = render(<Standing runs={days(1)} />);
    await settle();
    await answerAll(() => GOING);
    expect(host.textContent).toBe("attempt");
    await settle(STATUS_EVERY_MS);
    expect(waiting).toHaveLength(1);
    await settle(STATUS_TIMEOUT_MS);
    expect(host.textContent).toBe(
      "attempt | not refreshed since 2026-11-17T10:00:00.000Z: the server did not answer within 15 s",
    );
    // The next good answer is the answer again, with no mark.
    await settle(STATUS_EVERY_MS);
    await answerAll(() => DONE);
    expect(host.textContent).toBe("done");
  });

  it("a run never read well is listed as refused, with nothing kept", async () => {
    const host = render(<Standing runs={days(1)} />);
    await settle(STATUS_TIMEOUT_MS);
    expect(host.textContent).toBe("refused");
  });

  it("a going run's records are not read again because one status read failed", async () => {
    const runs = days(1);
    function Reads() {
      const { found } = useStatuses(runs);
      const reads = useRunReads(runs, found);
      return <p>{reads.size}</p>;
    }
    render(<Reads />);
    await settle();
    await answerAll(() => GOING);
    const configs = () => asked.filter((p) => p.endsWith("/config")).length;
    expect(configs()).toBe(1);
    await settle(STATUS_EVERY_MS);
    await settle(STATUS_TIMEOUT_MS);
    await settle();
    expect(configs()).toBe(1);
  });

  it("the row says where the run stood, and since when it is not refreshed, and why", () => {
    const read = {
      run: days(1)[0],
      status: { ok: true, value: runStatus(GOING) },
    } as unknown as RunRead;
    const since = "2026-11-17T09:58:00.000Z";
    const host = document.createElement("div");
    host.innerHTML = renderToStaticMarkup(
      <>{statusWords(read, { since, error: "the server did not answer within 15 s" })}</>,
    );
    expect(host.textContent).toContain("In progress");
    expect(host.textContent).toContain(
      `Not refreshed since ${clockTime(since)}: the server did not answer within 15 s`,
    );
  });

  it("a status that timed out says so, never only that it was not read", () => {
    const read = {
      run: days(1)[0],
      status: {
        ok: false,
        refusal: { status: 0, error: "the server did not answer within 15 s", context: {} },
      },
    } as unknown as RunRead;
    const host = document.createElement("div");
    host.innerHTML = renderToStaticMarkup(<>{statusWords(read)}</>);
    expect(host.textContent).toBe(
      "Where it stands was not read: the server did not answer within 15 s",
    );
  });
});

describe("overlapping rounds of status reads stay within the cap", () => {
  it("a round begun while another still reads never puts more than the cap in flight", async () => {
    render(<Standing runs={days(2 * STATUS_POOL)} />);
    await settle();
    expect(waiting).toHaveLength(STATUS_POOL);
    // The first lanes answer and take the rest of the first round.
    for (const w of waiting.splice(0)) w.answer(GOING);
    await settle();
    expect(waiting).toHaveLength(STATUS_POOL);
    // The page is shown again: a second round asks for the runs already answered.
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await settle();
    expect(waiting.length).toBeLessThanOrEqual(STATUS_POOL);
    while (waiting.length > 0) {
      for (const w of waiting.splice(0)) w.answer(GOING);
      await settle();
      expect(waiting.length).toBeLessThanOrEqual(STATUS_POOL);
    }
  });
});

function Ordered({ runs }: { readonly runs: readonly RunListing[] }) {
  const { found, minutes } = useStatuses(runs);
  const settled = useSettled(runs, found);
  const phases = useOrderPhases(phasesOf(runs, found), settled, minutes);
  return (
    <p>
      {homeOrder(runs, phases)
        .map((r) => r.name.replace("bench-", ""))
        .join(",")}
    </p>
  );
}

describe("Home settles its order once, and moves rows only on the minute's re-read", () => {
  it("an answer in the first seconds moves no row; the first round settles the order", async () => {
    const host = render(<Ordered runs={days(6)} />);
    await settle();
    expect(host.textContent).toBe("6,5,4,3,2,1");
    // The oldest run answers first, going, while the others still read.
    const first = waiting.find((w) => w.path.includes("/bench-1/"));
    waiting = waiting.filter((w) => w !== first);
    first?.answer(GOING);
    await settle();
    expect(host.textContent).toBe("6,5,4,3,2,1");
    await answerAll(() => DONE);
    expect(host.textContent).toBe("1,6,5,4,3,2");
  });

  it("with a status hanging, the order settles at the short wait, and once", async () => {
    const host = render(<Ordered runs={days(6)} />);
    await settle();
    const first = waiting.find((w) => w.path.includes("/bench-1/"));
    waiting = waiting.filter((w) => w !== first);
    first?.answer(GOING);
    await settle(STATUS_GRACE_MS);
    expect(host.textContent).toBe("1,6,5,4,3,2");
    // A later answer of the first round moves nothing until a minute's re-read ends.
    const second = waiting.find((w) => w.path.includes("/bench-2/"));
    waiting = waiting.filter((w) => w !== second);
    second?.answer(GOING);
    await settle();
    expect(host.textContent).toBe("1,6,5,4,3,2");
  });

  it("an answer read when the page is shown again waits for the minute's re-read to move a row", async () => {
    const host = render(<Ordered runs={days(6)} />);
    await settle();
    await answerAll((name) => (name === "bench-1" ? GOING : DONE));
    expect(host.textContent).toBe("1,6,5,4,3,2");
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await settle();
    await answerAll((name) => (name === "bench-1" || name === "bench-2" ? GOING : DONE));
    expect(host.textContent).toBe("1,6,5,4,3,2");
    await settle(STATUS_EVERY_MS);
    await answerAll((name) => (name === "bench-1" || name === "bench-2" ? GOING : DONE));
    expect(host.textContent).toBe("2,1,6,5,4,3");
  });
});
