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
