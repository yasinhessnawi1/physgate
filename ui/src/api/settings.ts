/**
 * The system a run recorded, as the Settings screen draws it: its engine facts, its models as
 * builder and reviewer pairs, its gate and queue, its OS layer and network, and its session
 * limits. The answer is the configuration route's, the one Home and Run records also read through
 * their own guard, which is left as it is.
 *
 * Each drawn field is read alone and is its own result: read, absent, or refused with its reason.
 * A wrong field refuses its own row and nothing else; a key this version does not draw is ignored;
 * a value of an open field this version has no words for is kept as written. Absent means the
 * key is missing, or the record holds the harness's own ``null`` for "none recorded"; nothing is
 * ever filled in, from a default or from anywhere else. Only an answer, or a configuration, that
 * is not a record at all is refused whole.
 */
import type { Quantity } from "../design/quantity";
import { ShapeError } from "./client";
import {
  at,
  cell,
  type Field,
  FieldError,
  flag,
  list,
  number,
  quantity,
  record,
  text,
  whole,
} from "./fields";

export type RecordedOsLayer =
  | { readonly kind: "present"; readonly mechanism: string }
  | { readonly kind: "absent"; readonly reason: string; readonly noOsProtection: boolean }
  /** A state this version has no words for, kept as written. */
  | { readonly kind: "unknown"; readonly state: string };

export interface RecordedBounds {
  readonly maxRetries: Field<Quantity>;
  readonly wallClock: Field<Quantity>;
  readonly maxTurns: Field<Quantity>;
  /** Each delay its own item: one wrong delay refuses that delay only. */
  readonly retryDelays: Field<readonly Field<Quantity>[]>;
}

/** A model pinned under a key: a role's builder, or a reviewer by the key it is pinned under. */
export interface PinnedModel {
  readonly key: string;
  readonly model: Field<string>;
}

export interface RecordedModels {
  readonly decomposition: Field<string>;
  /** One row per role; a wrong model refuses that row only. */
  readonly roles: Field<readonly PinnedModel[]>;
  /** Read per key, as recorded: a role's reviewer, or the plan's under ``design``. */
  readonly reviewers: Field<readonly PinnedModel[]>;
}

export interface RecordedSystem {
  readonly runId: Field<string>;
  readonly harnessCommit: Field<string>;
  readonly auth: Field<string>;
  readonly endpoint: Field<string>;
  readonly claudeVersion: Field<string>;
  readonly effort: Field<string>;
  readonly maxOutputTokens: Field<Quantity>;
  readonly thinkingDisplay: Field<string>;
  readonly gitBinary: Field<{ readonly path: string; readonly version: string }>;
  readonly rolePython: Field<{
    readonly path: string;
    readonly resolved: string;
    readonly version: string;
  }>;
  readonly escalationBackend: Field<string>;
  readonly queueDecisions: Field<string>;
  readonly osLayerAbsent: Field<string>;
  readonly osLayer: Field<RecordedOsLayer>;
  readonly network: Field<string>;
  readonly networkEnforced: Field<boolean>;
  readonly tokenCeiling: Field<Quantity>;
  readonly bounds: Field<RecordedBounds>;
  readonly gateMode: Field<string>;
  readonly designReview: Field<string>;
  readonly reportable: Field<boolean>;
  readonly models: Field<RecordedModels>;
}

function osLayer(raw: unknown): RecordedOsLayer {
  const layer = record(raw);
  const state = text(layer.state, "its state");
  if (state === "present")
    return { kind: "present", mechanism: text(layer.mechanism, "its mechanism") };
  if (state === "absent")
    return {
      kind: "absent",
      reason: text(layer.reason, "its reason"),
      noOsProtection: flag(layer.no_os_protection, "whether the platform has any OS protection"),
    };
  return { kind: "unknown", state };
}

function bounds(raw: unknown): RecordedBounds {
  const b = record(raw);
  return {
    maxRetries: at(b, "binary_max_retries", quantity(whole, "retries")),
    wallClock: at(b, "session_wall_clock_s", quantity(number, "s")),
    maxTurns: at(b, "session_max_turns", quantity(whole, "turns")),
    retryDelays: at(b, "infra_retry_delays_s", (delays) =>
      list(delays).map((delay) => cell(delay, quantity(number, "s"))),
    ),
  };
}

/** Every entry of a record of models, each read alone, in the record's order. */
function pinned(raw: unknown): readonly PinnedModel[] {
  return Object.entries(record(raw)).map(([key, model]) => ({ key, model: cell(model, text) }));
}

function models(raw: unknown): RecordedModels {
  const m = record(raw);
  return {
    decomposition: at(m, "decomposition", text),
    roles: at(m, "roles", pinned),
    reviewers: at(m, "reviewers", pinned),
  };
}

/** The harness commit: absent where the record names none, or holds no harness record. */
function harnessCommit(config: Readonly<Record<string, unknown>>): Field<string> {
  const harness = at(config, "harness", (raw) => record(raw, "the harness record"));
  if (harness.kind !== "read") return harness;
  return at(harness.value, "commit", text, true);
}

export function recordedSystem(value: unknown): RecordedSystem {
  let config: Readonly<Record<string, unknown>>;
  try {
    config = record(record(value).config);
  } catch (error) {
    if (error instanceof FieldError) throw new ShapeError("a run configuration");
    throw error;
  }
  return {
    runId: at(config, "run_id", text),
    harnessCommit: harnessCommit(config),
    auth: at(config, "auth", text),
    endpoint: at(config, "endpoint", text),
    claudeVersion: at(config, "claude_version", text),
    effort: at(config, "effort", text),
    maxOutputTokens: at(config, "max_output_tokens", quantity(whole, "tokens")),
    thinkingDisplay: at(config, "thinking_display", text),
    gitBinary: at(
      config,
      "git_binary",
      (raw) => {
        const git = record(raw);
        return { path: text(git.path, "its path"), version: text(git.version, "its version") };
      },
      true,
    ),
    rolePython: at(
      config,
      "role_python",
      (raw) => {
        const python = record(raw);
        return {
          path: text(python.path, "its path"),
          resolved: text(python.resolved, "the path it resolves to"),
          version: text(python.version, "its version"),
        };
      },
      true,
    ),
    escalationBackend: at(config, "escalation_backend", text, true),
    queueDecisions: at(config, "queue_decisions", text),
    osLayerAbsent: at(config, "os_layer_absent", text),
    osLayer: at(config, "os_layer", osLayer, true),
    network: at(config, "network", text),
    networkEnforced: at(config, "network_enforced", flag, true),
    tokenCeiling: at(config, "token_ceiling", quantity(whole, "tokens")),
    bounds: at(config, "bounds", bounds),
    gateMode: at(config, "gate_mode", text),
    designReview: at(config, "design_review", text),
    reportable: at(config, "reportable", flag),
    models: at(config, "models", models),
  };
}
