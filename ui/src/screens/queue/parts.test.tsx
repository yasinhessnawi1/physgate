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
  if (n === 0 && runId === "run-parts") return partsItem;
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

/** The Queue screen over the scripted run's answers, ``raised`` for the round after the gate. */
async function mounted(raised = false): Promise<HTMLElement> {
  const base = raised ? RAISED_BASE : BASE;
  const runId = raised ? "run-raised" : "run-parts";
  const listing = raised ? partsRaised : partsOpen;
  const total = raised ? 7 : 6;
  const served: Record<string, unknown> = {
    "/api/runs": {
      runs: [{ root: 0, name: runId, run_id: runId, manifest_id: "m", gate_mode: "on" }],
    },
    [`${base}/config`]: config(runId),
    [`${base}/status`]: status,
    [`${base}/queue`]: listing,
  };
  for (let n = 0; n < total; n += 1)
    served[`${base}/queue/items/${String(n)}`] = raised
      ? n === 6
        ? raisedItem
        : viewAt(n, runId, false)
      : viewAt(n);
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = typeof input === "string" ? input : (input as Request).url;
    if (init?.method === "POST") {
      posted.push({ url, body: JSON.parse(init.body as string) as Record<string, unknown> });
      return Promise.resolve(answer());
    }
    if (url === `${base}/events`)
      return Promise.resolve(new Response(`${JSON.stringify(decomposed)}\n`));
    return Promise.resolve(new Response(JSON.stringify(served[url]), { status: 200 }));
  });
  const host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const query = raised ? "item=run-raised-parts-2-r2" : "item=run-parts-parts-1";
  act(() => {
    root?.render(<Queue setHeader={vi.fn()} query={new URLSearchParams(query)} />);
  });
  await settle();
  return host;
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
