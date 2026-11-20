// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ShapeError } from "../../api/client";
import {
  EXPOSED,
  FLOOR,
  GAPS,
  gapLine,
  ONE_POINT,
  READ_AT,
  READER_REFUSAL,
  REFUSED_TREND,
  RUNS,
  SECOND,
  UNVERIFIED,
} from "./answers";
import { evidenceGaps, GAPS_ROUTE } from "./api";
import Evidence from "./Evidence";
import { ageWords } from "./Gaps";
import { EVIDENCE_COPY } from "./words";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

type Answer = readonly [number, unknown];

let answers: Record<string, Answer> = {};
let asked: string[] = [];

function serve(over: Record<string, Answer> = {}) {
  answers = { "/api/evidence/runs": [200, RUNS], [GAPS_ROUTE]: [200, GAPS], ...over };
}

beforeEach(() => {
  asked = [];
  serve();
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string) => {
      asked.push(input);
      const [status, body] = answers[input] ?? [404, { error: "no such route" }];
      return Promise.resolve(new Response(JSON.stringify(body), { status }));
    }),
  );
});

let root: Root | null = null;

/** The page's clock set to ``readAt`` plus ``hours``: only the date is faked, never a timer. */
function clockAt(hours: number, readAt = READ_AT) {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(Date.parse(readAt) + hours * 3_600_000));
}

const HOUR = 1;
const DAY = 24 * HOUR;

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

function role(host: HTMLElement, name: string): Element | null {
  return host.querySelector(`section[data-role="${name}"]`);
}

function rows(host: HTMLElement, name: string): Element[] {
  return [...(role(host, name)?.querySelectorAll("tbody tr[data-week]") ?? [])];
}

/** ``value`` with the line of its control role's first week changed by ``change``. */
function withLine(change: Record<string, unknown>) {
  return {
    roles: [
      {
        role: "control",
        state: "read",
        read_at: READ_AT,
        weeks: [{ week: "2026-W45", lines: [gapLine("2026-W45", change)], missing: false }],
      },
      { role: "firmware", state: "none" },
    ],
  };
}

describe("the gap trend's guard", () => {
  it("takes the answer whole: each role in order, with its state", () => {
    const trend = evidenceGaps(GAPS);
    expect(trend.roles.map((r) => [r.role, r.state])).toEqual([
      ["control", "read"],
      ["firmware", "none"],
    ]);
    const control = trend.roles[0];
    expect(control?.state === "read" ? control.weeks.map((w) => w.missing) : null).toEqual([
      false,
      true,
      false,
    ]);
    const refused = evidenceGaps(REFUSED_TREND).roles[0];
    expect(refused?.state === "refused" ? refused.error : null).toBe(READER_REFUSAL);
  });

  it("refuses anything the route does not send, and never a part of it", () => {
    const read = GAPS.roles[0] as Record<string, unknown>;
    const week = { week: "2026-W45", lines: [gapLine("2026-W45")], missing: false };
    const bad: unknown[] = [
      { roles: [{ role: "control", state: "headline" }] },
      { roles: [{ role: "control", state: "none", weeks: [] }] },
      {
        roles: [
          { role: "control", state: "none" },
          { role: "control", state: "none" },
        ],
      },
      { roles: [{ role: "electrical", state: "none" }] },
      { roles: [{ ...read, weeks: undefined }] },
      { roles: [{ ...read, extra: 1 }] },
      { roles: [{ role: "control", state: "refused", error: "x", reason: "y" }] },
      { roles: [{ ...REFUSED_TREND.roles[0], weeks: [] }] },
      { roles: [{ ...read, weeks: [{ ...week, missing: true }] }] },
      { roles: [{ ...read, weeks: [{ week: "2026-W46", lines: [], missing: false }] }] },
      { roles: [{ ...read, weeks: [{ ...week, week: "week 45" }] }] },
      withLine({ numbers: { ...gapLine("x").numbers, reward_hacking: { gap: "0.5" } } }),
      withLine({
        numbers: {
          ...gapLine("x").numbers,
          reward_hacking: { gap: 0.5, interval: [0.1], words: "w", label: null },
        },
      }),
      withLine({ numbers: { ...gapLine("x").numbers, held_out: { passed: 1 } } }),
      withLine({ store: "/somewhere" }),
      withLine({ version: "not a version" }),
      withLine({ manifest_ids: ["1".repeat(64)] }),
      withLine({ role: "control", arm: "harness" }),
      withLine({ floor: FLOOR }),
      withLine({
        numbers: { ...gapLine("x").numbers, held_out: { ...gapLine("x").numbers.held_out, n: 4 } },
      }),
      { roles: [], more: [] },
    ];
    for (const value of bad)
      expect(() => evidenceGaps(value), JSON.stringify(value)).toThrow(ShapeError);
  });
});

describe("the gap trend on the page", () => {
  it("is a tab of its own, read from its route alone, the runs not asked for", async () => {
    const host = await mount();
    const tabs = [...host.querySelectorAll('[role="group"][aria-label="What to show"] button')];
    expect(tabs.map((b) => text(b))).toEqual(["Runs", "Gaps", "Spend", "Compare", "Catches"]);
    expect(host.querySelector('section[data-tab="gaps"]')).not.toBeNull();
    expect(asked).toEqual([GAPS_ROUTE]);
  });

  it("shows each role in its own section, in the server's order", async () => {
    const host = await mount();
    const sections = [...host.querySelectorAll("section[data-role]")];
    expect(sections.map((s) => s.getAttribute("data-role"))).toEqual(["control", "firmware"]);
    expect(text(sections[0]?.querySelector("h2"))).toBe("Control role");
    expect(text(sections[1]?.querySelector("h2"))).toBe("Firmware role");
  });

  it("lists every week as a row, a week with no measurement said so in words", async () => {
    const host = await mount();
    const found = rows(host, "control");
    expect(found.map((r) => r.getAttribute("data-week"))).toEqual([
      "2026-W45",
      "2026-W46",
      "2026-W47",
    ]);
    expect(text(found[0])).toContain("Week 45, 2026");
    expect(text(found[1])).toContain(EVIDENCE_COPY.noMeasurement);
    expect(found[1]?.querySelector("[data-gap]")).toBeNull();
  });

  it("shows both gaps in points with their intervals, the rates as written, and the version", async () => {
    const host = await mount();
    const [first, , second] = rows(host, "control");
    expect(text(first?.querySelector('[data-gap="reward_hacking"]'))).toContain("+50.0 points");
    expect(text(first?.querySelector('[data-gap="reward_hacking"]'))).toContain(
      "95 % interval 0.0 to +100.0",
    );
    expect(text(first?.querySelector('[data-gap="optimiser_overfit"]'))).toContain(
      EVIDENCE_COPY.notMeasured,
    );
    expect(text(second?.querySelector('[data-gap="optimiser_overfit"]'))).toContain("+25.0 points");
    expect(text(second?.querySelector('[data-gap="optimiser_overfit"]'))).toContain(
      "95 % interval −12.5 to +50.0",
    );
    expect(text(second?.querySelector('[data-gap="optimiser_overfit"]'))).toContain(FLOOR);
    expect(text(first)).toContain("3/4 · 75.0 % [30.1, 95.4]");
    expect(text(first)).toContain("1/4 · 25.0 % [4.6, 69.9]");
    expect(text(first?.querySelector("[data-version]"))).toContain("3f70a6d8");
    expect(text(second)).toContain("3");
  });

  it("says beside its line what the reader says: a version seen since its measurement", async () => {
    const host = await mount();
    const [first, , second] = rows(host, "control");
    expect(text(second?.querySelector("[data-note]"))).toContain(EXPOSED);
    expect(first?.querySelector('[data-note="exposed"]')).toBeNull();
  });

  it("shows a line whose numbers the reader withholds with its reason and no number", async () => {
    serve({ [GAPS_ROUTE]: [200, withLine({ numbers: null, unverified: UNVERIFIED })] });
    const host = await mount();
    const [line] = rows(host, "control");
    expect(text(line)).toContain(UNVERIFIED);
    expect(line?.querySelector("[data-gap]")).toBeNull();
    expect(role(host, "control")?.querySelector("[data-point]")).toBeNull();
  });

  it("draws one point per gap measured and no line through them", async () => {
    const host = await mount();
    const chart = role(host, "control")?.querySelector("svg");
    expect(chart).not.toBeNull();
    const points = [...(chart?.querySelectorAll("[data-point]") ?? [])];
    expect(points.map((p) => p.getAttribute("data-point"))).toEqual([
      "2026-W45:reward_hacking",
      "2026-W47:reward_hacking",
      "2026-W47:optimiser_overfit",
    ]);
    expect(chart?.querySelector("polyline, path")).toBeNull();
    for (const line of chart?.querySelectorAll("line") ?? [])
      expect(["axis", "zero", "whisker", "tick"]).toContain(line.getAttribute("data-part"));
    expect(chart?.getAttribute("role")).toBe("img");
    expect(chart?.getAttribute("aria-label")).toBeTruthy();
  });

  it("says plainly what two points are, and claims no direction", async () => {
    const host = await mount();
    const said = text(role(host, "control")).toLowerCase();
    expect(said).toContain(EVIDENCE_COPY.pointsAlone(2).toLowerCase());
    expect(said).not.toMatch(/\b(rising|falling|increas|decreas|improv|worsen|trending)/);
  });

  it("reads honestly with one point: one measurement, no trend", async () => {
    serve({ [GAPS_ROUTE]: [200, ONE_POINT] });
    const host = await mount();
    const said = text(role(host, "control"));
    expect(said).toContain(EVIDENCE_COPY.onePoint);
    expect(said.toLowerCase()).not.toMatch(/\b(rising|falling|increas|decreas|improv|worsen)/);
    expect(role(host, "control")?.querySelectorAll("[data-point]").length).toBe(1);
  });

  it("says when the trend was read, and that what came since is not on it", async () => {
    clockAt(2 * HOUR);
    const host = await mount();
    const said = text(role(host, "control"));
    expect(said).toContain("Read from the gap trend on 2026-11-18 at 10:02 UTC (2 hours ago).");
    expect(said).toContain(EVIDENCE_COPY.asRead);
  });

  it("says how old the copy is in words, next to the time it was read", async () => {
    clockAt(9 * DAY + 3 * HOUR);
    const host = await mount();
    const note = role(host, "control")?.querySelector('[data-note="read-at"]');
    expect(text(note)).toContain("2026-11-18 at 10:02 UTC");
    expect(text(note)).toContain("(9 days ago)");
  });

  it("warns in plain words once the copy is older than seven days, and not before", async () => {
    clockAt(7 * DAY - HOUR);
    let host = await mount();
    expect(role(host, "control")?.querySelector('[data-note="stale"]')).toBeNull();
    clockAt(7 * DAY + HOUR);
    host = await mount();
    const warning = role(host, "control")?.querySelector('[data-note="stale"]');
    expect(text(warning)).toBe(EVIDENCE_COPY.stale);
    expect(warning?.getAttribute("role")).toBe("status");
  });

  it("warns on an old copy that holds no measurement yet, which reads as current as well", async () => {
    clockAt(30 * DAY);
    serve({
      [GAPS_ROUTE]: [
        200,
        { roles: [{ role: "control", state: "read", read_at: READ_AT, weeks: [] }] },
      ],
    });
    const host = await mount();
    expect(text(role(host, "control"))).toContain("(30 days ago)");
    expect(text(role(host, "control")?.querySelector('[data-note="stale"]'))).toBe(
      EVIDENCE_COPY.stale,
    );
  });

  it("says a copy's age in the words a person would use", () => {
    expect(typeof ageWords).toBe("function");
    const at = Date.parse(READ_AT);
    const after = (ms: number) => ageWords(READ_AT, at + ms);
    expect(after(20_000)).toBe("just now");
    expect(after(60_000)).toBe("1 minute ago");
    expect(after(45 * 60_000)).toBe("45 minutes ago");
    expect(after(3_600_000)).toBe("1 hour ago");
    expect(after(47 * 3_600_000)).toBe("47 hours ago");
    expect(after(48 * 3_600_000)).toBe("2 days ago");
    expect(after(9 * 86_400_000 + 5 * 3_600_000)).toBe("9 days ago");
    expect(after(-5 * 60_000)).toBe(EVIDENCE_COPY.aheadOfClock);
    expect(ageWords("the other day", at)).toBeNull();
  });

  it("says a role with no trend published what makes a first point appear, and draws nothing", async () => {
    const host = await mount();
    const firmware = role(host, "firmware");
    expect(text(firmware)).toContain(EVIDENCE_COPY.noTrend);
    expect(text(firmware)).toContain(EVIDENCE_COPY.firstPoint);
    expect(firmware?.querySelector("svg, table")).toBeNull();
    expect(text(host)).not.toMatch(/physgate|--publish|--append/);
  });

  it("says a published trend with no measurement yet the same way, never as an empty chart", async () => {
    serve({
      [GAPS_ROUTE]: [
        200,
        { roles: [{ role: "control", state: "read", read_at: READ_AT, weeks: [] }] },
      ],
    });
    const host = await mount();
    const control = role(host, "control");
    expect(text(control)).toContain(EVIDENCE_COPY.firstPoint);
    expect(control?.querySelector("svg, table")).toBeNull();
  });

  it("shows a refused trend in a sentence with the reader's words, and no number of it", async () => {
    serve({ [GAPS_ROUTE]: [200, REFUSED_TREND] });
    const host = await mount();
    const control = role(host, "control");
    expect(text(control?.querySelector("h3"))).toBe(EVIDENCE_COPY.trendRefused("control"));
    expect(text(control)).toContain(READER_REFUSAL);
    expect(text(control)).toContain("Read from the gap trend on 2026-11-18 at 10:02 UTC");
    expect(control?.querySelector("svg, table")).toBeNull();
  });

  it("names a refused answer in a sentence with its reason, and shows nothing partial", async () => {
    serve({ [GAPS_ROUTE]: [500, { error: "the route broke" }] });
    const host = await mount();
    const alert = host.querySelector('[role="alert"]');
    expect(text(alert?.querySelector("h2"))).toBe(EVIDENCE_COPY.gapsRefused);
    expect(text(alert)).toContain("the route broke");
    expect(host.querySelector("section[data-role]")).toBeNull();
  });

  it("keeps every number on the tab inside a figure, a table or a role's section", async () => {
    const host = await mount();
    const loose: string[] = [];
    for (const el of host.querySelectorAll("*")) {
      const own = [...el.childNodes]
        .filter((node) => node.nodeType === Node.TEXT_NODE)
        .map((node) => node.textContent ?? "")
        .join(" ");
      if (!/\d/.test(own)) continue;
      if (el.closest("[data-source], table, [role='alert']") === null) loose.push(own.trim());
    }
    expect(loose).toEqual([]);
  });

  it("refuses an answer that is not the route's, and draws none of it", async () => {
    serve({ [GAPS_ROUTE]: [200, withLine({ numbers: { ...SECOND.numbers, rate: 1 } })] });
    const host = await mount();
    expect(host.querySelector('[role="alert"]')).not.toBeNull();
    expect(host.querySelector("section[data-role]")).toBeNull();
  });
});
