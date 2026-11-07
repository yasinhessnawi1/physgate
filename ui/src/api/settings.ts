/** Not built yet: a stub, so the tests that hold it have something to import. */
import type { Quantity } from "../design/quantity";
import type { Field } from "./fields";

export type RecordedOsLayer =
  | { readonly kind: "present"; readonly mechanism: string }
  | { readonly kind: "absent"; readonly reason: string; readonly noOsProtection: boolean }
  | { readonly kind: "unknown"; readonly state: string };

export interface RecordedBounds {
  readonly maxRetries: Field<Quantity>;
  readonly wallClock: Field<Quantity>;
  readonly maxTurns: Field<Quantity>;
  readonly retryDelays: Field<readonly Field<Quantity>[]>;
}

export interface PinnedModel {
  readonly key: string;
  readonly model: Field<string>;
}

export interface RecordedModels {
  readonly decomposition: Field<string>;
  readonly roles: Field<readonly PinnedModel[]>;
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

export function recordedSystem(value: unknown): RecordedSystem {
  if (value === Symbol.for("stub")) throw new Error("stub");
  const absent = { kind: "absent", missing: true } as const;
  return {
    runId: absent,
    harnessCommit: absent,
    auth: absent,
    endpoint: absent,
    claudeVersion: absent,
    effort: absent,
    maxOutputTokens: absent,
    thinkingDisplay: absent,
    gitBinary: absent,
    rolePython: absent,
    escalationBackend: absent,
    queueDecisions: absent,
    osLayerAbsent: absent,
    osLayer: absent,
    network: absent,
    networkEnforced: absent,
    tokenCeiling: absent,
    bounds: absent,
    gateMode: absent,
    designReview: absent,
    reportable: absent,
    models: absent,
  };
}
