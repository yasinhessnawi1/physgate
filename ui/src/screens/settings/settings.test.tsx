// @vitest-environment happy-dom
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { forgetToken, takeTokenFromAddress } from "../../api/client";
import { DisplayProvider } from "../../shell/display";
import type { Header } from "../../shell/header";
import { Shell } from "../../shell/Shell";
import { namesACommand } from "../../rules/commands";
import {
  DESIGN_REVIEW_WORDS,
  OS_LAYER_ABSENT_WORDS,
  PAIR_WORDS,
  QUEUE_DECISION_WORDS,
  SETTINGS_COPY,
} from "../../words/settings";
import type { ViewDef } from "../registry";
import { pairKind } from "./pairs";
import Settings from "./Settings";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// A path, not a URL object: under a simulated DOM, URL is the DOM's own class.
const HERE = dirname(fileURLToPath(import.meta.url));

const SHA = "e".repeat(64);

/** The checkout's own catalogue, as the server read it at start. */
const CATALOGUE = JSON.parse(
  readFileSync(join(HERE, "..", "..", "..", "..", "desktop", "onboarding", "engines.json"), "utf8"),
) as { engines: Record<string, unknown>[] };

const ENGINES = {
  file: "desktop/onboarding/engines.json",
  sha256: SHA,
  length: 2243,
  catalogue: CATALOGUE,
};

/** A run's recorded configuration, as the configuration route sends it, with ``changes``. */
function config(changes: Record<string, unknown> = {}, models?: Record<string, unknown>) {
  return {
    manifest_id: "f".repeat(64),
    repair_budget: 3,
    config: {
      run_id: "run-17",
      seed: 7,
      brief_sha256: "b".repeat(64),
      gate_mode: "observe",
      models: models ?? {
        decomposition: "claude-opus-5-5",
        roles: {
          electrical: "claude-opus-5-5",
          control: "claude-sonnet-5",
          firmware: "claude-sonnet-5",
          mechanical: "claude-opus-5-5",
        },
        reviewers: {
          electrical: "claude-sonnet-5",
          control: "claude-sonnet-5",
          mechanical: "claude-opus-5-5-20261001",
          design: "claude-sonnet-5",
          sizing: "claude-sonnet-5",
        },
      },
      bounds: {
        binary_max_retries: 2,
        session_wall_clock_s: 0.1 + 0.2,
        session_max_turns: 20,
        infra_retry_delays_s: [1, 2.5],
      },
      token_ceiling: 200000,
      claude_version: "2.1.301",
      target_head: "c".repeat(40),
      endpoint: "default",
      auth: "subscription",
      reportable: true,
      harness: { commit: "a1b2c3d4e5f6".padEnd(40, "0"), clean: true, uncommitted_sha256: null },
      effort: "high",
      max_output_tokens: 32000,
      thinking_display: "summarized",
      role_python: {
        path: "/opt/py/bin/python3",
        resolved: "/opt/py/bin/python3.12",
        version: "3.12.9",
        prefix: "/opt/py",
        distributions: [],
      },
      git_binary: { path: "/usr/bin/gitbin", version: "2.47.1" },
      escalation_backend: "rules",
      queue_decisions: "record",
      os_layer_absent: "refuse",
      os_layer: { state: "present", mechanism: "seatbelt", claude_version: "2.1.301" },
      network: "none",
      network_enforced: true,
      design_review: "observe",
      held_out: ["/srv/planted/held-out-root"],
      held_out_canaries: ["CANARY-PLANTED-0001"],
      held_out_sha256: ["9".repeat(64)],
      ...changes,
    },
  };
}

const RUNS = {
  runs: [
    {
      root: 0,
      name: "run-a",
      run_id: "run-a",
      manifest_id: "m",
      gate_mode: "on",
      os_layer: null,
    },
    {
      root: 0,
      name: "run-b",
      run_id: "run-b",
      manifest_id: "m",
      gate_mode: "observe",
      os_layer: null,
    },
  ],
};

const started = (runId: string, ts: string) =>
  JSON.stringify({ seq: 0, ts, kind: "run_started", run_id: runId, gate_mode: "on" });

interface Answer {
  readonly status: number;
  readonly body: string;
}

const json = (body: unknown, status = 200): Answer => ({ status, body: JSON.stringify(body) });

/** What the stub server answers, by path; a path it does not know answers 404. */
function routes(over: Record<string, Answer | "pending"> = {}): Record<string, Answer | "pending"> {
  return {
    "/api/runs": json(RUNS),
    "/api/engines": json(ENGINES),
    "/api/runs/0/run-a/events": { status: 200, body: started("run-a", "2026-10-01T09:00:00Z") },
    "/api/runs/0/run-b/events": { status: 200, body: started("run-b", "2026-11-02T09:00:00Z") },
    "/api/runs/0/run-a/config": json(config({ run_id: "run-a" })),
    "/api/runs/0/run-b/config": json(config()),
    "/api/runs/0/run-a/status": json({ next_step: { kind: "done" }, halted: null }),
    "/api/runs/0/run-b/status": json({ next_step: { kind: "done" }, halted: null }),
    ...over,
  };
}

/** Every request the page made: its method and path. */
let asked: [string, string][] = [];
/** Requests the stub holds unanswered, answered (and so ended) when the test ends. */
let held: (() => void)[] = [];
const roots: Root[] = [];

function serve(table: Record<string, Answer | "pending">) {
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string, init?: RequestInit) => {
      asked.push([init?.method ?? "GET", path]);
      const answer = table[path] ?? json({ error: "no such route in this test" }, 404);
      if (answer === "pending")
        return new Promise<Response>((resolve) => {
          held.push(() => {
            resolve(new Response(JSON.stringify({ error: "ended" }), { status: 503 }));
          });
        });
      return Promise.resolve(new Response(answer.body, { status: answer.status }));
    }),
  );
}

beforeEach(() => {
  asked = [];
  held = [];
  window.localStorage.clear();
});

afterEach(() => {
  act(() => {
    for (const root of roots.splice(0)) root.unmount();
  });
  for (const end of held.splice(0)) end();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  forgetToken();
  document.body.innerHTML = "";
  document.head.innerHTML = "";
  window.location.hash = "";
  window.history.replaceState(null, "", "/");
});

/** Let every answered request reach the page. */
async function settle() {
  for (let i = 0; i < 6; i += 1)
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
}

let headers: Header[] = [];

async function open(
  table: Record<string, Answer | "pending"> = routes(),
  query = "",
): Promise<HTMLElement> {
  serve(table);
  headers = [];
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  roots.push(root);
  act(() => {
    root.render(
      <DisplayProvider>
        <Settings
          setHeader={(h) => {
            headers.push(h);
          }}
          query={new URLSearchParams(query)}
        />
      </DisplayProvider>,
    );
  });
  await settle();
  return host;
}

function section(host: HTMLElement, name: string): HTMLElement {
  const found = host.querySelector<HTMLElement>(`section[aria-label="${name}"]`);
  expect(found, name).not.toBeNull();
  return found ?? document.createElement("section");
}

/** The fact row a section draws for ``field``. */
function fact(where: HTMLElement, field: string): HTMLElement {
  const found = where.querySelector<HTMLElement>(`[data-field="${field}"]`);
  expect(found, field).not.toBeNull();
  return found ?? document.createElement("div");
}

/** What ``el`` reads, without the glossary's explanations its terms carry for hover and focus. */
function text(el: Element | null | undefined): string {
  if (el === null || el === undefined) return "";
  const copy = el.cloneNode(true) as Element;
  for (const tip of copy.querySelectorAll('[role="tooltip"]')) tip.remove();
  return copy.textContent.replace(/\s+/g, " ");
}

const CONTROLS = "a, button, input, select, textarea, summary, details, [tabindex], [role=radio]";

describe("the page", () => {
  it("leads with its sentence, then the five sections in order", async () => {
    const host = await open();
    expect(text(host.querySelector(".pg-screen-lead"))).toBe(SETTINGS_COPY.lede);
    const sections = [...host.querySelectorAll(".pg-settings > section")].map((s) =>
      s.getAttribute("aria-label"),
    );
    expect(sections).toEqual([
      "Engines",
      "Defaults for new runs",
      "System, as the run recorded it",
      "Who decides here",
      "Appearance",
    ]);
  });

  it("names no terminal command, and no credential's state", async () => {
    const host = await open();
    expect(namesACommand(text(host))).toBe(false);
    expect(text(host)).not.toMatch(/signed[\s-]*in|your key|connected|budget/i);
  });
});

describe("Engines: the catalogue, as this checkout lists it", () => {
  it("names its source, the file and its digest, and its size as a quantity", async () => {
    const engines = section(await open(), "Engines");
    expect(text(engines.querySelector(".pg-catalogue-source"))).toContain(
      "this checkout · desktop/onboarding/engines.json",
    );
    expect(text(engines)).toContain(SHA);
    expect(text(engines.querySelector('[data-field="size"] .pg-quantity'))).toBe("2243B");
    expect(engines.getAttribute("data-source")).toContain("desktop/onboarding/engines.json");
  });

  it("draws one row per engine, in the catalogue's order, each led by its name", async () => {
    const engines = section(await open(), "Engines");
    const rows = [...engines.querySelectorAll(".pg-engine")];
    expect(rows.map((r) => r.getAttribute("data-engine"))).toEqual(
      CATALOGUE.engines.map((e) => e.id),
    );
    expect(text(rows[0]?.querySelector(".pg-engine-name"))).toBe("Claude Code");
    expect(text(rows[0])).toContain("Runs sign in with your Claude subscription.");
    expect(text(rows[0])).toContain("Claude subscription");
  });

  it("marks an available engine Available, and a not-yet one Not yet, dashed and neutral", async () => {
    const engines = section(await open(), "Engines");
    const code = engines.querySelector('[data-engine="claude-code"]');
    expect(code?.querySelector('[data-status-kind="engine-available"]')).not.toBeNull();
    const openai = engines.querySelector('[data-engine="openai"]');
    const tag = openai?.querySelector('[data-status-kind="engine-not-yet"]');
    expect(tag?.className).toBe("pg-status pg-status-dashed");
    expect(text(tag)).toBe("Not yet");
    expect(engines.innerHTML).not.toMatch(/pg-verdict|[✓✕]/);
  });

  it("an engine's row holds no control at all, and a not-yet one is not a choice", async () => {
    const engines = section(await open(), "Engines");
    for (const row of engines.querySelectorAll(".pg-engine"))
      expect(row.querySelectorAll(CONTROLS), row.getAttribute("data-engine") ?? "").toHaveLength(0);
  });

  it("shows a status it does not know as written, and keeps that engine inert", async () => {
    const catalogue = {
      engines: [
        { id: "a", name: "Engine A", status: "available" },
        { id: "b", name: "Engine B", status: "available — not for evaluation" },
        { id: "c", name: "Engine C" },
      ],
    };
    const host = await open(routes({ "/api/engines": json({ ...ENGINES, catalogue }) }));
    const b = section(host, "Engines").querySelector('[data-engine="b"]');
    expect(text(b?.querySelector(".pg-as-written"))).toBe("available — not for evaluation");
    expect(b?.querySelector("[data-status-kind]")).toBeNull();
    expect(text(section(host, "Engines").querySelector('[data-engine="c"]'))).toContain(
      SETTINGS_COPY.noStatus,
    );
    const cards = section(host, "Defaults for new runs").querySelectorAll('input[type="radio"]');
    expect([...cards].map((c) => c.getAttribute("value"))).toEqual(["a"]);
  });

  it("an entry it cannot read is a row with its reason, and the others render", async () => {
    const catalogue = {
      engines: [{ id: "a", name: "Engine A" }, { id: 7 }, { id: "c", name: "C" }],
    };
    const host = await open(routes({ "/api/engines": json({ ...ENGINES, catalogue }) }));
    const rows = [...section(host, "Engines").querySelectorAll(".pg-engine")];
    expect(rows).toHaveLength(3);
    expect(text(rows[1])).toBe("This entry could not be read: its id is not text.");
    expect(text(rows[2])).toContain("C");
  });

  it("lists an engine's models with the catalogue's own defaults, never a run's", async () => {
    const engines = section(await open(), "Engines");
    const api = engines.querySelector('[data-engine="claude-api"]');
    const models = [...(api?.querySelectorAll(".pg-engine-model") ?? [])].map(text);
    expect(models).toEqual([
      "Claude Opus 5.5 claude-opus-5-5 · default builder",
      "Claude Sonnet 5 claude-sonnet-5 · default reviewer",
      "Claude Haiku 4.5 claude-haiku-4-5-20251001",
    ]);
    expect(text(engines)).not.toMatch(/this run/i);
  });

  it("folds the local models, with their sizes as approximate quantities and their source as text", async () => {
    const engines = section(await open(), "Engines");
    const fold = engines.querySelector("details.pg-local-models");
    expect(text(fold?.querySelector("summary"))).toBe(SETTINGS_COPY.localModels);
    expect(fold?.hasAttribute("open")).toBe(false);
    const heads = [...(fold?.querySelectorAll("th") ?? [])].map(text);
    expect(heads).toEqual([
      "Model",
      "Memory, approximate",
      "Disk, approximate",
      "Licence",
      "Source",
    ]);
    const first = fold?.querySelector("tbody tr");
    expect([...(first?.querySelectorAll(".pg-quantity") ?? [])].map(text)).toEqual(["6GB", "5GB"]);
    expect(text(first)).toContain("https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct");
    expect(fold?.querySelectorAll("a")).toHaveLength(0);
    expect(fold?.closest(".pg-engine")).toBeNull();
  });

  it("says where the engine is chosen, and that runs use their own parameters", async () => {
    expect(text(section(await open(), "Engines"))).toContain(SETTINGS_COPY.engineChosenWhere);
  });

  it("with no catalogue, says so, and the defaults still render with nothing to choose", async () => {
    const host = await open(
      routes({ "/api/engines": json({ error: "this checkout lists no engines" }, 404) }),
    );
    const engines = section(host, "Engines");
    expect(engines.querySelector(".pg-state-empty")?.getAttribute("aria-label")).toBe(
      SETTINGS_COPY.enginesEmpty,
    );
    expect(engines.querySelector('[role="alert"]')).toBeNull();
    const defaults = section(host, "Defaults for new runs");
    expect(text(defaults)).toContain(SETTINGS_COPY.noEngineToChoose);
    expect(defaults.querySelectorAll('input[type="radio"]')).toHaveLength(0);
    expect(
      section(host, "System, as the run recorded it").querySelector(".pg-facts"),
    ).not.toBeNull();
  });

  it("a refused catalogue is the section's error, with its reason, and nothing of it partial", async () => {
    const reason = "the engine catalogue could not be read: it repeats the key 'id'";
    const host = await open(routes({ "/api/engines": json({ error: reason }, 422) }));
    const engines = section(host, "Engines");
    const error = engines.querySelector('[role="alert"]');
    expect(error?.getAttribute("aria-label")).toBe(SETTINGS_COPY.enginesError);
    expect(text(error)).toContain(reason);
    expect(text(error)).toContain("422");
    expect(text(error)).toContain("/api/engines");
    expect(error?.querySelector("button.pg-state-retry")).not.toBeNull();
    expect(engines.querySelectorAll(".pg-engine, .pg-catalogue-source")).toHaveLength(0);
    expect(
      section(host, "System, as the run recorded it").querySelector(".pg-facts"),
    ).not.toBeNull();
  });

  it("an answer of the wrong shape is the section's error too", async () => {
    const host = await open(routes({ "/api/engines": json({ ...ENGINES, sha256: "x" }) }));
    expect(section(host, "Engines").querySelector('[role="alert"]')).not.toBeNull();
  });

  it("while it is read, says what it reads, and the other sections render", async () => {
    const host = await open(routes({ "/api/engines": "pending" }));
    const loading = section(host, "Engines").querySelector('[aria-busy="true"]');
    expect(text(loading)).toContain("Reading the engines this checkout lists…");
    expect(
      section(host, "System, as the run recorded it").querySelector(".pg-facts"),
    ).not.toBeNull();
  });
});

describe("Defaults for new runs: drawn, disabled, and set nowhere", () => {
  it("every control is disabled, holds no value and presses nothing", async () => {
    const defaults = section(await open(), "Defaults for new runs");
    const controls = [
      ...defaults.querySelectorAll(".pg-facts input, .pg-facts select, .pg-facts button"),
    ];
    expect(controls.length).toBeGreaterThanOrEqual(2 + 2 + 3 + 1);
    for (const control of controls)
      expect((control as HTMLInputElement).disabled, control.outerHTML).toBe(true);
    for (const radio of defaults.querySelectorAll<HTMLInputElement>('input[type="radio"]'))
      expect(radio.checked).toBe(false);
    for (const select of defaults.querySelectorAll("select")) expect(select.value).toBe("");
    expect(defaults.querySelector<HTMLInputElement>('input[type="number"]')?.value).toBe("");
    expect(defaults.querySelector('[aria-pressed="true"]')).toBeNull();
    expect(defaults.querySelector("[checked], [selected]:not([value=''])")).toBeNull();
  });

  it("every control says what sets its value today, through its description", async () => {
    const defaults = section(await open(), "Defaults for new runs");
    const said = (field: string) => {
      const controls = [...fact(defaults, field).querySelectorAll("input, select, button")];
      expect(controls.length, field).toBeGreaterThan(0);
      return controls.map((c) => {
        const id = c.getAttribute("aria-describedby") ?? "";
        return text(defaults.querySelector(`[id="${id}"]`));
      });
    };
    for (const [field, sentence] of [
      ["engine", SETTINGS_COPY.defaultEngine],
      ["builder", SETTINGS_COPY.defaultBuilder],
      ["reviewer", SETTINGS_COPY.defaultReviewer],
      ["gate-mode", SETTINGS_COPY.defaultGateMode],
      ["token-ceiling", SETTINGS_COPY.defaultTokenCeiling],
    ] as const)
      for (const s of said(field)) expect(s, field).toBe(sentence);
  });

  it("offers the available engines as cards, and the catalogue's models with no default kept", async () => {
    const defaults = section(await open(), "Defaults for new runs");
    const cards = [...defaults.querySelectorAll('input[type="radio"]')];
    expect(cards.map((c) => c.getAttribute("value"))).toEqual(["claude-code", "claude-api"]);
    const builder = fact(defaults, "builder").querySelector("select");
    expect([...(builder?.options ?? [])].map((o) => o.textContent)).toEqual([
      SETTINGS_COPY.noDefaultKept,
      "Claude Opus 5.5",
      "Claude Sonnet 5",
      "Claude Haiku 4.5",
    ]);
    expect(text(fact(defaults, "reviewer"))).toContain(SETTINGS_COPY.reviewerMustDiffer);
    const gate = [...fact(defaults, "gate-mode").querySelectorAll("button")].map(text);
    expect(gate).toEqual(["On", "Observe", "Off"]);
    const ceiling = fact(defaults, "token-ceiling");
    expect(text(ceiling.querySelector("label, dt"))).toContain(SETTINGS_COPY.tokenCeiling);
    expect(text(ceiling)).toContain("tokens");
    expect(text(defaults)).not.toMatch(/budget|USD/i);
  });

  it("nothing on the screen acts: no act, no '…' label, no confirmation, in source or drawn", async () => {
    const host = await open();
    expect(host.querySelectorAll(".pg-btn-act, .pg-btn-reject, dialog")).toHaveLength(0);
    for (const button of host.querySelectorAll("button"))
      expect(text(button).trim().endsWith("…"), text(button)).toBe(false);
    const folder = HERE;
    for (const name of readdirSync(folder).filter((n) => !n.includes(".test.")))
      expect(readFileSync(join(folder, name), "utf8"), name).not.toMatch(
        /variant="act"|variant: "act"|ConfirmDialog|pg-btn-act|postAction/,
      );
  });
});

describe("System, as the run recorded it", () => {
  it("draws the engine facts as recorded", async () => {
    const system = section(await open(), "System, as the run recorded it");
    expect(text(fact(system, "auth"))).toContain("Claude subscription");
    expect(text(fact(system, "endpoint"))).toContain(SETTINGS_COPY.endpointDefault);
    expect(text(fact(system, "claude-version"))).toContain("2.1.301");
    expect(text(fact(system, "effort"))).toContain("High");
    expect(text(fact(system, "max-output-tokens").querySelector(".pg-quantity"))).toBe(
      "32000tokens",
    );
    expect(text(fact(system, "thinking-display"))).toContain(
      "Summarised in each session's transcript, which its reviewer reads",
    );
    const git = text(fact(system, "git-binary"));
    expect(git.indexOf("2.47.1")).toBeLessThan(git.indexOf("/usr/bin/gitbin"));
    const python = text(fact(system, "role-python"));
    expect(python).toContain("/opt/py/bin/python3");
    expect(python).toContain("3.12.9");
    expect(python).toContain("/opt/py/bin/python3.12");
    expect(python).not.toContain("/opt/py ");
    expect(text(fact(system, "engine"))).toContain("not recorded by this run");
  });

  it("names its source: the run and its commit; every quantity is inside it", async () => {
    const system = section(await open(), "System, as the run recorded it");
    const chip = system.querySelector(".pg-source");
    expect(chip?.getAttribute("aria-label")).toBe("Source: run run-17 at commit a1b2c3d");
    for (const q of system.querySelectorAll(".pg-quantity"))
      expect(q.closest("[data-source]")?.getAttribute("data-source")).toBe("run run-17@a1b2c3d");
  });

  it("draws every session limit as a quantity in its unit, unrounded", async () => {
    const system = section(await open(), "System, as the run recorded it");
    const limit = (field: string) =>
      [...fact(system, field).querySelectorAll(".pg-quantity")].map(text);
    expect(limit("token-ceiling")).toEqual(["200000tokens"]);
    expect(limit("wall-clock")).toEqual(["0.30000000000000004s"]);
    expect(limit("turns")).toEqual(["20turns"]);
    expect(limit("retries")).toEqual(["2retries"]);
    expect(limit("delays")).toEqual(["1s", "2.5s"]);
    expect(text(fact(system, "token-ceiling"))).toContain(SETTINGS_COPY.tokenCeiling);
  });

  it("says a run with no retry delays has none", async () => {
    const bounds = {
      binary_max_retries: 0,
      session_wall_clock_s: 120,
      session_max_turns: 1,
      infra_retry_delays_s: [],
    };
    const system = section(
      await open(routes({ "/api/runs/0/run-b/config": json(config({ bounds })) })),
      "System, as the run recorded it",
    );
    expect(text(fact(system, "delays"))).toContain(SETTINGS_COPY.noDelays);
    expect(text(fact(system, "wall-clock"))).toContain("120s");
  });

  function pairs(host: HTMLElement): string[][] {
    const table = section(host, "System, as the run recorded it").querySelector(
      'table[aria-label="Who built and who reviewed"]',
    );
    expect(table).not.toBeNull();
    return [...(table?.querySelectorAll("tbody tr") ?? [])].map((tr) =>
      [...tr.querySelectorAll("td")].map(text),
    );
  }

  it("shows each role's builder and reviewer side by side, and compares the two strings", async () => {
    const rows = pairs(await open());
    expect(rows).toEqual([
      ["Electrical electrical", "claude-opus-5-5", "claude-sonnet-5", PAIR_WORDS.different],
      ["Control control", "claude-sonnet-5", "claude-sonnet-5", PAIR_WORDS.same],
      [
        "Firmware firmware",
        "claude-sonnet-5",
        SETTINGS_COPY.noReviewer,
        SETTINGS_COPY.nothingToCompare,
      ],
      [
        "Mechanical mechanical",
        "claude-opus-5-5",
        "claude-opus-5-5-20261001",
        PAIR_WORDS.different,
      ],
      [SETTINGS_COPY.decomposition, "claude-opus-5-5", "claude-sonnet-5", PAIR_WORDS.different],
      [
        "sizing",
        "",
        `claude-sonnet-5 ${SETTINGS_COPY.unknownReviewerKey}`,
        SETTINGS_COPY.nothingToCompare,
      ],
    ]);
  });

  it("a pair with the same string is a neutral sentence, never a verdict", async () => {
    const system = section(await open(), "System, as the run recorded it");
    const same = system.querySelector('[data-status-kind="pair-same-string"]');
    expect(same?.className).toBe("pg-status");
    expect(system.innerHTML).not.toMatch(/pg-verdict|pg-observed|[✓✕]/);
    expect(text(system.querySelector(".pg-pairs-note"))).toBe(SETTINGS_COPY.pairsNote);
  });

  it("compares the recorded strings, and nothing else", () => {
    expect(pairKind("claude-opus-5-5", "claude-opus-5-5")).toBe("pair-same-string");
    expect(pairKind("claude-opus-5-5", "claude-opus-5-5-20261001")).toBe("pair-different-strings");
    expect(pairKind("claude-opus-5-5", "anthropic/claude-opus-5.5")).toBe("pair-different-strings");
    expect(pairKind("claude-opus-5-5", "Claude-Opus-5-5")).toBe("pair-different-strings");
  });

  it("with no plan reviewer pinned, the decomposition row says so", async () => {
    const models = {
      decomposition: "claude-opus-5-5",
      roles: { electrical: "claude-opus-5-5" },
      reviewers: { electrical: "claude-sonnet-5" },
    };
    const rows = pairs(
      await open(routes({ "/api/runs/0/run-b/config": json(config({}, models)) })),
    );
    expect(rows.at(-1)).toEqual([
      SETTINGS_COPY.decomposition,
      "claude-opus-5-5",
      SETTINGS_COPY.noPlanReviewer,
      SETTINGS_COPY.nothingToCompare,
    ]);
  });

  it("roles that are not a record refuse the table's body, and the decomposition row stands", async () => {
    const models = { decomposition: "claude-opus-5-5", roles: ["electrical"], reviewers: {} };
    const host = await open(routes({ "/api/runs/0/run-b/config": json(config({}, models)) }));
    const rows = pairs(host);
    expect(rows.map((r) => r[0])).toEqual([SETTINGS_COPY.decomposition]);
    expect(
      text(section(host, "System, as the run recorded it").querySelector(".pg-pairs")),
    ).toContain("This value could not be read: it is not a record.");
  });

  it("one wrong field refuses its own row, and the rest of the card renders", async () => {
    const host = await open(routes({ "/api/runs/0/run-b/config": json(config({ effort: 1 })) }));
    const system = section(host, "System, as the run recorded it");
    expect(system.querySelectorAll(".pg-refused")).toHaveLength(1);
    expect(text(fact(system, "effort"))).toContain("This value could not be read: it is not text.");
    expect(text(fact(system, "auth"))).toContain("Claude subscription");
    expect(text(fact(system, "token-ceiling"))).toContain("200000");
    expect(pairs(host).length).toBeGreaterThan(0);
  });

  it("a field the run did not record reads so, and is never filled from the catalogue", async () => {
    const answer = config();
    const recorded = answer.config as Record<string, unknown>;
    delete recorded.models;
    delete recorded.design_review;
    delete recorded.effort;
    const system = section(
      await open(routes({ "/api/runs/0/run-b/config": json(answer) })),
      "System, as the run recorded it",
    );
    expect(text(fact(system, "effort"))).toContain(SETTINGS_COPY.notRecorded);
    expect(text(fact(system, "design-review"))).toContain(SETTINGS_COPY.notRecorded);
    expect(text(system.querySelector(".pg-pairs"))).toContain(SETTINGS_COPY.notRecorded);
    expect(text(system)).not.toMatch(
      /claude-opus-5-5|claude-sonnet-5|default builder|default reviewer/,
    );
  });

  it("shows a value it has no words for as written, and never as a known word", async () => {
    const system = section(
      await open(
        routes({
          "/api/runs/0/run-b/config": json(config({ effort: "turbo", network: "loopback" })),
        }),
      ),
      "System, as the run recorded it",
    );
    expect(text(fact(system, "effort").querySelector(".pg-as-written"))).toBe("turbo");
    expect(text(fact(system, "effort"))).not.toMatch(/High|Maximum|Low|Medium/);
    expect(text(fact(system, "network").querySelector(".pg-as-written"))).toBe("loopback");
  });

  it.each([
    [
      {
        os_layer: { state: "present", mechanism: "seatbelt", claude_version: "2" },
        network: "none",
        network_enforced: true,
      },
      "OS layer · Seatbelt",
      "None, enforced by the OS layer",
    ],
    [
      {
        os_layer: {
          state: "absent",
          reason: "macOS: sandbox-exec is missing",
          no_os_protection: false,
        },
        network: "none",
        network_enforced: false,
      },
      "OS layer absent",
      "None requested, not enforceable here",
    ],
    [
      { os_layer: null, network: "none", network_enforced: null },
      "OS layer not recorded",
      "None, not measured",
    ],
    [{ os_layer: null, network: "open", network_enforced: null }, "OS layer not recorded", "Open"],
  ])("draws the OS layer and the network as recorded: %j", async (changes, layer, network) => {
    const system = section(
      await open(routes({ "/api/runs/0/run-b/config": json(config(changes)) })),
      "System, as the run recorded it",
    );
    expect(text(fact(system, "os-layer"))).toContain(layer);
    expect(text(fact(system, "network"))).toContain(network);
  });

  it("an absent OS layer is loud, with its reason as written", async () => {
    const system = section(
      await open(
        routes({
          "/api/runs/0/run-b/config": json(
            config({
              os_layer: {
                state: "absent",
                reason: "macOS: sandbox-exec is missing",
                no_os_protection: false,
              },
            }),
          ),
        }),
      ),
      "System, as the run recorded it",
    );
    expect(fact(system, "os-layer").querySelector(".pg-os-layer-absent")).not.toBeNull();
    expect(text(fact(system, "os-layer"))).toContain("macOS: sandbox-exec is missing");
  });

  it("says what the queue and the OS-layer switch mean for this run", async () => {
    const system = section(
      await open(
        routes({
          "/api/runs/0/run-b/config": json(
            config({ queue_decisions: "act", os_layer_absent: "allow" }),
          ),
        }),
      ),
      "System, as the run recorded it",
    );
    expect(text(fact(system, "queue-decisions"))).toContain(QUEUE_DECISION_WORDS.act);
    expect(text(fact(system, "os-layer-absent"))).toContain(OS_LAYER_ABSENT_WORDS.allow);
    expect(text(fact(system, "design-review"))).toContain(DESIGN_REVIEW_WORDS.observe);
    expect(text(fact(system, "escalation"))).toContain("rules");
    expect(text(fact(system, "gate-mode"))).toContain("Observe · not gated");
  });

  it("says whether the run's numbers may be reported, and where its full record is", async () => {
    const system = section(await open(), "System, as the run recorded it");
    expect(text(fact(system, "reportable"))).toContain(SETTINGS_COPY.reportableYes);
    const link = system.querySelector<HTMLAnchorElement>("a.pg-full-record");
    expect(text(link)).toBe(SETTINGS_COPY.fullRecord);
    expect(link?.getAttribute("href")).toBe("#/home/run-records?run=0%2Frun-b");
  });

  it("never draws a value of the held-out keys", async () => {
    const host = await open();
    const all = host.innerHTML;
    for (const value of ["/srv/planted/held-out-root", "CANARY-PLANTED-0001", "9".repeat(64)])
      expect(all).not.toContain(value);
  });

  it("opens on the newest run, and reads only its configuration and status", async () => {
    await open();
    const configs = asked.filter(([, p]) => p.endsWith("/config") || p.endsWith("/status"));
    expect(configs).toEqual([
      ["GET", "/api/runs/0/run-b/config"],
      ["GET", "/api/runs/0/run-b/status"],
    ]);
  });

  it("opens on the run the address names", async () => {
    await open(routes(), "run=0/run-a");
    expect(asked.filter(([, p]) => p.endsWith("/config"))).toEqual([
      ["GET", "/api/runs/0/run-a/config"],
    ]);
  });

  it("a refused configuration is the section's error, with nothing of it partial", async () => {
    const reason = "the run's configuration could not be read";
    const host = await open(routes({ "/api/runs/0/run-b/config": json({ error: reason }, 422) }));
    const system = section(host, "System, as the run recorded it");
    expect(system.querySelector('[role="alert"]')?.getAttribute("aria-label")).toBe(
      SETTINGS_COPY.systemError,
    );
    expect(text(system.querySelector('[role="alert"]'))).toContain("/api/runs/0/run-b/config");
    expect(system.querySelectorAll(".pg-facts, table")).toHaveLength(0);
    expect(section(host, "Engines").querySelectorAll(".pg-engine").length).toBeGreaterThan(0);
  });

  it("with no run yet, says so, and the other sections render", async () => {
    const host = await open(routes({ "/api/runs": json({ runs: [] }) }));
    const system = section(host, "System, as the run recorded it");
    expect(system.querySelector(".pg-state-empty")?.getAttribute("aria-label")).toBe(
      SETTINGS_COPY.systemEmpty,
    );
    expect(text(system)).toContain(SETTINGS_COPY.systemEmptyBody);
    expect(section(host, "Engines").querySelectorAll(".pg-engine").length).toBeGreaterThan(0);
    expect(headers.at(-1)).toEqual({ title: "Settings", runState: "none" });
  });

  it("while the run is read, says what it reads", async () => {
    const host = await open(routes({ "/api/runs/0/run-b/config": "pending" }));
    expect(
      text(section(host, "System, as the run recorded it").querySelector('[aria-busy="true"]')),
    ).toContain("Reading the run's recorded configuration…");
  });
});

describe("the top bar follows the chosen run, from what it recorded", () => {
  it("names the run, its source, its gate mode and its OS layer", async () => {
    await open();
    expect(headers.at(-1)).toMatchObject({
      title: "Settings",
      source: { id: "run run-17", commit: "a1b2c3d4e5f6".padEnd(40, "0") },
      gateMode: "observe",
      osLayer: { state: "present", mechanism: "seatbelt" },
      inProgress: false,
    });
    expect(headers.at(-1)?.run?.label).toMatch(/^Run /);
  });

  it("a refused field leaves out only its own part of the chip", async () => {
    await open(
      routes({ "/api/runs/0/run-b/config": json(config({ run_id: 5, gate_mode: "audit" })) }),
    );
    const last = headers.at(-1);
    expect(last?.source).toBeUndefined();
    expect(last?.gateMode).toBeUndefined();
    expect(last?.osLayer).toEqual({ state: "present", mechanism: "seatbelt" });
  });
});

describe("Who decides here", () => {
  function operator(name: string) {
    const meta = document.createElement("meta");
    meta.name = "physgate-operator";
    meta.content = name;
    document.head.append(meta);
  }

  it("with an operator and the operator's address: recorded as them, and this window can decide", async () => {
    operator("Yasin K.");
    window.history.replaceState(null, "", "/#act=PLANTED-TOKEN-0123456789");
    takeTokenFromAddress();
    const who = section(await open(), "Who decides here");
    expect(text(who)).toContain("Decisions taken in this window are recorded as Yasin K.");
    expect(text(who)).toContain(SETTINGS_COPY.canDecide);
    expect(text(who)).toContain(SETTINGS_COPY.operatorWhere);
    expect(document.body.innerHTML).not.toMatch(/PLANTED|TOKEN-0123|0123456789/);
  });

  it("with an operator and no token: it can only read", async () => {
    operator("Yasin K.");
    const who = section(await open(), "Who decides here");
    expect(text(who)).toContain(SETTINGS_COPY.cannotDecide);
    expect(text(who)).not.toContain(SETTINGS_COPY.canDecide);
  });

  it("with no operator: read-only, said so", async () => {
    const who = section(await open(), "Who decides here");
    expect(text(who)).toContain(SETTINGS_COPY.noOperator);
    expect(text(who)).toContain(SETTINGS_COPY.operatorWhere);
  });
});

describe("Appearance: the viewer's own choices, shared with the top bar", () => {
  it("offers theme and density, pressing the choices made, and says where they are kept", async () => {
    const look = section(await open(), "Appearance");
    const theme = look.querySelector('[role="group"][aria-label="Theme"]');
    expect([...(theme?.querySelectorAll("button") ?? [])].map(text)).toEqual([
      "Light",
      "Dark",
      "Follow the system",
    ]);
    expect(text(theme?.querySelector('[aria-pressed="true"]'))).toBe("Follow the system");
    const density = look.querySelector('[role="group"][aria-label="Density"]');
    expect(text(density?.querySelector('[aria-pressed="true"]'))).toBe("Compact");
    expect(text(look)).toContain(SETTINGS_COPY.keptHere);
  });

  it("a choice made here is drawn and kept", async () => {
    const look = section(await open(), "Appearance");
    act(() => {
      [...look.querySelectorAll<HTMLButtonElement>('[aria-label="Theme"] button')]
        .find((b) => b.textContent === "Dark")
        ?.click();
    });
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(window.localStorage.getItem("physgate.theme")).toBe("dark");
    act(() => {
      [...look.querySelectorAll<HTMLButtonElement>('[aria-label="Density"] button')]
        .find((b) => b.textContent === "Comfortable")
        ?.click();
    });
    expect(document.documentElement.dataset.density).toBe("comfortable");
    expect(window.localStorage.getItem("physgate.density")).toBe("comfortable");
  });

  it("a theme the address fixes disables the theme control, and says so", async () => {
    window.history.replaceState(null, "", "/?theme=dark");
    const look = section(await open(), "Appearance");
    const buttons = [...look.querySelectorAll<HTMLButtonElement>('[aria-label="Theme"] button')];
    expect(buttons.every((b) => b.disabled)).toBe(true);
    const id = look.querySelector('[aria-label="Theme"]')?.getAttribute("aria-describedby") ?? "";
    expect(text(look.querySelector(`[id="${id}"]`))).toBe("Fixed to dark by this page's address");
    expect(
      [...look.querySelectorAll<HTMLButtonElement>('[aria-label="Density"] button')].some(
        (b) => b.disabled,
      ),
    ).toBe(false);
  });

  it("renders on the defaults when the storage throws", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const look = section(await open(), "Appearance");
    expect(text(look.querySelector('[aria-label="Theme"] [aria-pressed="true"]'))).toBe(
      "Follow the system",
    );
  });

  it("inside the shell, the top bar and this section change the same choice, both ways", async () => {
    serve(routes());
    const view: ViewDef = {
      group: "settings",
      area: "home",
      slug: "settings",
      title: "Settings",
      icon: "settings",
      component: Settings,
    };
    window.location.hash = "#/home/settings";
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    roots.push(root);
    act(() => {
      root.render(<Shell views={[view]} />);
    });
    await settle();
    const look = section(host, "Appearance");
    act(() => {
      [...look.querySelectorAll<HTMLButtonElement>('[aria-label="Theme"] button')]
        .find((b) => b.textContent === "Dark")
        ?.click();
    });
    expect(host.querySelector('button[title^="Theme"]')?.getAttribute("title")).toBe(
      "Theme: Dark. Change it",
    );
    act(() => {
      host.querySelector<HTMLButtonElement>('button[title^="Density"]')?.click();
    });
    expect(text(look.querySelector('[aria-label="Density"] [aria-pressed="true"]'))).toBe(
      "Comfortable",
    );
  });
});

describe("what the screen asks the server", () => {
  it("only GETs, and only the run list, each listed run's log, the chosen run's configuration and status, and the catalogue", async () => {
    await open();
    expect(asked.every(([method]) => method === "GET")).toBe(true);
    // Each run's log is read once per page for its label, so a later test may find it read.
    const allowed = new Set([
      "/api/runs",
      "/api/engines",
      "/api/runs/0/run-a/events",
      "/api/runs/0/run-b/events",
      "/api/runs/0/run-b/config",
      "/api/runs/0/run-b/status",
    ]);
    const paths = asked.map(([, p]) => p);
    expect(paths.filter((p) => !allowed.has(p))).toEqual([]);
    for (const p of [
      "/api/runs",
      "/api/engines",
      "/api/runs/0/run-b/config",
      "/api/runs/0/run-b/status",
    ])
      expect(
        paths.filter((q) => q === p),
        p,
      ).toHaveLength(1);
  });
});
