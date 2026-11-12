// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SimulationScreen } from "./Simulation";
import type { ToolViewDef } from "./toolViews";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const BASE = "/api/runs/0/run-series";
const S1 = "s1-af41ca";
const S2 = "s2-5e2ad0";
const SHA = (c: string) => c.repeat(64);
const COMMIT = "0123456789abcdef0123456789abcdef01234567";

const RUNS = {
  runs: [
    {
      root: 0,
      name: "run-series",
      run_id: "r-series",
      manifest_id: "m",
      gate_mode: "on",
      os_layer: null,
    },
  ],
};

const CONFIG = {
  manifest_id: "m",
  config: {
    run_id: "r-series",
    gate_mode: "on",
    harness: { commit: "fedcba9876543210" },
    auth: "api_key",
    brief_sha256: "a",
    seed: 7,
    models: { roles: { control: "model-x" }, decomposition: "model-x" },
    os_layer: null,
  },
};

/** What the status route sends beside the next step, for a run that owes nothing. */
const NOTHING_OWED = { halted: null, owed_halt: null, completion: { owner: false, modules: [] } };
const DONE = { next_step: { kind: "done", subtask_id: null }, ...NOTHING_OWED };
const GOING = { next_step: { kind: "session", subtask_id: S1 }, ...NOTHING_OWED };

const EVENTS = [
  { seq: 1, ts: "2026-11-06T10:00:00Z", kind: "run_started", run_id: "r-series", gate_mode: "on" },
  {
    seq: 2,
    ts: "2026-11-06T10:00:01Z",
    kind: "subtask_planned",
    subtask_id: S1,
    assigned_role: "control",
  },
  {
    seq: 3,
    ts: "2026-11-06T10:00:02Z",
    kind: "subtask_planned",
    subtask_id: S2,
    assigned_role: "control",
  },
]
  .map((e) => JSON.stringify(e))
  .join("\n");

const gateRecord = (extra: Record<string, unknown> = {}) => ({
  seq: 40,
  check: 2,
  name: "magnitude",
  outcome: "unchecked",
  gate_mode: "on",
  blocking: false,
  expected: null,
  low: null,
  high: null,
  ...extra,
});

const check = (extra: Record<string, unknown> = {}) => ({
  node_id: "control.loop",
  quantity: "phase_margin",
  record_id: "loop_nominal",
  extract: "phase_margin",
  trace: null,
  session_id: "sess-3",
  declared_value: 0.5534885189031078,
  declared_unit: "rad",
  read_value: 0.5534885189031078,
  read_unit: "rad",
  outcome: "agrees",
  reason: null,
  gate: [gateRecord()],
  ...extra,
});

const PEAK = {
  quantity: "step_peak",
  record_id: "step_nominal",
  extract: "max_abs",
  trace: "position",
  declared_value: 1.3912345678901,
  declared_unit: "m",
  read_value: 1.3912345678901,
  read_unit: "m",
};

const sealed = (id: string, session = "sess-3") => ({
  record_id: id,
  session_id: session,
  sha256: SHA("b"),
  length: 900,
  script: "control/sim.py",
  script_sha256: SHA("c"),
});

const attempt = (subtask: string, n: number, extra: Record<string, unknown> = {}) => ({
  subtask_id: subtask,
  attempt: n,
  owner_role: "control",
  merged: false,
  rejected: false,
  refused_by: null,
  sessions: [{ session_id: `sess-${String(n)}`, outcome: "completed", attempt_commit: COMMIT }],
  records: [sealed("step_nominal", `sess-${String(n)}`)],
  superseded: [],
  set_aside: [],
  checks: [],
  ...extra,
});

const LISTING = {
  tolerance: "0.005",
  attempts: [
    attempt(S1, 1, {
      rejected: true,
      checks: [
        check({
          ...PEAK,
          session_id: "sess-1",
          gate: [
            gateRecord({
              outcome: "fail",
              blocking: true,
              expected: "within its sourced range",
              low: { value: 0.1, unit: "m" },
              high: { value: 1.0, unit: "m" },
            }),
          ],
        }),
      ],
    }),
    attempt(S1, 2, {
      refused_by: "series",
      records: [],
      set_aside: [
        {
          session_id: "sess-2",
          kind: "refused",
          name: "stray_notes.json",
          reason: "not a record this format admits",
        },
      ],
      checks: [
        check({
          read_value: null,
          read_unit: null,
          outcome: "unreadable",
          reason: "names the record loop_nominal, which this attempt did not seal",
          session_id: null,
          gate: "refused_before_gate",
        }),
      ],
    }),
    attempt(S1, 3, {
      merged: true,
      records: [
        sealed("edge_01"),
        sealed("edge_02"),
        sealed("loop_nominal"),
        sealed("step_nominal"),
      ],
      superseded: [{ record_id: "step_nominal", session_id: "sess-0" }],
      checks: [
        check(),
        check({ ...PEAK, gate: "not_named" }),
        check({
          quantity: "edge_peak",
          record_id: "edge_01",
          extract: "max",
          trace: "position",
          declared_unit: "m",
          read_unit: "m",
          gate: "gate_not_run",
        }),
      ],
    }),
    attempt(S2, 1, {
      merged: true,
      checks: [
        check({
          ...PEAK,
          session_id: "sess-1",
          gate: [
            gateRecord({
              outcome: "fail",
              gate_mode: "observe",
              blocking: true,
              low: { value: 0.1, unit: "m" },
              high: { value: 1.0, unit: "m" },
            }),
          ],
        }),
        check({ session_id: "sess-1", gate: "gate_off" }),
        check({ session_id: "sess-1", gate: "unmatched" }),
        check({
          session_id: "sess-1",
          outcome: "partly",
          gate: [gateRecord({ outcome: "deferred", gate_mode: "advisory" })],
        }),
        check({ session_id: "sess-1", declared_unit: "" }),
      ],
    }),
  ],
};

const col = (name: string, unit: string, extra: Record<string, unknown> = {}) => ({
  name,
  unit,
  samples: 501,
  first: 0,
  last: 1.0000064,
  smallest: "NEGZERO",
  largest: 1.3912345678901,
  ...extra,
});

const shown = (id: string, extra: Record<string, unknown> = {}) => ({
  record_id: id,
  session_id: "sess-3",
  sha256: SHA("d"),
  length: 21345,
  title: `Stand-in loop, unit step at gain 2, not the robot (${id})`,
  group: "step",
  axis: "time",
  loop: false,
  x: col("time", "s", { last: 10, smallest: 0, largest: 10 }),
  traces: [col("position", "m"), col("error", "m", { first: 1, last: -0.0000064 })],
  inputs: {
    seed: { value: 7, unit: "dimensionless" },
    gain: { value: 2.0, unit: "dimensionless" },
    big_seed: { value: "9223372036854775807", unit: "dimensionless" },
  },
  producer: {
    script: { path: "control/sim.py", sha256: SHA("e"), blob: "f".repeat(40) },
    loaded: [{ path: "control/model.py", sha256: SHA("1"), blob: "9".repeat(40) }],
  },
  environment: [{ path: "/usr/lib/python3.12/json/__init__.py", sha256: SHA("2") }],
  attempt_commit: COMMIT,
  ...extra,
});

const RECORDS = {
  subtask_id: S1,
  attempt: 3,
  records: [
    {
      record_id: "edge_01",
      session_id: "sess-3",
      sha256: SHA("b"),
      length: 900,
      record: `series/${S1}/3/sess-3/edge_01.json`,
      refused: "seal",
      error: "the record's bytes are not the ones its session sealed",
      sealed_sha256: SHA("b"),
      sealed_length: 900,
      found_sha256: SHA("7"),
    },
    {
      record_id: "edge_02",
      session_id: "sess-3",
      sha256: SHA("b"),
      length: 900,
      record: `series/${S1}/3/sess-3/edge_02.json`,
      refused: "format",
      error: "a column's unit is not one the gate knows",
      sealed_sha256: SHA("b"),
      sealed_length: 900,
    },
    shown("loop_nominal", {
      title: "Stand-in loop gain K/(s(s+1)(0.1s+1)), broken at the plant input, not the robot",
      group: "frequency_response",
      axis: "frequency",
      loop: true,
      x: col("angular_frequency", "rad/s", {
        samples: 3,
        first: 0.01,
        last: 100,
        smallest: 0.01,
        largest: 100,
      }),
      traces: [
        col("loop_magnitude", "dimensionless", { samples: 3 }),
        col("loop_phase", "rad", { samples: 3 }),
      ],
    }),
    shown("step_nominal"),
    { record_id: "bad_row", title: "no columns" },
  ],
};

const ROWS = 501;
const STEP_SAMPLES = {
  format: "physgate-series/1",
  id: "step_nominal",
  title: "Stand-in",
  group: "step",
  axis: "time",
  x: { name: "time", unit: "s", values: Array.from({ length: ROWS }, (_, i) => i / 50) },
  traces: [
    {
      name: "position",
      unit: "m",
      values: Array.from({ length: ROWS }, (_, i) => (i === 0 ? "NEGZERO" : i / 360.123)),
    },
    { name: "error", unit: "m", values: Array.from({ length: ROWS }, (_, i) => 1 - i / 360.123) },
  ],
  inputs: { seed: { value: 7, unit: "dimensionless" } },
  producer: {},
};

const LOOP_SAMPLES = {
  axis: "frequency",
  x: { name: "angular_frequency", unit: "rad/s", values: [0.01, 1, 100] },
  traces: [
    { name: "loop_magnitude", unit: "dimensionless", values: [200, 1.2, 0.0002] },
    { name: "loop_phase", unit: "rad", values: [-1.58, -2.4, -3.1] },
  ],
};

type Answer = readonly [number, unknown];

let answers: Record<string, Answer> = {};
let asked: string[] = [];
let held: { path: string; release: () => void } | null = null;

function serve(over: Record<string, Answer> = {}) {
  answers = {
    "/api/runs": [200, RUNS],
    [`${BASE}/config`]: [200, CONFIG],
    [`${BASE}/status`]: [200, DONE],
    [`${BASE}/events`]: [200, EVENTS],
    [`${BASE}/series`]: [200, LISTING],
    [`${BASE}/series/${S1}/3`]: [200, RECORDS],
    [`${BASE}/series/${S1}/1`]: [
      200,
      { subtask_id: S1, attempt: 1, records: [shown("step_nominal")] },
    ],
    [`${BASE}/series/${S2}/1`]: [
      200,
      { subtask_id: S2, attempt: 1, records: [shown("step_nominal")] },
    ],
    [`${BASE}/series/${S1}/3/step_nominal`]: [200, STEP_SAMPLES],
    [`${BASE}/series/${S1}/1/step_nominal`]: [200, STEP_SAMPLES],
    [`${BASE}/series/${S2}/1/step_nominal`]: [200, STEP_SAMPLES],
    [`${BASE}/series/${S1}/3/loop_nominal`]: [200, LOOP_SAMPLES],
    ...over,
  };
}

beforeEach(() => {
  asked = [];
  held = null;
  serve();
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string) => {
      asked.push(input);
      const [status, body] = answers[input] ?? [404, { error: "no such route" }];
      const response = () =>
        new Response(
          // JSON.stringify writes -0 as 0; the server writes the record's -0.0 as such.
          typeof body === "string" ? body : JSON.stringify(body).replaceAll('"NEGZERO"', "-0.0"),
          { status },
        );
      if (held?.path === input)
        return new Promise<Response>((resolve) => {
          if (held !== null)
            held.release = () => {
              resolve(response());
            };
        });
      return Promise.resolve(response());
    }),
  );
  // The page has no canvas here: uPlot draws into one that accepts every call and draws nothing.
  const context = new Proxy(
    {},
    { get: (_t, key) => (key === "measureText" ? () => ({ width: 10 }) : () => undefined) },
  );
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(context as never);
  vi.stubGlobal(
    "Path2D",
    class {
      moveTo() {}
      lineTo() {}
      rect() {}
      arc() {}
      closePath() {}
      bezierCurveTo() {}
      addPath() {}
    },
  );
});

let root: Root | null = null;

afterEach(() => {
  // A read still held is let go, so nothing is pending once the window goes.
  held?.release();
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

function render(search: string, toolViews?: readonly ToolViewDef[]) {
  act(() => {
    root?.render(
      <SimulationScreen
        setHeader={() => undefined}
        query={new URLSearchParams(search)}
        {...(toolViews === undefined ? {} : { toolViews })}
      />,
    );
  });
}

/** The screen at ``search``, read whole. */
async function mount(search = "", toolViews?: readonly ToolViewDef[]): Promise<HTMLElement> {
  const host = document.createElement("main");
  document.body.append(host);
  root = createRoot(host);
  render(search, toolViews);
  await settle();
  return host;
}

/** The first text of ``el``: what a person reads first. */
function firstText(el: Element): string {
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  let node = walker.nextNode();
  while (node !== null && (node.textContent ?? "").trim() === "") node = walker.nextNode();
  return (node?.textContent ?? "").trim();
}

/** A record id, a hex digest, a run id or a dotted key: never what leads. */
const AN_ID =
  /^([a-z][a-z0-9_]*_[a-z0-9_]+$|[0-9a-f]{7,64}\b|run-\d+|[a-z][a-z0-9_]*(\.[a-z0-9_]+)+)/;

const text = (el: Element | null | undefined) => (el?.textContent ?? "").replace(/\s+/g, " ");

function bound(host: HTMLElement): HTMLTableRowElement[] {
  return [
    ...host.querySelectorAll<HTMLTableRowElement>(
      'table[aria-label="What was read off a record, and what the gate said"] tbody tr',
    ),
  ];
}

const rail = (host: HTMLElement) => host.querySelector('nav[aria-label="Simulation records"]');

function button(host: Element, words: string): HTMLButtonElement {
  const found = [...host.querySelectorAll("button")].find((b) => text(b).trim() === words);
  expect(found, `a button "${words}"`).toBeDefined();
  return found as HTMLButtonElement;
}

describe("reading the run's records", () => {
  it("says it is reading, and shows nothing of the records until it has read", async () => {
    held = { path: `${BASE}/series`, release: () => undefined };
    const host = await mount();
    expect(text(host.querySelector('[aria-busy="true"]'))).toBe(
      "Reading the run's simulation records…",
    );
    expect(rail(host)).toBeNull();
    expect(host.querySelector("table")).toBeNull();
    expect(host.textContent).toContain(
      "What the run's simulations recorded, as each was sealed when its session ended.",
    );
  });

  it("names what was refused in a sentence, with Details and Read again, and nothing partial", async () => {
    serve({
      [`${BASE}/series`]: [422, { error: "the event log has a line this version cannot read" }],
    });
    const host = await mount();
    const alert = host.querySelector('[role="alert"]');
    expect(text(alert?.querySelector("h2"))).toBe(
      "The run's simulation records could not be read: the event log has a line this version cannot read.",
    );
    expect(text(alert)).toContain(`${BASE}/series`);
    expect(text(alert)).toContain("422");
    expect(button(host, "Read again")).toBeTruthy();
    expect(rail(host)).toBeNull();
    expect(host.querySelector("table")).toBeNull();
    expect(host.querySelector(".pg-plot")).toBeNull();
  });

  it("says no run exists yet when there is none", async () => {
    serve({ "/api/runs": [200, { runs: [] }] });
    const host = await mount();
    expect(text(host.querySelector(".pg-state-empty h2"))).toBe("No run yet");
    expect(host.querySelector('[role="alert"]')).toBeNull();
  });

  it("says a run recorded no simulations, and how a role records one, with no command", async () => {
    serve({ [`${BASE}/series`]: [200, { tolerance: "0.005", attempts: [] }] });
    const host = await mount();
    expect(text(host.querySelector(".pg-state-empty h2"))).toBe(
      "This run recorded no simulations.",
    );
    expect(host.textContent).toContain(
      "A role records a simulation when its script runs one; any quantity read off a record is checked against it before the gate.",
    );
    expect(host.querySelector("button")).toBeNull();
  });

  it("says a run whose sessions recorded nothing recorded no simulations", async () => {
    serve({
      [`${BASE}/series`]: [
        200,
        {
          tolerance: "0.005",
          attempts: [attempt(S1, 1, { records: [] }), attempt(S2, 1, { records: [] })],
        },
      ],
    });
    const host = await mount();
    expect(text(host.querySelector(".pg-state-empty h2"))).toBe(
      "This run recorded no simulations.",
    );
    expect(rail(host)).toBeNull();
    expect(asked.filter((p) => p.startsWith(`${BASE}/series/`))).toEqual([]);
  });

  it("says a run with no event log yet has no record yet, never an error", async () => {
    serve({ [`${BASE}/series`]: [404, { error: "the run has no event log yet" }] });
    const host = await mount();
    expect(host.querySelector('[role="alert"]')).toBeNull();
    expect(host.textContent).toContain("Records appear when the session that wrote them ends.");
  });

  it("reads only the run's own routes and this screen's, and a record only when it is opened", async () => {
    const host = await mount();
    expect(host.querySelector(".pg-sim-record-heading")).not.toBeNull();
    const allowed = new Set([
      "/api/runs",
      `${BASE}/config`,
      `${BASE}/status`,
      `${BASE}/events`,
      `${BASE}/series`,
      `${BASE}/series/${S1}/3`,
      `${BASE}/series/${S1}/3/loop_nominal`,
    ]);
    expect(asked.filter((p) => !allowed.has(p))).toEqual([]);
    expect(asked).toContain(`${BASE}/series/${S1}/3/loop_nominal`);
    expect(asked).not.toContain(`${BASE}/series/${S1}/3/step_nominal`);
  });
});

describe("the rail", () => {
  it("opens on the first subtask that sealed a record, at its merged attempt, and its first shown record", async () => {
    const host = await mount();
    const current = rail(host)?.querySelector('.pg-sim-attempt[aria-current="true"]');
    expect(text(current)).toContain("Attempt 3");
    expect(text(host.querySelector(".pg-sim-record-heading"))).toContain(
      "Stand-in loop gain K/(s(s+1)(0.1s+1))",
    );
  });

  it("leads every subtask, attempt and record row with words, never an id", async () => {
    const host = await mount();
    const rows = [
      ...(rail(host)?.querySelectorAll(
        ".pg-sim-subtask-title, .pg-sim-attempt, .pg-sim-record-link",
      ) ?? []),
    ];
    expect(rows.length).toBeGreaterThan(8);
    expect(rows.map(firstText).filter((t) => AN_ID.test(t))).toEqual([]);
    expect(text(rail(host))).toContain("Subtask 1");
  });

  it("tags each attempt in neutral words from the log, never a verdict", async () => {
    const host = await mount();
    const tags = [...(rail(host)?.querySelectorAll(".pg-sim-attempt") ?? [])].map((a) =>
      text(a.querySelector(".pg-status")),
    );
    expect(tags).toEqual(["Not merged", "Refused before the gate", "Merged", "Merged"]);
    expect(rail(host)?.querySelector('[class*="pg-verdict"]')).toBeNull();
  });

  it("groups the records by the role's own group, and lists a record it could not show by its sentence", async () => {
    const host = await mount();
    const groups = [...(rail(host)?.querySelectorAll(".pg-sim-group-title") ?? [])].map(text);
    expect(groups).toEqual(["Frequency response", "Step", "Records not shown"]);
    const railText = text(rail(host));
    expect(railText).toContain("Not what was sealed");
    expect(railText).toContain(
      "This record is sealed, but this version cannot read it: a column's unit is not one the gate knows.",
    );
    expect(railText).toContain("This row could not be read:");
    expect(railText).toContain("Frequency record");
    expect(railText).toContain("Time record");
    expect(railText).toContain("501samples");
  });

  it("lists what a later session recorded again, and what a session set aside with its reason", async () => {
    const host = await mount();
    expect(text(rail(host))).toContain(
      "A later session of this attempt recorded step_nominal again; the later one is shown.",
    );
    const refused = await (async () => {
      act(() => {
        root?.unmount();
      });
      document.body.innerHTML = "";
      return mount(`subtask=${S1}&attempt=2`);
    })();
    expect(text(refused)).toContain("This attempt left no sealed record.");
    expect(text(rail(refused))).toContain("Not sealed: not a record this format admits.");
    expect(text(rail(refused))).toContain("stray_notes.json");
    expect(asked).not.toContain(`${BASE}/series/${S1}/2`);
  });

  it("says so far on its counts while the run is in progress, and tags the open attempt so", async () => {
    serve({
      [`${BASE}/status`]: [200, GOING],
      [`${BASE}/series`]: [200, { tolerance: "0.005", attempts: [attempt(S1, 1)] }],
      [`${BASE}/series/${S1}/1`]: [
        200,
        { subtask_id: S1, attempt: 1, records: [shown("step_nominal")] },
      ],
    });
    const host = await mount();
    expect(text(rail(host))).toContain("1 record so far");
    expect(text(rail(host)?.querySelector(".pg-sim-attempt .pg-status"))).toBe("In progress");
  });
});

describe("a record", () => {
  it("leads with its title, attributed to its role, the ids after it", async () => {
    const host = await mount(`subtask=${S1}&attempt=3&record=step_nominal`);
    const head = host.querySelector(".pg-sim-record-head");
    expect(firstText(head ?? host)).toBe(
      "Stand-in loop, unit step at gain 2, not the robot (step_nominal)",
    );
    expect(text(head)).toContain("titled by the control role");
    expect(text(head)).toContain("step_nominal");
    expect(head?.querySelector('[role="note"]')?.getAttribute("aria-label")).toBe(
      "Source: run r-series at commit 0123456",
    );
  });

  it("draws one plot per unit, units in the titles, the chart hidden and its summary the server's numbers", async () => {
    const host = await mount(`subtask=${S1}&attempt=3&record=step_nominal`);
    const plots = [...host.querySelectorAll("figure.pg-plot")];
    expect(plots).toHaveLength(1);
    expect(text(plots[0]?.querySelector(".pg-plot-title"))).toBe("Position and error");
    expect(text(plots[0]?.querySelector(".pg-plot-sub"))).toBe("Position and error against time");
    expect([...(plots[0]?.querySelectorAll(".pg-sim-key") ?? [])].map(text)).toEqual([
      "Position",
      "Error",
    ]);
    expect(plots[0]?.querySelector(".pg-plot-canvas")?.getAttribute("aria-hidden")).toBe("true");
    expect(text(plots[0]?.querySelector(".pg-plot-summary"))).toBe(
      "Position against time: 501 samples from 0 s to 10 s. Smallest -0 m, largest 1.3912345678901 m, last 1.0000064 m. " +
        "Error against time: 501 samples from 0 s to 10 s. Smallest -0 m, largest 1.3912345678901 m, last -0.0000064 m.",
    );
    expect(plots[0]?.getAttribute("data-source")).toBe(`run r-series@${COMMIT}`);
  });

  it("names the attempt's commit on every plot's chip, and a dashed no commit when it made none", async () => {
    serve({
      [`${BASE}/series/${S1}/3`]: [
        200,
        { ...RECORDS, records: [shown("step_nominal", { attempt_commit: null })] },
      ],
    });
    const host = await mount(`subtask=${S1}&attempt=3&record=step_nominal`);
    const chips = [...host.querySelectorAll("figure.pg-plot .pg-source")];
    expect(chips).toHaveLength(1);
    expect(chips[0]?.classList.contains("pg-source-missing")).toBe(true);
    expect(text(chips[0])).toContain("no commit");
  });

  it("draws a loop's magnitude and phase as two plots, in its own units", async () => {
    const host = await mount(`subtask=${S1}&attempt=3&record=loop_nominal`);
    const titles = [...host.querySelectorAll("figure.pg-plot .pg-plot-title")].map(text);
    expect(titles).toEqual(["Loop magnitude", "Loop phase"]);
    expect(host.textContent).toContain(
      "Loop phase against angular frequency: 3 samples from 0.01 rad/s to 100 rad/s.",
    );
    expect(host.textContent).not.toMatch(/°|deg/);
  });

  it("shows every row of its data, a page at a time, as recorded", async () => {
    const host = await mount(`subtask=${S1}&attempt=3&record=step_nominal`);
    const figure = host.querySelector("figure.pg-plot");
    expect(figure).not.toBeNull();
    if (figure === null) return;
    act(() => {
      button(figure, "Data").click();
    });
    const table = figure.querySelector('table[aria-label="Position and error: the data"]');
    expect(text(table?.querySelector("thead"))).toBe("Time [s]Position [m]Error [m]");
    expect(table?.querySelectorAll("tbody tr")).toHaveLength(500);
    expect(text(figure)).toContain("Rows 1–500 of 501");
    expect(text(table?.querySelector("tbody tr td:nth-child(2)"))).toBe("-0");
    act(() => {
      button(figure, "Next rows").click();
    });
    expect(text(figure)).toContain("Rows 501–501 of 501");
    expect(figure.querySelectorAll("tbody tr")).toHaveLength(1);
    expect(text(figure.querySelector("tbody tr td"))).toBe("10");
  });

  it("lists what was read off it, as the change check recorded it, and moves to its row", async () => {
    const host = await mount(`subtask=${S1}&attempt=3&record=step_nominal`);
    const readOff = host.querySelector('[aria-label="Read off this record"]');
    expect(text(readOff)).toContain("Step peak");
    expect(text(readOff)).toContain("1.3912345678901m");
    expect(text(readOff)).toContain("(Largest magnitude of position)");
    expect(text(readOff)).toContain("Agrees within three significant figures");
    expect(readOff).not.toBeNull();
    if (readOff === null) return;
    act(() => {
      button(readOff, "Show its row").click();
    });
    expect(document.activeElement?.id).toBe("sim-check-1");
  });

  it("shows its inputs and how it was produced one click away, unrounded, and says it was not re-run", async () => {
    const host = await mount(`subtask=${S1}&attempt=3&record=step_nominal`);
    const produced = host.querySelector("details.pg-sim-produced");
    expect(text(produced?.querySelector("summary"))).toBe("Inputs and how it was produced");
    expect(produced?.hasAttribute("open")).toBe(false);
    expect(text(produced)).toContain("Big seed");
    expect(text(produced)).toContain("9223372036854775807dimensionless");
    expect(text(produced)).toContain("control/sim.py");
    expect(text(produced)).toContain(
      "the interpreter's own installation, outside every place the session can write",
    );
    expect(text(produced)).toContain(
      "This record names the committed code that wrote it. The harness did not re-run that code to confirm the curve.",
    );
    expect(text(produced)).toContain("Checked against its seal on this read.");
    expect(text(produced)).toContain("21345B");
  });

  it("whose seal broke is a sentence in its place, with the seal under Details, and nothing drawn from it", async () => {
    const host = await mount(`subtask=${S1}&attempt=3&record=edge_01`);
    const state = host.querySelector(".pg-sim-refused");
    expect(text(state?.querySelector("h2"))).toBe(
      "This record changed after its session ended, so it is not shown.",
    );
    expect(text(state)).toContain(SHA("7"));
    expect(text(state)).toContain(`series/${S1}/3/sess-3/edge_01.json`);
    expect(state?.getAttribute("role")).toBe("status");
    expect(host.querySelector(".pg-plot")).toBeNull();
    expect(host.querySelector(".pg-plot-summary")).toBeNull();
    expect(host.querySelector(".pg-sim-produced")).toBeNull();
    expect(host.querySelector('.pg-sim-refused [class*="pg-verdict"]')).toBeNull();
    // A refusal, not a verdict: the state is drawn in neutral ink, never as an error.
    expect(host.querySelector(".pg-state-error")).toBeNull();
    expect(asked).not.toContain(`${BASE}/series/${S1}/3/edge_01`);
    // Its row in the table says so; the other records are still listed.
    const row = bound(host).find((r) => text(r).includes("Edge peak"));
    expect(text(row)).toContain("Not what was sealed");
    expect(rail(host)?.querySelectorAll(".pg-sim-record-link")).toHaveLength(5);
  });

  it("this version cannot read is a sentence in its place, and nothing drawn from it", async () => {
    const host = await mount(`subtask=${S1}&attempt=3&record=edge_02`);
    expect(text(host.querySelector(".pg-sim-refused h2"))).toBe(
      "This record is sealed, but this version cannot read it: a column's unit is not one the gate knows.",
    );
    expect(host.querySelector(".pg-plot")).toBeNull();
  });

  it("refused when it is opened shows the refusal alone, never the attempt's summary of it", async () => {
    serve({
      [`${BASE}/series/${S1}/3/step_nominal`]: [
        422,
        {
          error: "the record is not what its session sealed, so it is not served",
          record: `series/${S1}/3/sess-3/step_nominal.json`,
          seal: "broken",
          reason: "the record's bytes are not the ones its session sealed",
          sealed_sha256: SHA("d"),
          sealed_length: "21345",
          found_length: "21346",
        },
      ],
    });
    const host = await mount(`subtask=${S1}&attempt=3&record=step_nominal`);
    expect(text(host.querySelector(".pg-sim-refused h2"))).toBe(
      "This record changed after its session ended, so it is not shown.",
    );
    expect(text(host.querySelector(".pg-sim-refused"))).toContain("21346 B");
    expect(host.querySelector(".pg-plot")).toBeNull();
    expect(host.querySelector(".pg-sim-produced")).toBeNull();
    expect(host.querySelector(".pg-sim-record-heading")).toBeNull();
    expect(host.textContent).not.toContain("501 samples from");
  });

  it("whose sealed columns are not the ones its summary describes is refused, and nothing drawn", async () => {
    serve({
      [`${BASE}/series/${S1}/3/step_nominal`]: [
        200,
        { ...STEP_SAMPLES, traces: STEP_SAMPLES.traces.slice(0, 1) },
      ],
    });
    const host = await mount(`subtask=${S1}&attempt=3&record=step_nominal`);
    expect(text(host.querySelector('[role="alert"] h2'))).toBe("The record could not be read");
    expect(host.querySelector(".pg-plot")).toBeNull();
    expect(host.querySelector(".pg-sim-produced")).toBeNull();
  });

  it("gets focus when the person chooses it, and not on the screen's first draw", async () => {
    const host = await mount(`subtask=${S1}&attempt=3&record=step_nominal`);
    expect(document.activeElement).not.toBe(host.querySelector(".pg-sim-record-heading"));
    render(`subtask=${S1}&attempt=3&record=loop_nominal`);
    await settle();
    expect(document.activeElement).toBe(host.querySelector(".pg-sim-record-heading"));
    expect(text(document.activeElement)).toContain("Stand-in loop gain");
  });
});

describe("what was read off a record, and what the gate said", () => {
  it("names the tolerance in words from the run's listing, and the gate column's rule above the table", async () => {
    const host = await mount();
    const table = host.querySelector(".pg-sim-bound");
    expect(text(table)).toContain(
      "Each quantity a role read off one of its records was checked against that record before the gate. The gate column shows only what a gate record says about that quantity.",
    );
    // The term's explanation sits beside its word, so the sentence is read in two parts.
    expect(text(table?.querySelector(".pg-term-word"))).toBe("Agreement");
    expect(text(table)).toContain("is within three significant figures (0.5 % relative).");
    serve({ [`${BASE}/series`]: [200, { ...LISTING, tolerance: "0.01" }] });
    act(() => {
      root?.unmount();
    });
    document.body.innerHTML = "";
    const other = await mount();
    expect(text(other.querySelector(".pg-sim-bound"))).toContain(
      "Agrees within a relative tolerance of 0.01",
    );
  });

  it("leads each row with the quantity's name, links its node, and shows both values unrounded", async () => {
    const host = await mount();
    const rows = bound(host);
    expect(rows).toHaveLength(3);
    expect(rows.map((r) => firstText(r))).toEqual(["Phase margin", "Step peak", "Edge peak"]);
    const node = rows[0]?.querySelector<HTMLAnchorElement>("a.pg-sim-node");
    expect(node?.getAttribute("href")).toBe(
      "#/orchestration/design-graph?run=0%2Frun-series&node=control.loop",
    );
    expect(text(rows[0])).toContain("0.5534885189031078rad");
    expect(text(rows[1])).toContain("Largest magnitude of position");
  });

  it("shows a gate record that names the quantity with its glyph, and none for a quantity none names", async () => {
    const host = await mount();
    const [phase, peak, edge] = bound(host);
    expect(phase?.querySelector(".pg-verdict-unchecked")).not.toBeNull();
    expect(text(phase)).toContain("Plausible value check");
    expect(text(phase)).toContain("check 2 · seq 40");
    expect(text(peak)).toContain("No gate record of this attempt names this quantity.");
    expect(peak?.querySelector('[class*="pg-verdict"], .pg-badge')).toBeNull();
    expect(peak?.querySelector('a[href*="gate-checks"]')).not.toBeNull();
    expect(text(edge)).toContain("The gate has not run on this attempt.");
  });

  it("shows a failing record with the range it was held to", async () => {
    const host = await mount(`subtask=${S1}&attempt=1`);
    const [peak] = bound(host);
    expect(peak?.querySelector(".pg-verdict-fail")).not.toBeNull();
    expect(text(peak)).toContain("0.1m to 1m");
    expect(text(peak)).toContain("within its sourced range");
  });

  it("says an attempt refused before the gate could not be read off, with the recorded reason", async () => {
    const host = await mount(`subtask=${S1}&attempt=2`);
    const [phase] = bound(host);
    expect(text(phase)).toContain("Could not be read off the record");
    expect(text(phase)).toContain(
      "Names the record loop_nominal, which this attempt did not seal.",
    );
    expect(text(phase)).toContain("The gate did not run: the attempt was refused before it.");
    expect(text(phase)).toContain("Not read");
  });

  it("under observe, off, an unmatched finding and an unknown word, says each as recorded", async () => {
    const host = await mount(`subtask=${S2}&attempt=1`);
    const [observed, off, unmatched, unknown, unread] = bound(host);
    expect(text(observed)).toContain("Would fail · not enforced");
    expect(observed?.querySelector(".pg-verdict-fail")).toBeNull();
    expect(text(off)).toContain("The gate did not run.");
    expect(text(unmatched)).toContain(
      "Named by the gate's finding, but it cannot be matched to one gate record.",
    );
    expect(text(unknown)).toContain("deferred · advisory");
    expect(text(unknown)).toContain("partly");
    expect(unknown?.querySelector('[class*="pg-verdict"]')).toBeNull();
    expect(text(unread)).toContain("This row could not be read:");
  });
});

describe("no what-if, and nothing that acts", () => {
  it("draws no what-if element, no dashed series and no control that runs or writes", async () => {
    const host = await mount();
    expect(
      host.querySelector(".pg-whatif, .pg-banner-whatif, .pg-plot-whatif, .pg-quantity-whatif"),
    ).toBeNull();
    expect(host.querySelector(".pg-btn-act, .pg-btn-reject")).toBeNull();
    expect([...host.querySelectorAll("button")].filter((b) => /^Run as/.test(text(b)))).toEqual([]);
    expect(host.textContent).not.toMatch(/what-if|draft/i);
  });
});

describe("the 3D and multi-domain slot", () => {
  it("is empty and says so, naming no collaborator and no command", async () => {
    const host = await mount();
    const slot = host.querySelector('[aria-label="3D and multi-domain views"]');
    expect(text(slot?.querySelector("h2"))).toBe("3D and multi-domain views");
    expect(text(slot)).toContain(
      "Tool views, such as a CAD viewer, a KiCad viewer or a co-simulation, appear here once one is added. None is added yet.",
    );
    expect(text(slot)).not.toMatch(/collaborator|physgate /i);
  });

  it("gives a registered tool view a tab of its own, and shows it when chosen", async () => {
    const view: ToolViewDef = {
      id: "probe",
      title: "Probe viewer",
      icon: "box",
      component: ({ record }) => <p className="probe-view">Probe of {record}</p>,
    };
    const host = await mount(`subtask=${S1}&attempt=3&record=step_nominal`, [view]);
    const tabs = host.querySelector('[aria-label="Views of this record"]');
    expect([...(tabs?.querySelectorAll("button") ?? [])].map(text)).toEqual([
      "Recorded series",
      "Probe viewer",
    ]);
    expect(host.querySelector('[aria-label="3D and multi-domain views"]')).toBeNull();
    act(() => {
      button(host, "Probe viewer").click();
    });
    expect(text(host.querySelector(".probe-view"))).toBe("Probe of step_nominal");
  });
});
