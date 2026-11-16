// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  CANARY,
  CATCHES,
  COMMIT,
  COMPARED,
  DIGEST,
  DRIFTED,
  readRow,
  RUNS,
  SPEND,
  TAMPERED,
  UNREADABLE,
  VIEW,
} from "./answers";
import Evidence from "./Evidence";
import { APART_WORDS, EVIDENCE_COPY, KIND_HEADINGS, KIND_TAGS } from "./words";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const SPEND_ROUTE = "/api/evidence/spend/0/ev-development/2026-11-01";
const MATCHED = "/api/evidence/compare/0/ev-development/0/ev-ablation";
const DRIFTED_ROUTE = "/api/evidence/compare/0/ev-development/0/ev-drifted";

type Answer = readonly [number, unknown];

let answers: Record<string, Answer> = {};
let asked: { path: string; init: RequestInit | undefined }[] = [];
let held: string | null = null;

function serve(over: Record<string, Answer> = {}) {
  answers = {
    "/api/evidence/runs": [200, RUNS],
    "/api/prices": [200, { prices: ["2026-10-01", "2026-11-01", "2026-09-15"] }],
    [SPEND_ROUTE]: [200, SPEND],
    [MATCHED]: [200, COMPARED],
    [DRIFTED_ROUTE]: [422, DRIFTED],
    "/api/evidence/catches": [200, CATCHES],
    ...over,
  };
}

beforeEach(() => {
  asked = [];
  held = null;
  serve();
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string, init?: RequestInit) => {
      asked.push({ path: input, init });
      const [status, body] = answers[input] ?? [404, { error: "no such route" }];
      if (held === input) return new Promise<Response>(() => undefined);
      return Promise.resolve(new Response(JSON.stringify(body), { status }));
    }),
  );
});

let root: Root | null = null;

afterEach(() => {
  act(() => {
    root?.unmount();
  });
  root = null;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

async function settle() {
  for (let i = 0; i < 8; i += 1)
    await act(async () => {
      await Promise.resolve();
    });
}

/** The screen at ``search``, read whole, in place of any mounted before. */
async function mount(search = ""): Promise<HTMLElement> {
  act(() => {
    root?.unmount();
  });
  document.body.innerHTML = "";
  const host = document.createElement("main");
  document.body.append(host);
  root = createRoot(host);
  act(() => {
    root?.render(<Evidence setHeader={() => undefined} query={new URLSearchParams(search)} />);
  });
  await settle();
  return host;
}

const text = (el: Element | null | undefined) => (el?.textContent ?? "").replace(/\s+/g, " ");

function sections(host: HTMLElement, selector = "section[data-kind]"): string[] {
  return [...host.querySelectorAll(selector)].map((s) => s.getAttribute("data-kind") ?? "");
}

function section(host: HTMLElement, label: string): Element | null {
  return host.querySelector(`section[aria-label="${label}"]`);
}

describe("the screen", () => {
  it("is titled Evidence, opens on the runs, and offers the four tabs and no other control", async () => {
    let title = "";
    const host = document.createElement("main");
    document.body.append(host);
    root = createRoot(host);
    act(() => {
      root?.render(
        <Evidence
          setHeader={(header) => {
            title = header.title;
          }}
          query={new URLSearchParams()}
        />,
      );
    });
    await settle();
    expect(title).toBe("Evidence");
    const tabs = [...host.querySelectorAll('[role="group"][aria-label="What to show"] button')];
    expect(tabs.map((b) => text(b))).toEqual(["Runs", "Spend", "Compare", "Catches"]);
    expect(tabs[0]?.getAttribute("aria-pressed")).toBe("true");
    expect(host.querySelector('section[data-tab="runs"]')).not.toBeNull();
  });

  it("says it is reading, and shows nothing of the runs until it has read them", async () => {
    held = "/api/evidence/runs";
    const host = await mount();
    expect(text(host.querySelector('[aria-busy="true"]'))).toContain("Reading the runs");
    expect(host.querySelector("table")).toBeNull();
    expect(sections(host)).toEqual([]);
  });

  it("says the server reads no run, in words, never an empty table", async () => {
    serve({ "/api/evidence/runs": [200, { runs: [] }] });
    for (const tab of ["runs", "spend", "compare", "catches"]) {
      const host = await mount(`tab=${tab}`);
      expect(text(host.querySelector(".pg-state-empty h2")), tab).toBe("This server reads no run.");
      expect(host.querySelector('[role="alert"]'), tab).toBeNull();
      expect(host.querySelector("table"), tab).toBeNull();
    }
  });

  it("names a refused list in a sentence, with its reason, and shows nothing partial", async () => {
    serve({ "/api/evidence/runs": [403, { error: "a file the allowlist refuses" }] });
    const host = await mount();
    const alert = host.querySelector('[role="alert"]');
    expect(text(alert?.querySelector("h2"))).toBe(EVIDENCE_COPY.runsRefused);
    expect(text(alert)).toContain("a file the allowlist refuses");
    expect(text(alert)).toContain("/api/evidence/runs");
    expect(sections(host)).toEqual([]);
  });

  it("refuses a list that carries a held-out tier's field, and shows none of it", async () => {
    const leaked = readRow("ev-reportable", "reportable", "4");
    const pins = { ...leaked.pins, held_out_sha256: [DIGEST] };
    serve({ "/api/evidence/runs": [200, { runs: [{ ...leaked, pins }] }] });
    const host = await mount();
    expect(host.querySelector('[role="alert"]')).not.toBeNull();
    expect(host.innerHTML).not.toContain(DIGEST);
    expect(sections(host)).toEqual([]);
  });

  it("asks the server with GETs only, for its own routes and the price sheets alone", async () => {
    for (const search of ["", "tab=spend", "tab=compare&a=0/ev-development&b=0/ev-ablation"])
      await mount(search);
    await mount("tab=catches");
    expect(asked.length).toBeGreaterThan(0);
    for (const { path, init } of asked) {
      expect(path).toMatch(/^\/api\/(evidence\/(runs|spend|compare|catches)(\/|$)|prices$)/);
      expect(init?.method ?? "GET").toBe("GET");
      expect(init?.body ?? null).toBeNull();
    }
    expect(document.querySelector(".pg-btn-act, .pg-btn-reject, dialog, form")).toBeNull();
  });

  it("shows no headline figure on any tab", async () => {
    for (const tab of ["runs", "spend", "compare", "catches"]) {
      const search = tab === "compare" ? "tab=compare&a=0/ev-development&b=0/ev-ablation" : "";
      const host = await mount(search === "" ? `tab=${tab}` : search);
      expect(host.querySelector(`section[data-tab="${tab}"]`), tab).not.toBeNull();
      expect(host.querySelector(".pg-quantity-lg"), tab).toBeNull();
      expect(text(host).toLowerCase(), tab).not.toMatch(/state[\s-]*of[\s-]*the[\s-]*art/);
    }
  });
});

describe("the runs, side by side", () => {
  it("sets each kind in its own section, reportable first and ablation last, never first", async () => {
    const host = await mount();
    expect(sections(host)).toEqual(["reportable", "development", "ablation"]);
    expect(text(section(host, KIND_HEADINGS.ablation)?.querySelector("h2"))).toBe("Ablation runs");
  });

  it("tags every run with its kind, in the owner's words for ablation and development", async () => {
    const host = await mount();
    const ablation = section(host, KIND_HEADINGS.ablation);
    expect(text(ablation)).toContain(
      "Ablation run: measures what removing a part changes; never reportable",
    );
    const development = section(host, KIND_HEADINGS.development);
    const tags = [...(development?.querySelectorAll("td .evidence-kind-tag") ?? [])];
    expect(tags.map((t) => text(t))).toEqual([KIND_TAGS.development, KIND_TAGS.development]);
  });

  it("names every run's source: its chip with the run and the commit it recorded", async () => {
    const host = await mount();
    const heads = [...host.querySelectorAll("th[data-run]")];
    expect(heads.map((h) => h.getAttribute("data-run"))).toEqual([
      "ev-reportable",
      "ev-development",
      "ev-drifted",
      "ev-ablation",
    ]);
    for (const head of heads) {
      expect(head.getAttribute("data-source")).toContain("0123456");
      expect(head.querySelector(".pg-source")).not.toBeNull();
    }
  });

  it("shows each run's seed, its manifest id short with the whole one copyable, and its check", async () => {
    const host = await mount();
    const development = section(host, KIND_HEADINGS.development);
    const ids = [...(development?.querySelectorAll(".pg-id-wrap") ?? [])];
    expect(ids.map((i) => text(i.querySelector(".pg-id")))).toEqual([
      "222222222222",
      "333333333333",
    ]);
    expect(ids[0]?.querySelector("button")?.getAttribute("aria-label")).toBe(
      `Copy ${"2".repeat(64)}`,
    );
    expect(text(development)).toContain(EVIDENCE_COPY.configHolds);
  });

  it("shows every recorded flag and pin as recorded, a nested one by its dotted path", async () => {
    const host = await mount();
    const reportable = section(host, KIND_HEADINGS.reportable);
    const paths = [...(reportable?.querySelectorAll("th .pg-id") ?? [])].map((p) => text(p));
    for (const path of ["gate_mode", "harness.commit", "hooks", "models.roles.control"])
      expect(paths).toContain(path);
    const rows = [...(reportable?.querySelectorAll("tbody tr") ?? [])].map((r) => text(r));
    expect(rows.some((r) => r.includes("Models roles control") && r.includes("model-role"))).toBe(
      true,
    );
    expect(rows.some((r) => r.includes("Max output tokens") && r.includes("64000"))).toBe(true);
    expect(rows.some((r) => r.includes("Harness commit") && r.includes(COMMIT))).toBe(true);
  });

  it("lists a run it could not read with its record and reason, and none of its settings", async () => {
    const host = await mount();
    const unread = section(host, EVIDENCE_COPY.unread);
    expect(text(unread?.querySelector('[data-run="ev-tampered"]'))).toContain(
      `Its run.json could not be read: ${TAMPERED.error}.`,
    );
    expect(text(unread?.querySelector('[data-run="ev-unreadable"]'))).toContain(
      `Its events.jsonl could not be read at offset 4211: ${UNREADABLE.error} (unknown kind).`,
    );
    expect(host.querySelector('th[data-run="ev-tampered"]')).toBeNull();
  });

  it("says a kind with no run in words, and says the gaps are not on this page yet", async () => {
    serve({ "/api/evidence/runs": [200, { runs: [readRow("ev-ablation", "ablation", "1")] }] });
    const host = await mount();
    expect(text(section(host, KIND_HEADINGS.reportable))).toContain(EVIDENCE_COPY.noneOfKind);
    expect(text(host)).toContain(
      "The two gaps are not on this page yet: no measurement of them exists.",
    );
    expect(sections(host)).toEqual(["reportable", "development", "ablation"]);
  });
});

describe("the spend", () => {
  it("names the newest price sheet the server holds, and asks for the spend at it", async () => {
    const host = await mount("tab=spend&run=0/ev-development");
    expect(text(host)).toContain(
      "Priced at the price sheet of 2026-11-01, the newest the server holds.",
    );
    expect(asked.map((a) => a.path)).toContain(SPEND_ROUTE);
  });

  it("opens on a reportable or development run, never an ablation run, when none is named", async () => {
    await mount("tab=spend");
    const spend = asked.map((a) => a.path).filter((p) => p.startsWith("/api/evidence/spend/"));
    expect(spend).toEqual(["/api/evidence/spend/0/ev-reportable/2026-11-01"]);
  });

  it("says the server holds no price sheet, and asks for no spend", async () => {
    serve({ "/api/prices": [200, { prices: [] }] });
    const host = await mount("tab=spend&run=0/ev-development");
    expect(text(host.querySelector(".pg-state-empty h2"))).toBe(EVIDENCE_COPY.noSheet);
    expect(asked.some((a) => a.path.startsWith("/api/evidence/spend/"))).toBe(false);
  });

  it("shows each session's row beside its role's sum, the sum labelled with the server's view", async () => {
    const host = await mount("tab=spend&run=0/ev-development");
    const table = host.querySelector('table[data-role="control"]');
    expect(
      [...(table?.querySelectorAll("tbody tr") ?? [])].map((r) => r.getAttribute("data-session")),
    ).toEqual(["s-1", "s-2"]);
    const sum = table?.querySelector("tfoot tr");
    expect(text(sum)).toContain("Sum");
    expect(text(sum)).toContain(VIEW);
  });

  it("marks a lower bound as one: 'at least' before the figure, and says why a seal broke", async () => {
    const host = await mount("tab=spend&run=0/ev-development");
    const table = host.querySelector('table[data-role="control"]');
    expect(text(table?.querySelector("tfoot"))).toContain("at least");
    expect(text(table?.querySelector('[data-session="s-2"]'))).toContain(EVIDENCE_COPY.sealBroken);
    expect(text(table?.querySelector('[data-session="s-1"]'))).not.toContain("at least");
    const cost = section(host, EVIDENCE_COPY.cost);
    expect(text(cost)).toContain("at least");
    expect(text(cost)).toContain(EVIDENCE_COPY.lowerBoundLine);
  });

  it("shows a cost to the cent with the exact figure one hover away, and every figure sourced", async () => {
    const host = await mount("tab=spend&run=0/ev-development");
    const cost = section(host, EVIDENCE_COPY.cost);
    const usd = cost?.querySelector(".pg-figure .pg-quantity");
    expect(text(usd?.querySelector(".pg-quantity-value"))).toBe("0.26");
    expect(usd?.getAttribute("title")).toBe("0.256912 USD as recorded");
    const quantities = [...host.querySelectorAll(".pg-quantity")];
    expect(quantities.length).toBeGreaterThan(0);
    for (const q of quantities) expect(q.closest("[data-source]")).not.toBeNull();
    expect(host.querySelector(".evidence-mark .pg-source")).not.toBeNull();
    expect(text(host.querySelector(".evidence-mark"))).toContain(KIND_TAGS.development);
  });

  it("says a group apart from the roles that holds no call in words, never a zero", async () => {
    const host = await mount("tab=spend&run=0/ev-development");
    for (const group of ["review", "routing", "left_over"] as const) {
      const apart = section(host, APART_WORDS[group].title);
      expect(text(apart)).toContain(APART_WORDS[group].none);
      expect(apart?.querySelector("table")).toBeNull();
    }
    expect(section(host, APART_WORDS.decomposition.title)?.querySelector("table")).not.toBeNull();
  });

  it("names a refused spend in a sentence with its record and date, and draws nothing of it", async () => {
    serve({
      [SPEND_ROUTE]: [
        422,
        {
          error: "the sheet is not one the server holds",
          root: "0",
          name: "ev-development",
          record: "prices",
          date: "2026-11-01",
        },
      ],
    });
    const host = await mount("tab=spend&run=0/ev-development");
    const alert = host.querySelector('[role="alert"]');
    expect(text(alert?.querySelector("h2"))).toBe("The spend of ev-development could not be read");
    expect(text(alert)).toContain("prices");
    expect(text(alert)).toContain("2026-11-01");
    expect(host.querySelector(".pg-quantity")).toBeNull();
  });
});

describe("two runs compared", () => {
  it("asks for no comparison until two runs are chosen, and says so", async () => {
    const host = await mount("tab=compare&a=0/ev-development");
    expect(text(host)).toContain(EVIDENCE_COPY.chooseTwo);
    expect(asked.some((a) => a.path.startsWith("/api/evidence/compare/"))).toBe(false);
  });

  it("shows the comparison's side by side, each run sourced, the settings that differ marked", async () => {
    const host = await mount("tab=compare&a=0/ev-development&b=0/ev-ablation");
    const table = host.querySelector("table.evidence-compare");
    expect(table).not.toBeNull();
    expect(text(host.querySelector('[data-note="differs"]'))).toBe(
      "The reported settings that differ: Ablation, Hooks.",
    );
    const differs = [...(table?.querySelectorAll('tr[data-differs="true"]') ?? [])];
    expect(differs.map((r) => r.getAttribute("data-field"))).toEqual(["hooks", "ablation"]);
    const wall = table?.querySelector('tr[data-field="wall_clock_s"]');
    expect(text(wall)).toContain("12.5");
    expect(text(wall)).toContain("9.25");
    for (const q of table?.querySelectorAll(".pg-quantity") ?? [])
      expect(q.closest("[data-source]")).not.toBeNull();
    expect(text(host.querySelector(".evidence-marks"))).toContain(KIND_TAGS.ablation);
  });

  it("shows a refusal over drifted settings in words, each setting named, and no number", async () => {
    const host = await mount("tab=compare&a=0/ev-development&b=0/ev-drifted");
    const alert = host.querySelector('[role="alert"]');
    expect(text(alert?.querySelector("h2"))).toBe(EVIDENCE_COPY.driftTitle);
    expect([...(alert?.querySelectorAll("li") ?? [])].map((li) => text(li))).toEqual([
      "The model that plans the subtasks",
      "The output token limit",
      "the tasks each run withheld differ",
    ]);
    const panel = host.querySelector('section[data-tab="compare"]');
    expect(panel?.querySelector("table")).toBeNull();
    expect(panel?.querySelector(".pg-quantity")).toBeNull();
    expect(host.innerHTML).not.toContain(DIGEST);
  });

  it("names any other refusal in a sentence with its reason", async () => {
    serve({ [MATCHED]: [404, { error: "no such run", root: "0", name: "ev-ablation" }] });
    const host = await mount("tab=compare&a=0/ev-development&b=0/ev-ablation");
    const alert = host.querySelector('[role="alert"]');
    expect(text(alert?.querySelector("h2"))).toBe(EVIDENCE_COPY.comparisonRefused);
    expect(text(alert)).toContain("no such run");
  });
});

describe("the gate's catches", () => {
  it("counts each kind in its own section, in order, and adds nothing across kinds", async () => {
    const host = await mount("tab=catches");
    expect(sections(host)).toEqual(["reportable", "development", "ablation"]);
    expect(text(host)).toContain(EVIDENCE_COPY.catchesLead);
    expect(host.querySelectorAll("tfoot").length).toBe(0);
    const rows = [...host.querySelectorAll("tr[data-check]")];
    expect(rows.length).toBe(3);
  });

  it("shows a rate only as k of n", async () => {
    const host = await mount("tab=catches");
    const all = section(host, KIND_HEADINGS.reportable)?.querySelector('tr[data-check="all"]');
    expect(text(all)).toContain("1 of 2");
    expect(text(host)).not.toMatch(/\d\s*%/);
  });

  it("says a kind whose runs ran no gate check in words, and one with no run so", async () => {
    const host = await mount("tab=catches");
    expect(text(section(host, KIND_HEADINGS.ablation))).toContain(
      "No gate check ran in these runs",
    );
    expect(section(host, KIND_HEADINGS.ablation)?.querySelector("table")).toBeNull();
    const none = { ...CATCHES, kinds: CATCHES.kinds.map((k) => ({ ...k, runs: [], rows: [] })) };
    serve({ "/api/evidence/catches": [200, none] });
    const again = await mount("tab=catches");
    expect(text(section(again, KIND_HEADINGS.reportable))).toContain(EVIDENCE_COPY.noneOfKind);
  });

  it("names every kind's runs by their chips, and the runs not counted with their reasons", async () => {
    const host = await mount("tab=catches");
    const development = section(host, KIND_HEADINGS.development);
    expect(development?.querySelectorAll(".pg-source").length).toBe(2);
    const unread = section(host, EVIDENCE_COPY.notCounted);
    expect(text(unread)).toContain(UNREADABLE.error);
  });

  it("refuses a count whose kinds are not the three in order", async () => {
    serve({ "/api/evidence/catches": [200, { ...CATCHES, kinds: [...CATCHES.kinds].reverse() }] });
    const host = await mount("tab=catches");
    expect(text(host.querySelector('[role="alert"] h2'))).toBe(EVIDENCE_COPY.catchesRefused);
    expect(host.querySelector("table")).toBeNull();
  });
});

describe("held-out strings", () => {
  it("never reach the page from any tab", async () => {
    for (const search of [
      "",
      "tab=spend&run=0/ev-reportable",
      "tab=compare&a=0/ev-development&b=0/ev-drifted",
      "tab=catches",
    ]) {
      const host = await mount(search);
      expect(host.querySelector("section[data-tab]"), search).not.toBeNull();
      expect(host.innerHTML).not.toContain(CANARY);
      expect(host.innerHTML).not.toContain(DIGEST);
    }
  });
});
