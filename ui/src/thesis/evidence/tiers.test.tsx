// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ShapeError } from "../../api/client";
import {
  CANARY,
  CURRENT_VERSION,
  DIGEST,
  GAPS,
  NO_FRESH,
  NO_TIERS,
  READ_AT,
  RUNS,
  TIERS,
  tierRole,
} from "./answers";
import { evidenceTiers, GAPS_ROUTE, TIERS_ROUTE } from "./api";
import Evidence from "./Evidence";
import { EVIDENCE_COPY } from "./words";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

type Answer = readonly [number, unknown];

let answers: Record<string, Answer> = {};

function serve(over: Record<string, Answer> = {}) {
  answers = {
    "/api/evidence/runs": [200, RUNS],
    [GAPS_ROUTE]: [200, GAPS],
    [TIERS_ROUTE]: [200, TIERS],
    ...over,
  };
}

beforeEach(() => {
  serve();
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string) => {
      const [status, body] = answers[input] ?? [404, { error: "no such route" }];
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
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

async function mount(search = "tab=gaps"): Promise<HTMLElement> {
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
  for (let i = 0; i < 8; i += 1)
    await act(async () => {
      await Promise.resolve();
    });
  return host;
}

const text = (el: Element | null | undefined) => (el?.textContent ?? "").replace(/\s+/g, " ");

function card(host: HTMLElement, role: string): Element | null {
  return host.querySelector(`[data-tier-role="${role}"]`);
}

function withControl(over: Record<string, unknown>) {
  return { roles: [tierRole(over), TIERS.roles[1]] };
}

/** ``value`` with ``key`` at ``path`` set to ``to`` (a copy). */
function edited(path: readonly string[], to: unknown) {
  const control = JSON.parse(JSON.stringify(tierRole())) as Record<string, unknown>;
  let at: Record<string, unknown> = control;
  for (const key of path.slice(0, -1)) at = at[key] as Record<string, unknown>;
  at[path[path.length - 1] ?? ""] = to;
  return { roles: [control, TIERS.roles[1]] };
}

describe("the tier versions' guard", () => {
  it("takes the answer whole: each role in order, with its state", () => {
    const status = evidenceTiers(TIERS);
    expect(status.roles.map((r) => [r.role, r.state])).toEqual([
      ["control", "read"],
      ["firmware", "refused"],
    ]);
    const control = status.roles[0];
    if (control?.state !== "read") throw new Error("control is not read");
    expect(control.counts).toEqual({ visible: 8, validation: 8, heldOut: 8 });
    expect(control.check).toEqual({
      state: "read",
      tasks: 8,
      allYes: 7,
      leftOut: 1,
      source: "check",
    });
    expect(evidenceTiers(NO_TIERS).roles.map((r) => r.state)).toEqual(["none", "none"]);
  });

  it.each([
    ["a key it does not know", edited(["store"], "/srv/held_out")],
    ["a key it does not know in the counts", edited(["counts", "path"], "/srv/held_out")],
    ["a key it does not know in the check", edited(["check", "digest"], DIGEST)],
    ["a string where a count belongs", edited(["counts", "held_out"], "8")],
    ["a flag where a count belongs", edited(["counts", "visible"], true)],
    ["a count where the flag belongs", edited(["measured"], 1)],
    ["a check whose counts are not every task", edited(["check", "left_out"], 2)],
    ["a check of another number of tasks than the tier", edited(["counts", "held_out"], 9)],
    ["an exposed version said to be fresh", edited(["exposure"], "exposed")],
    ["an exposure word it does not know", edited(["exposure"], "a little")],
    ["a state word it does not know", edited(["version_state"], "current")],
    ["a check source it does not know", edited(["check", "source"], "a person")],
    ["a version that is no id", edited(["version"], "/srv/held_out/task.json")],
    ["a role it does not know", edited(["role"], "whole_run")],
    ["a role twice", { roles: [tierRole(), tierRole()] }],
  ])("refuses %s, and never a part of the answer", (_, value) => {
    expect(() => evidenceTiers(value)).toThrow(ShapeError);
  });
});

describe("the tier versions on the page", () => {
  it("heads the Gaps tab, read from its own route, one card per role", async () => {
    const host = await mount();
    const panel = host.querySelector('section[data-tab="gaps"] > section[data-panel="tiers"]');
    expect(panel).not.toBeNull();
    expect(host.querySelector('section[data-tab="gaps"]')?.firstElementChild).toBe(panel);
    expect(text(panel?.querySelector("h2"))).toBe(EVIDENCE_COPY.tierPanelTitle);
    const cards = [...host.querySelectorAll("[data-tier-role]")];
    expect(cards.map((c) => c.getAttribute("data-tier-role"))).toEqual(["control", "firmware"]);
    // The gap trend's two role sections are still the tab's own, beside the cards.
    expect(host.querySelectorAll("section[data-role]").length).toBe(2);
  });

  it("says the published version's facts in words", async () => {
    const host = await mount();
    const control = card(host, "control");
    expect(text(control?.querySelector('[data-fact="version"]'))).toContain(
      CURRENT_VERSION.slice(0, 8),
    );
    expect(control?.querySelector(`[aria-label="Copy ${CURRENT_VERSION}"]`)).not.toBeNull();
    expect(text(control?.querySelector('[data-fact="counts"]'))).toBe(
      "8 visible · 8 validation · 8 held-out tasks",
    );
    expect(text(control?.querySelector('[data-fact="check"]'))).toBe(
      "7 of 8, 1 left out by a rule fixed in advance (answered by the check itself)",
    );
    expect(text(control?.querySelector('[data-fact="exposure"]'))).toBe("none");
    expect(text(control?.querySelector('[data-fact="state"]'))).toBe(
      "fresh: written to today's question",
    );
    expect(text(control?.querySelector('[data-fact="measured"]'))).toBe("No measured run yet.");
    expect(text(control?.querySelector('[data-note="read-at"]'))).toContain(
      "Read from the tier store on 2026-11-18 at 10:02 UTC",
    );
  });

  it("says a measured version as a word with no number of any result", async () => {
    serve({ [TIERS_ROUTE]: [200, withControl({ measured: true })] });
    const host = await mount();
    const measured = text(card(host, "control")?.querySelector('[data-fact="measured"]'));
    expect(measured).toBe(EVIDENCE_COPY.measured);
    expect(measured).not.toMatch(/\d/);
  });

  it("says an unchecked version, a refused check record and an imported check in words", async () => {
    serve({ [TIERS_ROUTE]: [200, withControl({ check: null })] });
    let host = await mount();
    expect(text(card(host, "control")?.querySelector('[data-fact="check"]'))).toBe(
      EVIDENCE_COPY.noBlindCheck,
    );
    serve({ [TIERS_ROUTE]: [200, withControl({ check: { refused: "check_record_changed" } })] });
    host = await mount();
    expect(text(card(host, "control")?.querySelector('[data-fact="check"]'))).toBe(
      "its record is refused (check_record_changed)",
    );
    const imported = { tasks: 8, all_yes: 8, left_out: 0, source: "imported" };
    serve({ [TIERS_ROUTE]: [200, withControl({ check: imported })] });
    host = await mount();
    expect(text(card(host, "control")?.querySelector('[data-fact="check"]'))).toContain(
      "imported from the check's kept session",
    );
  });

  it("says each exposure word and a stale version in words", async () => {
    serve({
      [TIERS_ROUTE]: [200, withControl({ exposure: "exposed_unchecked", version_state: "stale" })],
    });
    const host = await mount();
    const control = card(host, "control");
    expect(text(control?.querySelector('[data-fact="exposure"]'))).toBe(
      EVIDENCE_COPY.exposureWords.exposed_unchecked,
    );
    expect(text(control?.querySelector('[data-fact="state"]'))).toBe(
      EVIDENCE_COPY.stateWords.stale,
    );
  });

  it("says a role with nothing published so, and shows no number", async () => {
    serve({ [TIERS_ROUTE]: [200, NO_TIERS] });
    const host = await mount();
    for (const role of ["control", "firmware"]) {
      expect(text(card(host, role))).toContain(EVIDENCE_COPY.noTiers);
      expect(text(card(host, role)?.querySelector("p"))).not.toMatch(/\d/);
    }
  });

  it("shows a refused role in its sentence and none of a version", async () => {
    const host = await mount();
    const firmware = card(host, "firmware");
    expect(text(firmware?.querySelector("h4"))).toBe(EVIDENCE_COPY.tiersNotShown("firmware"));
    expect(text(firmware)).toContain(NO_FRESH);
    expect(firmware?.querySelector("[data-fact]")).toBeNull();
  });

  it("warns once the copy is more than a week old, and not before", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(Date.parse(READ_AT) + 6 * 24 * 3_600_000));
    let host = await mount();
    expect(card(host, "control")?.querySelector('[data-note="stale"]')).toBeNull();
    vi.setSystemTime(new Date(Date.parse(READ_AT) + 8 * 24 * 3_600_000));
    host = await mount();
    expect(text(card(host, "control")?.querySelector('[data-note="stale"]'))).toBe(
      EVIDENCE_COPY.tiersStale,
    );
  });

  it("shows an answer carrying a field it does not know as refused, never in part", async () => {
    serve({ [TIERS_ROUTE]: [200, edited(["canary"], CANARY)] });
    const host = await mount();
    const panelAlert = host.querySelector('section[data-tab="gaps"] > [role="alert"]');
    expect(text(panelAlert?.querySelector("h2"))).toBe(EVIDENCE_COPY.tiersRefused);
    expect(host.querySelector("[data-tier-role]")).toBeNull();
    expect(host.innerHTML).not.toContain(CANARY);
    expect(host.innerHTML).not.toContain(CURRENT_VERSION);
    // The gap trend is read apart, and is still shown.
    expect(host.querySelectorAll("section[data-role]").length).toBe(2);
  });

  it("keeps showing the cards when the gap trend's route is refused", async () => {
    serve({ [GAPS_ROUTE]: [500, { error: "the route broke" }] });
    const host = await mount();
    expect(host.querySelectorAll("[data-tier-role]").length).toBe(2);
    expect(host.querySelector("section[data-role]")).toBeNull();
  });

  it("names no command and no held-out string anywhere on the panel", async () => {
    const host = await mount();
    const panel = text(host.querySelector('section[data-panel="tiers"]'));
    expect(panel).not.toMatch(/physgate|--publish|tiers status/);
    expect(host.innerHTML).not.toContain(CANARY);
    expect(host.innerHTML).not.toContain(DIGEST);
  });
});
