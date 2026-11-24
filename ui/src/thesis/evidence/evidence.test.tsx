// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  CANARY,
  CATCHES,
  catchRow,
  COMMIT,
  COMPARED,
  DIGEST,
  DRIFTED,
  GAPS,
  readRow,
  RUNS,
  source,
  SPEND,
  TAMPERED,
  TIERS,
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
    "/api/evidence/gaps": [200, GAPS],
    "/api/evidence/tiers": [200, TIERS],
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

/** Open every kind's folded settings. */
function openSettings(host: HTMLElement) {
  for (const toggle of host.querySelectorAll<HTMLButtonElement>("section[data-kind] button"))
    if (toggle.textContent.startsWith("Show the settings"))
      act(() => {
        toggle.click();
      });
}

const text = (el: Element | null | undefined) => (el?.textContent ?? "").replace(/\s+/g, " ");

function sections(host: HTMLElement, selector = "section[data-kind]"): string[] {
  return [...host.querySelectorAll(selector)].map((s) => s.getAttribute("data-kind") ?? "");
}

function section(host: HTMLElement, label: string): Element | null {
  return host.querySelector(`section[aria-label="${label}"]`);
}

describe("the screen", () => {
  it("is titled Evidence, opens on the runs, and offers the five tabs and no other control", async () => {
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
    expect(tabs.map((b) => text(b))).toEqual(["Runs", "Gaps", "Spend", "Compare", "Catches"]);
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
    await mount("tab=gaps");
    expect(asked.length).toBeGreaterThan(0);
    for (const { path, init } of asked) {
      expect(path).toMatch(
        /^\/api\/(evidence\/(runs|spend|compare|catches|gaps|tiers)(\/|$)|prices$)/,
      );
      expect(init?.method ?? "GET").toBe("GET");
      expect(init?.body ?? null).toBeNull();
    }
    expect(document.querySelector(".pg-btn-act, .pg-btn-reject, dialog, form")).toBeNull();
  });

  it("shows no headline figure on any tab: every number belongs to one run or one kind", async () => {
    for (const tab of ["runs", "gaps", "spend", "compare", "catches"]) {
      const search = tab === "compare" ? "tab=compare&a=0/ev-development&b=0/ev-ablation" : "";
      const host = await mount(search === "" ? `tab=${tab}` : search);
      expect(host.querySelector(`section[data-tab="${tab}"]`), tab).not.toBeNull();
      expect(text(host).toLowerCase(), tab).not.toMatch(/state[\s-]*of[\s-]*the[\s-]*art/);
      const attributed: string[] = [];
      const loose: string[] = [];
      for (const el of host.querySelectorAll("*")) {
        const own = [...el.childNodes]
          .filter((node) => node.nodeType === Node.TEXT_NODE)
          .map((node) => node.textContent ?? "")
          .join(" ")
          .replace(/\d{4}-\d{2}-\d{2}/g, "");
        if (!/\d/.test(own)) continue;
        const owner = el.closest(
          "[data-source], [data-run], [data-kind], [data-check], table, select, [role='alert']",
        );
        (owner === null ? loose : attributed).push(own.trim());
      }
      expect(loose, `${tab}: a number held by no run and no kind`).toEqual([]);
      expect(attributed.length, `${tab}: the check saw no number at all`).toBeGreaterThan(0);
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
      "0/ev-reportable",
      "0/ev-development",
      "0/ev-drifted",
      "0/ev-ablation",
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

  it("shows every recorded flag and pin as recorded, a nested one by its dotted path, once opened", async () => {
    const host = await mount();
    openSettings(host);
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

  it("keeps two runs of one name under two roots as two distinct, labelled columns", async () => {
    const first = readRow("run-01", "development", "2");
    const second = { ...readRow("run-01", "development", "3"), root: 1 };
    serve({ "/api/evidence/runs": [200, { runs: [first, second] }] });
    const errors = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const host = await mount();
    const heads = [...host.querySelectorAll("th[data-run]")];
    expect(heads.map((h) => h.getAttribute("data-run"))).toEqual(["0/run-01", "1/run-01"]);
    expect(heads.map((h) => text(h.querySelector(".evidence-run-name")))).toEqual([
      "Run r-run-01",
      "Run r-run-01",
    ]);
    expect(text(heads[0])).toContain("Root 0");
    expect(text(heads[1])).toContain("Root 1");
    expect(text(heads[0])).not.toContain("Root 1");
    for (const row of host.querySelectorAll("tbody tr:not(.evidence-group)"))
      expect(row.children.length, text(row)).toBe(3);
    expect(errors.mock.calls.map((c) => String(c[0])).join("\n")).not.toMatch(/same key/);
  });

  it("lists a run it could not read with its record and reason, and none of its settings", async () => {
    const host = await mount();
    const unread = section(host, EVIDENCE_COPY.unread);
    expect(text(unread?.querySelector('[data-run="0/ev-tampered"]'))).toContain(
      `Its run.json could not be read: ${TAMPERED.error}.`,
    );
    expect(text(unread?.querySelector('[data-run="0/ev-unreadable"]'))).toContain(
      `Its events.jsonl could not be read at offset 4211: ${UNREADABLE.error} (unknown kind).`,
    );
    expect(host.querySelector('th[data-run="0/ev-tampered"]')).toBeNull();
  });

  it("keeps two unread runs of one name under two roots apart, by place and in words", async () => {
    const second = { ...TAMPERED, root: 1 };
    serve({ "/api/evidence/runs": [200, { runs: [TAMPERED, second] }] });
    const host = await mount();
    const rows = [...(section(host, EVIDENCE_COPY.unread)?.querySelectorAll("li") ?? [])];
    expect(rows.map((r) => r.getAttribute("data-run"))).toEqual(["0/ev-tampered", "1/ev-tampered"]);
    expect(text(rows[0])).toContain("Root 0");
    expect(text(rows[1])).toContain("Root 1");
  });

  it("says a kind with no run in words, and no longer says the gaps are not on this page", async () => {
    serve({ "/api/evidence/runs": [200, { runs: [readRow("ev-ablation", "ablation", "1")] }] });
    const host = await mount();
    expect(text(section(host, KIND_HEADINGS.reportable))).toContain(EVIDENCE_COPY.noneOfKind);
    expect(text(host)).not.toContain("The two gaps are not on this page yet");
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

  it("says a response was cut off, and not that calls went unpriced, when that alone bounds it", async () => {
    const cut = {
      ...SPEND,
      line: {
        ...SPEND.line,
        reconciliation: { ...SPEND.line.reconciliation, unread: [], seal_broken: [] },
        not_in_binary_totals_billing_unknown: {
          "session:s-1": {
            input_tokens: 2,
            output_tokens: 1,
            cache_read_input_tokens: 0,
            cache_creation_input_tokens: 55515,
          },
        },
      },
    };
    serve({ [SPEND_ROUTE]: [200, cut] });
    const host = await mount("tab=spend&run=0/ev-development");
    const cost = section(host, EVIDENCE_COPY.cost);
    expect(text(cost)).toContain("at least");
    expect(text(cost)).toContain(
      "A response was cut off by a connection error; its tokens are listed separately and the cost shown is a lower bound.",
    );
    expect(text(cost)).not.toContain(EVIDENCE_COPY.lowerBoundLine);
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

  it("names each column's root, so two runs of one name under two roots read apart", async () => {
    const route = "/api/evidence/compare/0/run-01/1/run-01";
    const a = source("run-01", "development", "2");
    const b = { ...source("run-01", "development", "3"), root: 1 };
    serve({
      "/api/evidence/runs": [
        200,
        {
          runs: [
            readRow("run-01", "development", "2"),
            { ...readRow("run-01", "development", "3"), root: 1 },
          ],
        },
      ],
      [route]: [200, { ...COMPARED, a, b }],
    });
    const host = await mount("tab=compare&a=0/run-01&b=1/run-01");
    const heads = [...(host.querySelector("table.evidence-compare thead tr")?.children ?? [])];
    expect(heads.slice(1).map((h) => h.getAttribute("data-run"))).toEqual(["0/run-01", "1/run-01"]);
    expect(text(heads[1])).toContain(`${EVIDENCE_COPY.baseline}: run-01`);
    expect(text(heads[1])).toContain("Root 0");
    expect(text(heads[2])).toContain(`${EVIDENCE_COPY.candidate}: run-01`);
    expect(text(heads[2])).toContain("Root 1");
  });

  it("shows a refusal over drifted settings in words, each setting named, and no number", async () => {
    const host = await mount("tab=compare&a=0/ev-development&b=0/ev-drifted");
    const alert = host.querySelector('[role="alert"]');
    expect(text(alert?.querySelector("h2"))).toBe(EVIDENCE_COPY.driftTitleSettings);
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

  it("shows no total of any count across kinds, whatever element would draw it", async () => {
    // Every count differs from every other and from every sum of two or three of its column's
    // counts, so a number on the page that is such a sum can only be a total across kinds.
    const row = (base: number, name: string) => ({
      ...catchRow("on", null, name, 0),
      checks_run: base + 1,
      blocking_failures: base + 2,
      reviewer_had_passed: base + 3,
      reviewer_had_failed: base + 4,
      no_review: base + 5,
      artefacts_caught: base + 6,
      caught_after_reviewer_passed: base + 7,
    });
    const bases = [100, 200, 400] as const;
    const distinct = {
      ...CATCHES,
      kinds: CATCHES.kinds.map((k, i) => ({
        ...k,
        runs: k.runs.length === 0 ? [source("ev-ablation", "ablation", "1")] : k.runs,
        rows: [row(bases[i] ?? 0, "all")],
      })),
    };
    serve({ "/api/evidence/catches": [200, distinct] });
    const host = await mount("tab=catches");
    expect(sections(host)).toEqual(["reportable", "development", "ablation"]);
    const shown = new Set<string>();
    for (const el of host.querySelectorAll("*")) {
      const own = [...el.childNodes]
        .filter((node) => node.nodeType === Node.TEXT_NODE)
        .map((node) => node.textContent ?? "")
        .join(" ");
      for (const found of own.match(/\d+/g) ?? []) shown.add(found);
    }
    for (const offset of [1, 2, 3, 4, 5, 6, 7]) {
      const [a, b, c] = [bases[0] + offset, bases[1] + offset, bases[2] + offset];
      for (const own of [a, b, c])
        expect(shown.has(String(own)), `a kind's own count ${String(own)}`).toBe(true);
      const totals = [a + b, a + c, b + c, a + b + c];
      for (const total of totals) expect(shown.has(String(total)), String(total)).toBe(false);
    }
    expect(text(host)).not.toMatch(/\b(total|altogether|in all|overall|combined|sum)\b/i);
    expect(host.querySelectorAll("tfoot, [data-total]").length).toBe(0);
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
      "tab=gaps",
    ]) {
      const host = await mount(search);
      expect(host.querySelector("section[data-tab]"), search).not.toBeNull();
      expect(host.innerHTML).not.toContain(CANARY);
      expect(host.innerHTML).not.toContain(DIGEST);
    }
  });
});

describe("the runs read as elsewhere, the settings folded", () => {
  it("names each run as every screen leads it, by its run id, the folder only as its detail", async () => {
    const host = await mount();
    const head = host.querySelector('th[data-run="0/ev-development"]');
    expect(text(head?.querySelector(".evidence-run-name"))).toBe("Run r-ev-development");
    expect(head?.querySelector(".evidence-run-name")?.getAttribute("title")).toBe(
      "folder ev-development",
    );
  });

  it("folds the settings: none shown until asked, with how many there are and how many differ", async () => {
    const host = await mount();
    const reportable = section(host, KIND_HEADINGS.reportable);
    expect(reportable?.querySelectorAll("th .pg-id")).toHaveLength(0);
    const toggle = [...(reportable?.querySelectorAll("button") ?? [])].find((b) =>
      text(b).startsWith("Show the settings"),
    );
    expect(toggle?.getAttribute("aria-expanded")).toBe("false");
    expect(text(toggle)).toMatch(/^Show the settings \(\d+ recorded, \d+ pinned\)$/);
    act(() => {
      toggle?.click();
    });
    expect(toggle?.getAttribute("aria-expanded")).toBe("true");
    expect(reportable?.querySelectorAll("th .pg-id").length).toBeGreaterThan(0);
  });

  it("says which settings differ between the runs of a kind, in words, before they are opened", async () => {
    const host = await mount();
    const development = section(host, KIND_HEADINGS.development);
    expect(text(development?.querySelector(".evidence-differ"))).toMatch(
      /^(No setting differs between these runs\.|\d+ settings? differs? between these runs: .+\.)$/,
    );
  });

  it("says nothing of settings differing in a kind with one run", async () => {
    serve({
      "/api/evidence/runs": [200, { runs: [readRow("ev-reportable", "reportable", "4")] }],
    });
    const host = await mount();
    const reportable = section(host, KIND_HEADINGS.reportable);
    expect(reportable).not.toBeNull();
    expect(reportable?.querySelector(".evidence-differ")).toBeNull();
    expect(text(host)).not.toContain("No setting differs");
  });

  it("writes the OS layer as OS, never Os", async () => {
    const row = readRow("ev-reportable", "reportable", "4");
    const flags = { ...row.flags, os_layer: { state: "present", claude_version: "2.1.301" } };
    serve({ "/api/evidence/runs": [200, { runs: [{ ...row, flags }] }] });
    const host = await mount();
    openSettings(host);
    expect(text(host)).toContain("os_layer");
    expect(text(host)).not.toContain("Os layer");
    expect(text(host)).toContain("OS layer");
  });
});
