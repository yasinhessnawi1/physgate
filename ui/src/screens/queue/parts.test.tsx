// @vitest-environment happy-dom
/**
 * A part of the plan, as a person decides it on the Queue screen (ARCH-122). The answers are the
 * server's own, taken from the scripted run on the reference brief that asks which parts a person
 * has: its queue listing while every part is open, the first part's view, the decomposition's
 * line naming the components, and the same run once a made part was raised again at the release.
 *
 * The page reads a part's item whole; offers have, make and find, never approve or reject; states
 * each value with its unit; refuses before sending what the server would refuse and that the page
 * can know; and shows the server's refusal word for word, writing nothing.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { forgetToken, OPERATOR_META, takeTokenFromAddress } from "../../api/client";
import { runEvent } from "../../api/events";
import { itemView, queueListing } from "../../api/queue";
import decomposed from "../../api/served/event-decomposed-parts.json";
import partsItem from "../../api/served/item-parts.json";
import raisedItem from "../../api/served/item-parts-raised.json";
import partsOpen from "../../api/served/queue-parts-open.json";
import partsRaised from "../../api/served/queue-parts-raised.json";
import status from "../../api/served/status.json";
import Queue from "./Queue";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

/** What came of ``read``: its value, or the message it threw, so a row fails on its assertion. */
function outcome<T>(read: () => T): { ok: true; value: T } | { ok: false; error: string } {
  try {
    return { ok: true, value: read() };
  } catch (error) {
    return { ok: false, error: String(error) };
  }
}

describe("the page's parser reads a part's item as the route sends it", () => {
  it("reads the item view, whose choices are have, make and find", () => {
    const read = outcome(() => itemView(partsItem));
    expect(read).toMatchObject({ ok: true });
    if (!read.ok) return;
    expect(read.value.item.source).toBe("parts");
    expect(read.value.item.consequence?.onChoose).toEqual({
      have: "declare",
      make: "declare",
      find: "find",
    });
  });

  it("reads the listing while every part is open", () => {
    const read = outcome(() => queueListing(partsOpen));
    expect(read).toMatchObject({ ok: true });
    if (read.ok) expect(read.value.open.map((i) => i.itemId)).toHaveLength(6);
  });

  it("reads each decided part's choice and what it stated", () => {
    const read = outcome(() => queueListing(partsRaised));
    expect(read).toMatchObject({ ok: true });
    if (!read.ok) return;
    const [have, make] = read.value.decided;
    expect(have).toMatchObject({
      position: "have",
      parts: {
        declared: { mass: { value: 0.0095, unit: "kg" }, stall_current: { value: 1.6, unit: "A" } },
        texts: [],
      },
    });
    expect(make).toMatchObject({
      position: "make",
      parts: {
        declared: { efficiency: { value: 1.5, unit: "1" } },
        texts: ["printed in PETG, walls at least 2 mm"],
      },
    });
  });

  it("reads the components the decomposition's line lists", () => {
    const read = outcome(() => runEvent(decomposed));
    expect(read).toMatchObject({ ok: true });
    if (!read.ok) return;
    expect(read.value).toMatchObject({
      kind: "decomposed",
      components: expect.arrayContaining([
        {
          node: "electrical.gearmotors",
          domain: "electrical",
          role: "control",
          label: "Drive gearmotors, 50:1 Micro Metal HPCB 6V",
          own: ["mass", "stall_current"],
          shared: [],
        },
      ]) as unknown,
    });
  });
});

const BASE = "/api/runs/0/run-parts";
const RAISED_BASE = "/api/runs/0/run-raised";

function config(runId: string): unknown {
  return {
    manifest_id: "m",
    config: {
      run_id: runId,
      gate_mode: "on",
      harness: { commit: null },
      auth: "subscription",
      brief_sha256: "b",
      seed: 11,
      models: { roles: {}, decomposition: null },
    },
  };
}

/**
 * The view of the ``n``-th part as the item route sends it: the open listing's item, in run
 * ``runId`` and open or decided as ``open`` says.
 */
function viewAt(n: number, runId = "run-parts", open = true): unknown {
  if (n === 0 && runId === "run-parts") return open ? partsItem : { ...partsItem, open: false };
  const listing = partsOpen as { open: Record<string, unknown>[] };
  const item = JSON.parse(JSON.stringify(listing.open[n]).replaceAll("run-parts", runId)) as Record<
    string,
    unknown
  >;
  const digest = item.item_sha256;
  delete item.item_sha256;
  delete item.trajectory_statuses;
  return {
    item,
    item_sha256: digest,
    open,
    position: n,
    trajectories: [{ link: "decomposition/stdout.jsonl", session_id: null, status: "no_seal" }],
    view_id: `view-${String(n)}`,
  };
}

interface Posted {
  readonly url: string;
  readonly body: Record<string, unknown>;
}

let root: Root | null = null;
let posted: Posted[] = [];
/** What the decision route answers; by default the line the queue wrote. */
const RECORDED = (): Response =>
  new Response(
    JSON.stringify({
      resolved: {
        item_id: "run-parts-parts-1",
        ts: "2026-11-16T22:00:00.000000Z",
        kind: "resolution",
        decision: "choose have",
        resolved_by: "parts-operator",
      },
    }),
    { status: 201 },
  );
let answer: () => Response = RECORDED;

beforeEach(() => {
  const meta = document.createElement("meta");
  meta.name = OPERATOR_META;
  meta.content = "parts-operator";
  document.head.append(meta);
  window.history.replaceState(null, "", "/#act=tok-parts");
  takeTokenFromAddress();
});

afterEach(() => {
  act(() => {
    root?.unmount();
  });
  root = null;
  posted = [];
  answer = RECORDED;
  served = {};
  logged = [decomposed];
  reads = [];
  afterPost = null;
  failing = new Set();
  vi.useRealTimers();
  document.body.innerHTML = "";
  document.head.innerHTML = "";
  forgetToken();
  vi.restoreAllMocks();
});

async function settle(): Promise<void> {
  for (let i = 0; i < 14; i += 1)
    await act(async () => {
      await Promise.resolve();
    });
}

/** What the server stand-in answers each read with; a row may change it while the page is open. */
let served: Record<string, unknown> = {};
/** The run's event log, one record per line. */
let logged: unknown[] = [decomposed];
/** Every route the page read, in order. */
let reads: string[] = [];
/** Run after each post is answered: how a row makes the server's state follow a decision. */
let afterPost: (() => void) | null = null;
/** Routes the server stand-in answers with a failure, as a restarting server would. */
let failing = new Set<string>();

/** The scripted run's listing once its first ``k`` parts are decided, and each part's view. */
function decidedUpTo(k: number): void {
  const later = JSON.parse(JSON.stringify(partsRaised).replaceAll("run-raised", "run-parts")) as {
    decided: unknown[];
  };
  served[`${BASE}/queue`] = {
    decided: later.decided.slice(0, k),
    open: (partsOpen as { open: unknown[] }).open.slice(k),
  };
  for (let n = 0; n < 6; n += 1)
    served[`${BASE}/queue/items/${String(n)}`] = viewAt(n, "run-parts", n >= k);
}

/** The line the run writes once every part is decided and it is released. */
const RELEASED = {
  kind: "parts_released",
  run_id: "run-parts",
  seq: 3,
  ts: "2026-11-16T22:10:00.000000Z",
  components: [1, 2, 3, 4, 5, 6].map((n) => ({
    item_id: `run-parts-parts-${String(n)}`,
    choice: n === 1 ? "have" : n === 2 ? "make" : "find",
  })),
};

/** The Queue screen over the scripted run's answers, ``raised`` for the round after the gate. */
async function mounted(raised = false, item?: string): Promise<HTMLElement> {
  const base = raised ? RAISED_BASE : BASE;
  const runId = raised ? "run-raised" : "run-parts";
  const listing = raised ? partsRaised : partsOpen;
  const total = raised ? 7 : 6;
  served = {
    "/api/runs": {
      runs: [{ root: 0, name: runId, run_id: runId, manifest_id: "m", gate_mode: "on" }],
    },
    [`${base}/config`]: config(runId),
    [`${base}/status`]: status,
    [`${base}/queue`]: listing,
    ...served,
  };
  for (let n = 0; n < total; n += 1)
    served[`${base}/queue/items/${String(n)}`] ??= raised
      ? n === 6
        ? raisedItem
        : viewAt(n, runId, false)
      : viewAt(n);
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = typeof input === "string" ? input : (input as Request).url;
    if (init?.method === "POST") {
      posted.push({ url, body: JSON.parse(init.body as string) as Record<string, unknown> });
      const said = answer();
      afterPost?.();
      return Promise.resolve(said);
    }
    reads.push(url);
    if (failing.has(url))
      return Promise.resolve(
        new Response(JSON.stringify({ error: "the server is starting" }), { status: 503 }),
      );
    if (url === `${base}/events`)
      return Promise.resolve(new Response(logged.map((e) => `${JSON.stringify(e)}\n`).join("")));
    return Promise.resolve(new Response(JSON.stringify(served[url]), { status: 200 }));
  });
  const host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const query = `item=${item ?? (raised ? "run-raised-parts-2-r2" : "run-parts-parts-1")}`;
  act(() => {
    root?.render(<Queue setHeader={vi.fn()} query={new URLSearchParams(query)} />);
  });
  await settle();
  return host;
}

// The one fixture the command line's own rows read too: its part says what each choice does.
const PART_SENTENCES =
  (
    JSON.parse(
      readFileSync(resolve(process.cwd(), "../tests/fixtures/queue_sentences.json"), "utf8"),
    ) as { readonly source: string; readonly sentences: Record<string, string> }[]
  ).find((row) => row.source === "parts")?.sentences ?? {};

/** The sentences said beside a part's choices, by the choice (or ``note``) each belongs to. */
function beside(host: HTMLElement): Record<string, string> {
  return Object.fromEntries(
    [...host.querySelectorAll<HTMLElement>(".pg-parts-decide .pg-queue-effects li")].map((li) => [
      li.dataset.verb ?? "",
      li.textContent.trim(),
    ]),
  );
}

function radios(host: HTMLElement): HTMLInputElement[] {
  return [...host.querySelectorAll<HTMLInputElement>('.pg-parts-choice input[type="radio"]')];
}

function labelOf(input: HTMLInputElement): string {
  return input.closest("label")?.textContent.trim() ?? "";
}

function choose(host: HTMLElement, label: string): void {
  const radio = radios(host).find((r) => labelOf(r).startsWith(label));
  expect(radio, `no choice labelled ${label}`).toBeDefined();
  act(() => {
    radio?.click();
  });
}

function field(host: HTMLElement, label: string): HTMLInputElement | HTMLTextAreaElement | null {
  return host.querySelector<HTMLInputElement | HTMLTextAreaElement>(`[aria-label="${label}"]`);
}

/** Type ``value`` into the field labelled ``label``, as React reads a typed value. */
function type(host: HTMLElement, label: string, value: string): void {
  const input = field(host, label);
  expect(input, `no field labelled ${label}`).not.toBeNull();
  if (input === null) return;
  const proto =
    input instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
  act(() => {
    Object.getOwnPropertyDescriptor(proto, "value")?.set?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function recordButton(host: HTMLElement): HTMLButtonElement | undefined {
  return [...host.querySelectorAll<HTMLButtonElement>(".pg-parts-actions button")].find((b) =>
    b.textContent.includes("Record this choice"),
  );
}

/** Open the confirmation and confirm it; the request it sends is in ``posted``. */
async function record(host: HTMLElement): Promise<void> {
  const button = recordButton(host);
  expect(button, "no Record this choice button").toBeDefined();
  expect(button?.disabled).toBe(false);
  act(() => {
    button?.click();
  });
  const confirm = [...document.querySelectorAll<HTMLButtonElement>("dialog[open] button")].find(
    (b) => b.textContent.trim() === "Record",
  );
  expect(confirm, "no Record button in the confirmation").toBeDefined();
  act(() => {
    confirm?.click();
  });
  await settle();
}

describe("the Queue screen with a part open", () => {
  it("renders the part, not an error", async () => {
    const host = await mounted();
    expect(host.textContent).not.toContain("could not be read");
    expect(host.querySelector(".pg-queue-decision")?.textContent).toBe(
      "A part of the plan to decide",
    );
  });

  it("names the component: its label, domain, module role and the values it states", async () => {
    const host = await mounted();
    const facts = host.querySelector(".pg-parts-component")?.textContent ?? "";
    expect(facts).toContain("Drive gearmotors, 50:1 Micro Metal HPCB 6V");
    expect(facts).toContain("Electrical");
    expect(facts).toContain("Control");
    expect(facts).toContain("Part 1 of 6");
    expect(facts).toContain("Mass, Stall current");
    // The fields for its values are shown once a choice states values.
    expect(field(host, "Mass: value")).toBeNull();
    choose(host, "I have it");
    expect(field(host, "Mass: value")).not.toBeNull();
    expect(field(host, "Stall current: unit")).not.toBeNull();
  });

  it("offers have, make and find, find chosen, and never approve or reject", async () => {
    const host = await mounted();
    expect(radios(host).map(labelOf)).toEqual([
      expect.stringMatching(/^I have it/) as unknown,
      expect.stringMatching(/^I will make it/) as unknown,
      expect.stringMatching(/^Find it/) as unknown,
    ]);
    expect(radios(host).find((r) => r.checked)?.value).toBe("find");
    const words = [...host.querySelectorAll("button")].map((b) => b.textContent);
    expect(words.filter((w) => /approve|reject/i.test(w))).toEqual([]);
    expect(host.textContent).not.toContain("If you approve");
  });

  it("says what each choice will do, in the command line's words, and nothing of approve or reject", async () => {
    const host = await mounted();
    expect(beside(host)).toEqual({
      have: PART_SENTENCES.choose_have,
      make: PART_SENTENCES.choose_make,
      find: PART_SENTENCES.choose_find,
      note: PART_SENTENCES.note,
    });
  });

  it("says nothing of what a choice will do where this page cannot record one", async () => {
    forgetToken();
    const host = await mounted();
    expect(host.querySelector(".pg-parts-decide")).not.toBeNull();
    expect(beside(host)).toEqual({});
  });

  it("says that finding every remaining part at once is not on this page", async () => {
    const host = await mounted();
    expect(host.querySelector(".pg-parts-find-all")?.textContent).toContain("command line");
  });
});

describe("the three decisions, made from the page", () => {
  it("I have it sends each value with its unit, and no text", async () => {
    const host = await mounted();
    choose(host, "I have it");
    type(host, "Mass: value", "0.0095");
    type(host, "Mass: unit", "kg");
    type(host, "Stall current: value", "1.6");
    type(host, "Stall current: unit", "A");
    await record(host);
    expect(posted).toHaveLength(1);
    expect(posted[0]?.url).toBe(`${BASE}/queue/decisions`);
    expect(posted[0]?.body).toEqual({
      item_id: "run-parts-parts-1",
      verb: "choose",
      position: "have",
      note: "",
      parts: {
        declared: { mass: { value: 0.0095, unit: "kg" }, stall_current: { value: 1.6, unit: "A" } },
        texts: [],
      },
      shown: {
        item_sha256: (partsItem as { item_sha256: string }).item_sha256,
        trajectories: ["no_seal"],
      },
      view_id: (partsItem as { view_id: string }).view_id,
    });
  });

  it("I have it takes a quantity the plan does not name, as the server admits it", async () => {
    const host = await mounted();
    choose(host, "I have it");
    type(host, "Mass: value", "0.0095");
    type(host, "Mass: unit", "kg");
    const add = [...host.querySelectorAll("button")].find((b) =>
      b.textContent.includes("Add another quantity"),
    );
    act(() => {
      add?.click();
    });
    type(host, "Another quantity 1: name", "rated_voltage");
    type(host, "Another quantity 1: value", "6");
    type(host, "Another quantity 1: unit", "V");
    await record(host);
    expect(posted[0]?.body.parts).toEqual({
      declared: { mass: { value: 0.0095, unit: "kg" }, rated_voltage: { value: 6, unit: "V" } },
      texts: [],
    });
  });

  it("I will make it sends the values and the short texts stated", async () => {
    const host = await mounted();
    choose(host, "I will make it");
    type(host, "Mass: value", "0.012");
    type(host, "Mass: unit", "kg");
    type(host, "Text 1", "printed in PETG, walls at least 2 mm");
    await record(host);
    expect(posted[0]?.body).toMatchObject({
      position: "make",
      parts: {
        declared: { mass: { value: 0.012, unit: "kg" } },
        texts: ["printed in PETG, walls at least 2 mm"],
      },
    });
  });

  it("Find it sends the choice and states nothing", async () => {
    const host = await mounted();
    await record(host);
    expect(posted[0]?.body.position).toBe("find");
    expect(posted[0]?.body).not.toHaveProperty("parts");
  });
});

/** Open the confirmation without confirming it; its text, or ``null`` if none opened. */
function confirmationText(host: HTMLElement): string | null {
  const button = recordButton(host);
  expect(button, "no Record this choice button").toBeDefined();
  act(() => {
    button?.click();
  });
  return document.querySelector("dialog[open]")?.textContent ?? null;
}

describe("the confirmation names where the run stands", () => {
  const RESUMED = "The decision is recorded now and taken up when the run is resumed.";

  it("on a run that has ended, says the decision is recorded now and taken up when the run is resumed", async () => {
    served[`${BASE}/status`] = { ...status, next_step: { kind: "done" } };
    const host = await mounted();
    const text = confirmationText(host);
    expect(text).toContain(`This run has ended. ${RESUMED}`);
    expect(document.querySelector("dialog[open] .pg-dialog-run-state")?.textContent).toBe(
      `This run has ended. ${RESUMED}`,
    );
  });

  it("on a going run, says nothing of a resume", async () => {
    const host = await mounted();
    const text = confirmationText(host);
    expect(text).toContain("One line appended to queue_decisions.jsonl");
    expect(text).not.toContain(RESUMED);
    expect(document.querySelector("dialog[open] .pg-dialog-run-state")).toBeNull();
  });
});

describe("what the page refuses before sending, and what the server refuses", () => {
  it("a value without its unit is refused, and nothing is sent", async () => {
    const host = await mounted();
    choose(host, "I have it");
    type(host, "Mass: value", "0.0095");
    expect(host.querySelector(".pg-parts-problems")?.textContent).toContain(
      "Mass: a value needs its unit",
    );
    expect(recordButton(host)?.disabled).toBe(true);
    expect(posted).toEqual([]);
  });

  it("I have it with no value stated is refused", async () => {
    const host = await mounted();
    choose(host, "I have it");
    expect(host.querySelector(".pg-parts-problems")?.textContent).toContain(
      "state at least one value",
    );
    expect(recordButton(host)?.disabled).toBe(true);
  });

  it("a value that is not a number is refused", async () => {
    const host = await mounted();
    choose(host, "I have it");
    type(host, "Mass: value", "about 10");
    type(host, "Mass: unit", "g");
    expect(host.querySelector(".pg-parts-problems")?.textContent).toContain(
      "Mass: the value must be a number",
    );
  });

  it("the server's refusal is shown word for word, and nothing is said to be recorded", async () => {
    answer = () =>
      new Response(
        // The route's own answer to this body, as the server gave it.
        JSON.stringify({
          error: "the request is not a decision",
          reason:
            "parts: Value error, 'stall_current' is not written in a unit of its kind: pint " +
            "cannot convert 'volt' ([mass] * [length]**2 * [time]**-3 * [current]**-1) to " +
            "'ampere' ([current])",
        }),
        { status: 400 },
      );
    const host = await mounted();
    choose(host, "I have it");
    type(host, "Stall current: value", "240");
    type(host, "Stall current: unit", "V");
    await record(host);
    // Shown in the open, not folded away: the server's words are what the person corrects by.
    expect(host.querySelector(".pg-parts-refused")?.textContent).toContain(
      "'stall_current' is not written in a unit of its kind",
    );
    expect(host.querySelector(".pg-queue-recorded")).toBeNull();
  });
});

describe("a part raised again after the release gate", () => {
  it("shows the gate's finding and offers no find", async () => {
    const host = await mounted(true);
    expect(host.textContent).not.toContain("could not be read");
    expect(host.querySelector(".pg-parts-raised")?.textContent).toContain(
      "efficiency of mechanical.bumper_cage is 1.5 1, outside 0 to 1 1",
    );
    expect(radios(host).map((r) => r.value)).toEqual(["have", "make"]);
  });

  it("says what have and make do, and nothing of find, which it does not offer", async () => {
    const host = await mounted(true);
    const said = beside(host);
    expect(Object.keys(said)).toEqual(["have", "make", "note"]);
    expect(said.have).toBe(PART_SENTENCES.choose_have);
    expect(said.make).toBe(PART_SENTENCES.choose_make);
  });

  it("asks again for every name stated before, with the value stated then", async () => {
    const host = await mounted(true);
    expect(radios(host).find((r) => r.checked)?.value).toBe("make");
    expect(field(host, "Efficiency: value")).not.toBeNull();
    expect(host.querySelector(".pg-parts-values")?.textContent).toContain("Stated before: 1.5 1");
    type(host, "Text 1", "printed in PETG");
    expect(host.querySelector(".pg-parts-problems")?.textContent).toContain(
      "state efficiency again",
    );
  });
});

/** Let the page's own clock run on by ``ms``, as it would while the page stays open. */
async function wait(ms: number): Promise<void> {
  act(() => {
    vi.advanceTimersByTime(ms);
  });
  await settle();
}

function waitingCount(host: HTMLElement): string {
  return (
    [...host.querySelectorAll("button, [role='radio'], label")]
      .map((e) => e.textContent.trim())
      .find((t) => t.startsWith("Waiting")) ?? ""
  );
}

describe("the queue read again while the page is open", () => {
  it("shows a part the gate raised again without the page being opened again", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    decidedUpTo(6);
    const host = await mounted(false, "run-parts-parts-6");
    expect(waitingCount(host)).toBe("Waiting · 0");
    const raised = JSON.parse(
      JSON.stringify(partsRaised).replaceAll("run-raised", "run-parts"),
    ) as Record<string, unknown>;
    served[`${BASE}/queue`] = raised;
    served[`${BASE}/queue/items/6`] = JSON.parse(
      JSON.stringify(raisedItem).replaceAll("run-raised", "run-parts"),
    ) as unknown;
    await wait(60_000);
    expect(waitingCount(host)).toBe("Waiting · 1");
    expect(host.querySelector(".pg-queue-list")?.textContent).toContain("run-parts-parts-2-r2");
  });

  it("shows the run released without the page being opened again", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    decidedUpTo(6);
    const host = await mounted(false, "run-parts-parts-6");
    expect(host.querySelector(".pg-parts-released")).toBeNull();
    logged = [decomposed, RELEASED];
    await wait(60_000);
    expect(host.querySelector(".pg-parts-released")?.textContent).toBe(
      "Every part is decided, and the run was released: 1 you have, 1 you will make, 4 to find.",
    );
  });

  it("never reads the open part's view again on its own, so its shown time stands", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    const host = await mounted();
    expect(host.querySelector(".pg-parts-decide")).not.toBeNull();
    const before = reads.filter((r) => r === `${BASE}/queue/items/0`).length;
    const listed = reads.filter((r) => r === `${BASE}/queue`).length;
    await wait(60_000);
    expect(reads.filter((r) => r === `${BASE}/queue`).length).toBeGreaterThan(listed);
    expect(reads.filter((r) => r === `${BASE}/queue/items/0`).length).toBe(before);
  });

  it("reads the queue every five seconds and the status once a minute, and neither while hidden", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    await mounted();
    const count = (route: string) => reads.filter((r) => r === `${BASE}${route}`).length;
    const routes = ["/queue", "/events", "/status", "/config", "/queue/items/0"];
    const at = (): number[] => routes.map(count);
    const start = at();
    // Second by second, so each tick is its own render, as on a real clock.
    for (let s = 0; s < 60; s += 1) await wait(1_000);
    // Twelve ticks: the listing each tick, the log each tick while the run awaits its release,
    // the status once, and nothing else again.
    expect(at().map((n, i) => n - (start[i] ?? 0))).toEqual([12, 12, 1, 0, 0]);
    Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
    try {
      const hidden = reads.length;
      for (let s = 0; s < 120; s += 1) await wait(1_000);
      expect(reads.length).toBe(hidden);
    } finally {
      Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
    }
  });

  it("keeps the last good queue on screen when one refresh fails, and says so, with what was typed", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    const host = await mounted();
    choose(host, "I have it");
    type(host, "Mass: value", "0.0095");
    type(host, "Mass: unit", "kg");
    const panel = host.querySelector(".pg-parts-decide");
    expect(panel).not.toBeNull();
    failing.add(`${BASE}/queue`);
    await wait(5_000);
    expect(host.querySelector(".pg-queue-refresh-failed")?.textContent).toBe(
      "The latest refresh of this page failed; it tries again in a few seconds. What is shown is from the last refresh that worked.",
    );
    expect(host.textContent).not.toContain("The queue could not be read");
    expect(host.querySelector(".pg-parts-decide")).toBe(panel);
    expect((field(host, "Mass: value") as HTMLInputElement | null)?.value).toBe("0.0095");
    expect((field(host, "Mass: unit") as HTMLInputElement | null)?.value).toBe("kg");
    failing.clear();
    await wait(5_000);
    expect(host.querySelector(".pg-queue-refresh-failed")).toBeNull();
    expect(host.querySelector(".pg-parts-decide")).toBe(panel);
    expect((field(host, "Mass: value") as HTMLInputElement | null)?.value).toBe("0.0095");
  });

  it("keeps the part's panel, its name and what was typed when one refresh of the run's log fails", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    const host = await mounted();
    choose(host, "I have it");
    type(host, "Mass: value", "0.0095");
    type(host, "Mass: unit", "kg");
    const panel = host.querySelector(".pg-parts-decide");
    const named = host.querySelector(".pg-parts-component")?.textContent ?? "";
    expect(named).toContain("Part 1 of 6");
    failing.add(`${BASE}/events`);
    await wait(5_000);
    expect(host.querySelector(".pg-parts-decide")).toBe(panel);
    expect(host.querySelector(".pg-parts-component")?.textContent).toBe(named);
    expect((field(host, "Mass: value") as HTMLInputElement | null)?.value).toBe("0.0095");
    expect((field(host, "Mass: unit") as HTMLInputElement | null)?.value).toBe("kg");
    expect(host.querySelector(".pg-queue-refresh-failed")).not.toBeNull();
    const before = reads.filter((r) => r === `${BASE}/events`).length;
    failing.clear();
    await wait(5_000);
    expect(reads.filter((r) => r === `${BASE}/events`).length).toBeGreaterThan(before);
    expect(host.querySelector(".pg-queue-refresh-failed")).toBeNull();
  });

  it("keeps what a person typed while the queue is read again", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    const host = await mounted();
    choose(host, "I have it");
    type(host, "Mass: value", "0.0095");
    await wait(60_000);
    expect((field(host, "Mass: value") as HTMLInputElement | null)?.value).toBe("0.0095");
  });

  it("reads the queue again after a refusal, and keeps the refusal and what was typed", async () => {
    answer = () =>
      new Response(
        JSON.stringify({ error: "the item is no longer as shown", item: "run-parts-parts-1" }),
        { status: 409 },
      );
    const host = await mounted();
    choose(host, "I have it");
    type(host, "Mass: value", "0.0095");
    type(host, "Mass: unit", "kg");
    const listed = reads.filter((r) => r === `${BASE}/queue`).length;
    await record(host);
    expect(reads.filter((r) => r === `${BASE}/queue`).length).toBeGreaterThan(listed);
    expect(host.querySelector(".pg-parts-refused")?.textContent).toContain(
      "the item is no longer as shown",
    );
    expect((field(host, "Mass: value") as HTMLInputElement | null)?.value).toBe("0.0095");
  });
  it("keeps the refusal on screen when the part turns out to be decided elsewhere", async () => {
    answer = () =>
      new Response(JSON.stringify({ error: "not an open item", item: "run-parts-parts-1" }), {
        status: 409,
      });
    afterPost = () => {
      decidedUpTo(1);
    };
    const host = await mounted(false, "run-parts-parts-1");
    await record(host);
    expect(host.querySelector(".pg-parts-decide")).toBeNull();
    expect(host.querySelector(".pg-queue-entry-on")?.textContent).toContain("run-parts-parts-1");
    const refused = host.querySelector(".pg-parts-refused")?.textContent ?? "";
    expect(refused).toContain("The server refused this choice, and nothing was written:");
    expect(refused).toContain("not an open item");
  });
});

describe("a page that lost its token", () => {
  it("says a reload forgot it, and that the operator address opens it again", async () => {
    forgetToken();
    vi.spyOn(performance, "getEntriesByType").mockReturnValue([
      { type: "reload" } as unknown as PerformanceEntry,
    ]);
    window.history.replaceState(null, "", "/");
    takeTokenFromAddress();
    const host = await mounted();
    const why = host.querySelector(".pg-parts-decide .pg-queue-why-not")?.textContent ?? "";
    expect(why).toContain("reloaded");
    expect(why).toContain("open the operator address");
    expect(window.sessionStorage.length).toBe(0);
    expect(window.localStorage.length).toBe(0);
  });
});

describe("after a part is decided", () => {
  it("moves to the next open part, says Recorded for the one decided, and puts focus on the choice", async () => {
    // The address names the first part, as a click in the list leaves it.
    afterPost = () => {
      decidedUpTo(1);
    };
    const host = await mounted(false, "run-parts-parts-1");
    await record(host);
    expect(host.querySelector(".pg-parts-component")?.textContent).toContain("Part 2 of 6");
    const recorded = host.querySelector(".pg-queue-recorded")?.textContent ?? "";
    expect(recorded).toContain("choose have");
    expect(recorded).toContain("Drive gearmotors, 50:1 Micro Metal HPCB 6V");
    const focused = document.activeElement as HTMLInputElement | null;
    expect(focused?.type).toBe("radio");
    expect(focused?.checked).toBe(true);
    expect(focused?.closest(".pg-parts-decide")).not.toBeNull();
  });

  it("opens the part the page was first opened on again when it is clicked after the page moved on", async () => {
    afterPost = () => {
      decidedUpTo(1);
    };
    const host = await mounted(false, "run-parts-parts-1");
    await record(host);
    expect(host.querySelector(".pg-parts-component")?.textContent).toContain("Part 2 of 6");
    const resolvedTab = [
      ...host.querySelectorAll<HTMLElement>("button, [role='radio'], label"),
    ].find((e) => e.textContent.trim().startsWith("Resolved"));
    act(() => {
      resolvedTab?.click();
    });
    const first = host.querySelector<HTMLAnchorElement>(
      'a.pg-queue-entry[href*="run-parts-parts-1"]',
    );
    expect(first, "no list entry for the first part").not.toBeNull();
    act(() => {
      first?.click();
    });
    // The address names the first part again, as the page's router passes it on.
    act(() => {
      root?.render(
        <Queue setHeader={vi.fn()} query={new URLSearchParams("item=run-parts-parts-1")} />,
      );
    });
    await settle();
    expect(host.querySelector(".pg-queue-entry-on")?.textContent ?? "").toContain(
      "run-parts-parts-1",
    );
    expect(host.querySelector(".pg-parts-decide")).toBeNull();
  });

  it("once the last part is decided, says what the run does next", async () => {
    decidedUpTo(5);
    afterPost = () => {
      decidedUpTo(6);
    };
    answer = () =>
      new Response(
        JSON.stringify({
          resolved: {
            item_id: "run-parts-parts-6",
            ts: "2026-11-16T22:00:00.000000Z",
            kind: "resolution",
            decision: "choose find",
            resolved_by: "parts-operator",
          },
        }),
        { status: 201 },
      );
    const host = await mounted(false, "run-parts-parts-6");
    await record(host);
    const next = host.querySelector(".pg-parts-next")?.textContent ?? "";
    expect(next).toContain("Every part is decided");
    expect(next).toContain("checks");
    expect(next).toContain("brings the part back here with the gate's finding");
    expect(next).toContain("resumed");
    expect(host.querySelector(".pg-queue-recorded")?.textContent).toContain("choose find");
  });
});

describe("a quantity the physics gate's catalogue does not name", () => {
  it("is said, beside its name, to be recorded as unchecked", async () => {
    const host = await mounted();
    choose(host, "I have it");
    const add = [...host.querySelectorAll("button")].find((b) =>
      b.textContent.includes("Add another quantity"),
    );
    act(() => {
      add?.click();
    });
    type(host, "Another quantity 1: name", "bumper_stiffness");
    const row = field(host, "Another quantity 1: name")?.closest(".pg-parts-row");
    expect(row?.querySelector(".pg-parts-unchecked")?.textContent).toContain(
      "recorded as unchecked",
    );
    type(host, "Another quantity 1: name", "stall_torque");
    expect(row?.querySelector(".pg-parts-unchecked")).toBeNull();
    // The plan's own names are the catalogue's: none of them is marked.
    expect(host.querySelectorAll(".pg-parts-unchecked")).toHaveLength(0);
  });
});

describe("the list beside a decided item", () => {
  it("shows the item just decided among the resolved, marked as the one on screen", async () => {
    decidedUpTo(5);
    afterPost = () => {
      decidedUpTo(6);
    };
    const host = await mounted(false, "run-parts-parts-6");
    expect(host.querySelector(".pg-queue-entry-on")?.textContent).toContain("run-parts-parts-6");
    await record(host);
    const on = host.querySelector(".pg-queue-entry-on");
    expect(on?.textContent).toContain("run-parts-parts-6");
    expect(on?.querySelector('[data-status-kind="resolved"]')?.textContent).toBe("Resolved");
  });
});
