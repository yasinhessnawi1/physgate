/**
 * The Evidence routes' answers the screen's unit tests serve, shaped as the server sends them:
 * the six runs of the browser tests' fixture, one run's spend, a comparison and the catch count.
 * Only tests import this file.
 */

export const COMMIT = "0123456789abcdef0123456789abcdef01234567";
export const VIEW =
  "a view: each session's priced call, summed by the role its subtask was planned for";
/** A held-out tier's digest and canary, as a server must never send them. */
export const DIGEST = "d".repeat(64);
export const CANARY = "9a1e7c0d5b3f42e8a6c1d0f7b2e94a37";

const manifest = (digit: string) => digit.repeat(64);

export function readRow(name: string, kind: string, digit: string) {
  return {
    root: 0,
    name,
    run_id: `r-${name}`,
    seed: 7,
    manifest_id: manifest(digit),
    kind,
    flags: {
      gate_mode: kind === "development" ? "observe" : "on",
      harness: { commit: COMMIT, clean: true, uncommitted_sha256: null },
      reportable: kind === "reportable",
      ablation: kind === "ablation",
      hooks: kind === "ablation" ? "off" : "on",
    },
    pins: {
      "models.decomposition": "model-plan",
      "models.roles": { control: "model-role" },
      max_output_tokens: 64000,
    },
  };
}

export const TAMPERED = {
  root: 0,
  name: "ev-tampered",
  error: "the run's configuration is not the one its first log line names",
  record: "run.json",
};

export const UNREADABLE = {
  root: 0,
  name: "ev-unreadable",
  error: "the event log holds a line of a kind this package does not know",
  record: "events.jsonl",
  offset: "4211",
  reason: "unknown kind",
};

/** The run list as the server orders it: by name, so the ablation run comes first. */
export const RUNS = {
  runs: [
    readRow("ev-ablation", "ablation", "1"),
    readRow("ev-development", "development", "2"),
    readRow("ev-drifted", "development", "3"),
    readRow("ev-reportable", "reportable", "4"),
    TAMPERED,
    UNREADABLE,
  ],
};

export function source(name: string, kind: string, digit: string) {
  return {
    root: 0,
    name,
    run_id: `r-${name}`,
    manifest_id: manifest(digit),
    kind,
    harness_commit: COMMIT,
    harness_clean: true,
  };
}

const TOKENS = {
  input_tokens: 1200,
  output_tokens: 340,
  cache_read_input_tokens: 5000,
  cache_creation_input_tokens: 800,
};

export function call(attribution: string, usd: string, lowerBound = false, sealBroken = false) {
  return {
    attribution,
    model: "model-role",
    tokens: TOKENS,
    cache_writes: { five_minute: 800, one_hour: 0 },
    usd,
    binary_usd: null,
    agrees: null,
    seal_broken: sealBroken,
    lower_bound: lowerBound,
  };
}

function session(id: string, attempt: number, lowerBound = false, sealBroken = false) {
  return {
    ...call(`session:${id}`, "0.123456", lowerBound, sealBroken),
    session_id: id,
    subtask_id: "s1-af41ca",
    attempt,
    outcome: "completed",
  };
}

export const SPEND = {
  source: source("ev-development", "development", "2"),
  line: {
    manifest_id: manifest("2"),
    run_id: "r-ev-development",
    started: "2026-11-15T10:00:00Z",
    auth: "api_key",
    endpoint: "https://api.example.org",
    basis: "list_price_estimate",
    prices_date: "2026-11-01",
    usd_to_nok: "10.9",
    usd_to_nok_date: "2026-11-01",
    rows: [{ model: "model-role", tokens: TOKENS, usd: "0.256912" }],
    usd: "0.256912",
    nok: "2.8003408",
    partial: false,
    lower_bound: true,
    reconciliation: {
      binary_usd: "0.2",
      priced_usd: "0.256912",
      differs: [],
      unread: ["session:s-2"],
      ttl_unread: [],
      seal_broken: ["session:s-2"],
    },
    review_tokens: {},
    calls: [],
  },
  view: VIEW,
  roles: [
    {
      role: "control",
      sum: {
        tokens: {
          input_tokens: 2400,
          output_tokens: 680,
          cache_read_input_tokens: 10000,
          cache_creation_input_tokens: 1600,
        },
        usd: "0.246912",
        lower_bound: true,
      },
      sessions: [session("s-1", 1), session("s-2", 2, true, true)],
    },
  ],
  apart: {
    decomposition: {
      sum: { tokens: TOKENS, usd: "0.01", lower_bound: false },
      calls: [call("decomposition:d-1", "0.01")],
    },
    review: { sum: null, calls: [] },
    routing: { sum: null, calls: [] },
    left_over: { sum: null, calls: [] },
  },
};

export function numbers(name: string, overrides: Record<string, unknown> = {}) {
  return {
    manifest_id: manifest("2"),
    run_id: `r-${name}`,
    gate_mode: "observe",
    auth: "api_key",
    effort: "high",
    max_output_tokens: 64000,
    thinking_display: "summarized",
    escalation_backend: null,
    queue_decisions: "record",
    design_review: "on",
    reviewers: "on",
    skills: "on",
    hooks: "on",
    ablation: false,
    harness_commit: COMMIT,
    harness_clean: true,
    reportable: false,
    tokens: { input_tokens: 1200, output_tokens: 340 },
    sessions: 3,
    attempts_merged: 1,
    attempts_rejected: 1,
    subtasks_escalated: 0,
    integration: null,
    wall_clock_s: 12.5,
    ...overrides,
  };
}

export const COMPARED = {
  a: source("ev-development", "development", "2"),
  b: source("ev-ablation", "ablation", "1"),
  comparison: {
    baseline: numbers("ev-development"),
    candidate: numbers("ev-ablation", { hooks: "off", ablation: true, wall_clock_s: 9.25 }),
    differs_in: ["ablation", "hooks"],
    notes: [],
  },
};

export const DRIFTED = {
  error: "the two runs were pinned to different settings",
  drifted: ["models.decomposition", "max_output_tokens", "held_out_sha256"],
  a: source("ev-development", "development", "2"),
  b: source("ev-drifted", "development", "3"),
};

export function catchRow(gateMode: string, check: number | null, name: string, caught: number) {
  return {
    gate_mode: gateMode,
    check,
    name,
    checks_run: 4,
    blocking_failures: 2,
    reviewer_had_passed: 1,
    reviewer_had_failed: 1,
    no_review: 0,
    artefacts_caught: 2,
    caught_after_reviewer_passed: caught,
  };
}

export const CATCHES = {
  kinds: [
    {
      kind: "reportable",
      runs: [source("ev-reportable", "reportable", "4")],
      rows: [catchRow("on", null, "all", 1), catchRow("on", 2, "magnitude", 1)],
    },
    {
      kind: "development",
      runs: [
        source("ev-development", "development", "2"),
        source("ev-drifted", "development", "3"),
      ],
      rows: [catchRow("observe", null, "all", 0)],
    },
    { kind: "ablation", runs: [source("ev-ablation", "ablation", "1")], rows: [] },
  ],
  unread: [UNREADABLE],
};

// -- the gap trend ------------------------------------------------------------------------------

/** A tier version, as a trend line names it. */
export const TIER_VERSION = `3f70a6d8${"c".repeat(56)}`;
export const FLOOR =
  "a noise floor until the optimiser runs: neither tier has been seen by anything";
export const BOOTSTRAP = "task-cluster bootstrap 95 %, 1000 draws, seed 7";
export const EXPOSED =
  "the tier version 3f70a6d8 is marked exposed as the register reads now: it has been seen since this line was measured";
export const UNVERIFIED = "a vector the line names has no gaps measurement in the register";
export const READER_REFUSAL =
  "the trend's last line (line 3) is cut: a write stopped part way through it, before its head moved. The head records 2 line(s); a person removes the bytes after the end of line 2, and the trend reads again";

/** A tier's count as the route serves it: its rate as the reader wrote it, and what failed. */
function tierCount(rate: string) {
  return { rate, unscored: 0, flaky: 0 };
}

/** A trend line as the route serves it, its numbers given; ``over`` changes any field. */
export function gapLine(week: string, over: Record<string, unknown> = {}) {
  return {
    week,
    version: TIER_VERSION,
    measurements: 2,
    numbers: {
      visible: tierCount("3/4 · 75.0 % [30.1, 95.4]"),
      validation: null,
      held_out: tierCount("1/4 · 25.0 % [4.6, 69.9]"),
      reward_hacking: { gap: 0.5, interval: [0.0, 1.0], words: BOOTSTRAP, label: null },
      optimiser_overfit: null,
    },
    unverified: null,
    exposed_since: null,
    ...over,
  };
}

/** The second measurement: both gaps, the validation tier measured, the version seen since. */
export const SECOND = gapLine("2026-W47", {
  measurements: 3,
  numbers: {
    visible: tierCount("4/4 · 100.0 % [51.0, 100.0]"),
    validation: tierCount("2/4 · 50.0 % [15.0, 85.0]"),
    held_out: tierCount("1/4 · 25.0 % [4.6, 69.9]"),
    reward_hacking: { gap: 0.75, interval: [0.5, 1.0], words: BOOTSTRAP, label: null },
    optimiser_overfit: { gap: 0.25, interval: [-0.125, 0.5], words: BOOTSTRAP, label: FLOOR },
  },
  exposed_since: EXPOSED,
});

export const READ_AT = "2026-11-18T10:02:00Z";

/** The control role's trend of two measurements and a week between with none; firmware none. */
export const GAPS = {
  roles: [
    {
      role: "control",
      state: "read",
      read_at: READ_AT,
      weeks: [
        { week: "2026-W45", lines: [gapLine("2026-W45")], missing: false },
        { week: "2026-W46", lines: [], missing: true },
        { week: "2026-W47", lines: [SECOND], missing: false },
      ],
    },
    { role: "firmware", state: "none" },
  ],
};

/** One measurement alone. */
export const ONE_POINT = {
  roles: [
    {
      role: "control",
      state: "read",
      read_at: READ_AT,
      weeks: [{ week: "2026-W47", lines: [gapLine("2026-W47")], missing: false }],
    },
    { role: "firmware", state: "none" },
  ],
};

/** A trend the reader refused as it was published. */
export const REFUSED_TREND = {
  roles: [
    {
      role: "control",
      state: "refused",
      error: READER_REFUSAL,
      reason: "trend_unreadable",
      read_at: READ_AT,
    },
    { role: "firmware", state: "none" },
  ],
};
