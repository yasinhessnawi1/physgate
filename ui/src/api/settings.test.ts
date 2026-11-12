import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { assert, describe, expect, it } from "vitest";

import { ShapeError } from "./client";
import type { Field } from "./fields";
import { runConfig } from "./records";
import { type RecordedSystem, recordedSystem } from "./settings";

/**
 * A run's configuration as the server sends it: every key the record holds today, the plan
 * reviewer's two keys a newer harness writes, and the held-out tier's three, each with a value.
 */
function answer(): { manifest_id: string; config: Record<string, unknown>; repair_budget: number } {
  return {
    manifest_id: "f".repeat(64),
    repair_budget: 3,
    config: {
      run_id: "run-17",
      seed: 7,
      brief_sha256: "b".repeat(64),
      gate_mode: "observe",
      models: {
        decomposition: "claude-opus-5-5",
        roles: { electrical: "claude-opus-5-5", control: "claude-sonnet-5" },
        reviewers: {
          electrical: "claude-sonnet-5",
          control: "claude-opus-5-5",
          design: "claude-sonnet-5",
        },
      },
      bounds: {
        binary_max_retries: 2,
        session_wall_clock_s: 120.5,
        session_max_turns: 20,
        infra_retry_delays_s: [1, 2.5, 30],
      },
      token_ceiling: 200000,
      claude_version: "2.1.301",
      target_head: "c".repeat(40),
      endpoint: "default",
      auth: "subscription",
      reportable: true,
      harness: { commit: "a".repeat(40), clean: true, uncommitted_sha256: null },
      effort: "high",
      max_output_tokens: 32000,
      thinking_display: "summarized",
      role_python: {
        path: "/opt/py/bin/python3",
        resolved: "/opt/py/bin/python3.12",
        version: "3.12.9",
        prefix: "/opt/py",
        distributions: ["numpy==2.1.0"],
      },
      git_binary: { path: "/usr/bin/git", version: "2.47.1" },
      escalation_backend: "rules",
      queue_decisions: "record",
      os_layer_absent: "refuse",
      os_layer: { state: "present", mechanism: "seatbelt", claude_version: "2.1.301" },
      network: "none",
      network_enforced: true,
      design_review: "observe",
      held_out: ["/srv/held/tier-a"],
      held_out_canaries: ["CANARY-held-0001"],
      held_out_sha256: ["9".repeat(64)],
    },
  };
}

const read = <T>(value: T): Field<T> => ({ kind: "read", value });

/** Everything the guard draws from ``answer()``, as it must read it. */
const WHOLE: RecordedSystem = {
  runId: read("run-17"),
  harnessCommit: read("a".repeat(40)),
  auth: read("subscription"),
  endpoint: read("default"),
  claudeVersion: read("2.1.301"),
  effort: read("high"),
  maxOutputTokens: read({ value: 32000, unit: "tokens" }),
  thinkingDisplay: read("summarized"),
  gitBinary: read({ path: "/usr/bin/git", version: "2.47.1" }),
  rolePython: read({
    path: "/opt/py/bin/python3",
    resolved: "/opt/py/bin/python3.12",
    version: "3.12.9",
  }),
  escalationBackend: read("rules"),
  queueDecisions: read("record"),
  osLayerAbsent: read("refuse"),
  osLayer: read({ kind: "present", mechanism: "seatbelt" }),
  network: read("none"),
  networkEnforced: read(true),
  tokenCeiling: read({ value: 200000, unit: "tokens" }),
  bounds: read({
    maxRetries: read({ value: 2, unit: "retries" }),
    wallClock: read({ value: 120.5, unit: "s" }),
    maxTurns: read({ value: 20, unit: "turns" }),
    retryDelays: read([
      read({ value: 1, unit: "s" }),
      read({ value: 2.5, unit: "s" }),
      read({ value: 30, unit: "s" }),
    ]),
  }),
  gateMode: read("observe"),
  designReview: read("observe"),
  reportable: read(true),
  models: read({
    decomposition: read("claude-opus-5-5"),
    roles: read([
      { key: "electrical", model: read("claude-opus-5-5") },
      { key: "control", model: read("claude-sonnet-5") },
    ]),
    reviewers: read([
      { key: "electrical", model: read("claude-sonnet-5") },
      { key: "control", model: read("claude-opus-5-5") },
      { key: "design", model: read("claude-sonnet-5") },
    ]),
  }),
};

/** ``answer()`` with one key of its configuration set to ``value``, or removed. */
function withKey(key: string, value: unknown, remove = false) {
  const a = answer();
  if (remove) Reflect.deleteProperty(a.config, key);
  else a.config[key] = value;
  return a;
}

/** Each drawn top-level key, the field it is drawn as, and a value of the wrong type. */
const DRAWN: readonly (readonly [string, keyof RecordedSystem, unknown])[] = [
  ["run_id", "runId", 7],
  ["auth", "auth", 1],
  ["endpoint", "endpoint", ["default"]],
  ["claude_version", "claudeVersion", 2],
  ["effort", "effort", true],
  ["max_output_tokens", "maxOutputTokens", 1.5],
  ["thinking_display", "thinkingDisplay", {}],
  ["git_binary", "gitBinary", "/usr/bin/git"],
  ["role_python", "rolePython", { path: 1, resolved: "/x", version: "3.12" }],
  ["escalation_backend", "escalationBackend", 3],
  ["queue_decisions", "queueDecisions", null],
  ["os_layer_absent", "osLayerAbsent", 1],
  ["os_layer", "osLayer", { state: 7 }],
  ["network", "network", 0],
  ["network_enforced", "networkEnforced", "yes"],
  ["token_ceiling", "tokenCeiling", "200000"],
  ["bounds", "bounds", [1, 2]],
  ["gate_mode", "gateMode", 1],
  ["design_review", "designReview", 2],
  ["reportable", "reportable", "true"],
  ["models", "models", "claude-opus-5-5"],
  ["harness", "harnessCommit", 5],
];

/** The fields of ``got`` other than ``except``, which must equal the whole read's. */
function othersWhole(got: RecordedSystem, except: keyof RecordedSystem) {
  const others = (r: RecordedSystem) =>
    Object.fromEntries(Object.entries(r).filter(([k]) => k !== except));
  expect(others(got)).toEqual(others(WHOLE));
}

describe("the recorded system is read field by field", () => {
  it("reads every drawn field of a whole configuration", () => {
    expect(recordedSystem(answer())).toEqual(WHOLE);
  });

  it.each(DRAWN)(
    "%s of the wrong type refuses its own field only, with a reason",
    (key, name, wrong) => {
      const got = recordedSystem(withKey(key, wrong));
      expect(got[name].kind).toBe("refused");
      const field = got[name];
      expect(field.kind === "refused" ? field.reason : "").not.toBe("");
      othersWhole(got, name);
    },
  );

  it.each(DRAWN)("%s missing reads as not recorded, and nothing else changes", (key, name) => {
    const got = recordedSystem(withKey(key, undefined, true));
    expect(got[name]).toEqual({ kind: "absent", missing: true });
    othersWhole(got, name);
  });

  it.each([
    ["role_python", "rolePython"],
    ["git_binary", "gitBinary"],
    ["os_layer", "osLayer"],
    ["escalation_backend", "escalationBackend"],
    ["network_enforced", "networkEnforced"],
  ] as const)("%s null is the harness's own 'none recorded', never a refusal", (key, name) => {
    const got = recordedSystem(withKey(key, null));
    expect(got[name]).toEqual({ kind: "absent", missing: false });
    othersWhole(got, name);
  });

  it("a harness commit of null is the harness's own 'no commit'", () => {
    const a = answer();
    a.config.harness = { commit: null, clean: false, uncommitted_sha256: "d".repeat(64) };
    const got = recordedSystem(a);
    expect(got.harnessCommit).toEqual({ kind: "absent", missing: false });
    othersWhole(got, "harnessCommit");
  });

  it("a null where the harness always writes a value is refused, not taken as absent", () => {
    for (const key of ["auth", "effort", "token_ceiling", "reportable", "design_review"]) {
      const got = recordedSystem(withKey(key, null));
      const name = DRAWN.find(([k]) => k === key)?.[1] ?? "auth";
      expect(got[name].kind, key).toBe("refused");
    }
  });
});

describe("a nested record is read element by element", () => {
  function bounds(changes: Record<string, unknown>) {
    const a = answer();
    a.config.bounds = { ...(a.config.bounds as Record<string, unknown>), ...changes };
    const got = recordedSystem(a);
    othersWhole(got, "bounds");
    if (got.bounds.kind !== "read") assert.fail("the bounds were not read");
    return got.bounds.value;
  }

  it("a wrong limit refuses that limit only", () => {
    const wholeBounds = WHOLE.bounds.kind === "read" ? WHOLE.bounds.value : null;
    const got = bounds({ session_max_turns: 2.5 });
    expect(got.maxTurns.kind).toBe("refused");
    expect(got.maxRetries).toEqual(wholeBounds?.maxRetries);
    expect(got.wallClock).toEqual(wholeBounds?.wallClock);
    expect(got.retryDelays).toEqual(wholeBounds?.retryDelays);
    expect(bounds({ binary_max_retries: "2" }).maxRetries.kind).toBe("refused");
    expect(bounds({ session_wall_clock_s: "120" }).wallClock.kind).toBe("refused");
    expect(bounds({ infra_retry_delays_s: "1, 2" }).retryDelays.kind).toBe("refused");
  });

  it("a wrong retry delay refuses that delay only", () => {
    const delays = bounds({ infra_retry_delays_s: [1, "two", 4] }).retryDelays;
    if (delays.kind !== "read") assert.fail("the delays were not read");
    expect(delays.value.map((d) => d.kind)).toEqual(["read", "refused", "read"]);
    expect(delays.value[2]).toEqual(read({ value: 4, unit: "s" }));
  });

  it("an empty list of delays is read as empty", () => {
    expect(bounds({ infra_retry_delays_s: [] }).retryDelays).toEqual(read([]));
  });

  function models(changes: Record<string, unknown>) {
    const a = answer();
    a.config.models = { ...(a.config.models as Record<string, unknown>), ...changes };
    const got = recordedSystem(a);
    othersWhole(got, "models");
    if (got.models.kind !== "read") assert.fail("the models were not read");
    return got.models.value;
  }

  it("a role's bad model refuses that role's row only", () => {
    const got = models({ roles: { electrical: 5, control: "claude-sonnet-5" } });
    if (got.roles.kind !== "read") assert.fail("the roles were not read");
    expect(got.roles.value[0]?.key).toBe("electrical");
    expect(got.roles.value[0]?.model.kind).toBe("refused");
    expect(got.roles.value[1]).toEqual({ key: "control", model: read("claude-sonnet-5") });
    expect(got.decomposition).toEqual(read("claude-opus-5-5"));
    expect(got.reviewers.kind).toBe("read");
  });

  it("roles that are not a record refuse the table's body, and keep the decomposition", () => {
    const got = models({ roles: ["electrical"] });
    expect(got.roles.kind).toBe("refused");
    expect(got.decomposition).toEqual(read("claude-opus-5-5"));
    expect(got.reviewers.kind).toBe("read");
  });

  it("a reviewer's bad model refuses that reviewer only, and never a role's row", () => {
    const got = models({ reviewers: { electrical: null, control: "claude-opus-5-5" } });
    if (got.reviewers.kind !== "read" || got.roles.kind !== "read") assert.fail("not read");
    expect(got.reviewers.value[0]?.model.kind).toBe("refused");
    expect(got.reviewers.value[1]).toEqual({ key: "control", model: read("claude-opus-5-5") });
    expect(got.roles.value.map((r) => r.model.kind)).toEqual(["read", "read"]);
  });

  it("a reviewer key that names no role is kept as written", () => {
    const got = models({ reviewers: { firmware: "claude-sonnet-5" } });
    expect(got.reviewers).toEqual(read([{ key: "firmware", model: read("claude-sonnet-5") }]));
  });

  it("a missing decomposition reads as not recorded, and the roles still read", () => {
    const a = answer();
    const m = { ...(a.config.models as Record<string, unknown>) };
    delete m.decomposition;
    a.config.models = m;
    const got = recordedSystem(a);
    if (got.models.kind !== "read") assert.fail("the models were not read");
    expect(got.models.value.decomposition).toEqual({ kind: "absent", missing: true });
    expect(got.models.value.roles.kind).toBe("read");
  });

  it("an OS layer whose state is malformed refuses that row only", () => {
    for (const layer of [
      { state: "present" },
      { state: "present", mechanism: 4 },
      { state: "absent", reason: 1, no_os_protection: false },
      { state: "absent", reason: "bwrap missing", no_os_protection: "no" },
      ["present"],
    ]) {
      const got = recordedSystem(withKey("os_layer", layer));
      expect(got.osLayer.kind, JSON.stringify(layer)).toBe("refused");
      othersWhole(got, "osLayer");
    }
  });

  it("reads an absent OS layer with its reason, and an unknown state as written", () => {
    expect(
      recordedSystem(
        withKey("os_layer", {
          state: "absent",
          reason: "macOS: sandbox-exec is missing",
          no_os_protection: false,
        }),
      ).osLayer,
    ).toEqual(
      read({ kind: "absent", reason: "macOS: sandbox-exec is missing", noOsProtection: false }),
    );
    expect(
      recordedSystem(withKey("os_layer", { state: "partial", mechanism: "seatbelt" })).osLayer,
    ).toEqual(read({ kind: "unknown", state: "partial" }));
    expect(
      recordedSystem(withKey("os_layer", { state: "present", mechanism: "landlock" })).osLayer,
    ).toEqual(read({ kind: "present", mechanism: "landlock" }));
  });

  it("a role's interpreter or git binary missing a part is refused, not filled", () => {
    expect(
      recordedSystem(withKey("role_python", { path: "/p", version: "3.12" })).rolePython.kind,
    ).toBe("refused");
    expect(recordedSystem(withKey("git_binary", { path: "/usr/bin/git" })).gitBinary.kind).toBe(
      "refused",
    );
  });

  it("a harness record without a commit reads as not recorded", () => {
    const got = recordedSystem(withKey("harness", { clean: true }));
    expect(got.harnessCommit).toEqual({ kind: "absent", missing: true });
    expect(recordedSystem(withKey("harness", { commit: 7 })).harnessCommit.kind).toBe("refused");
  });
});

describe("what the guard does not draw changes nothing", () => {
  it("an unknown key is ignored", () => {
    expect(recordedSystem(withKey("an_unknown_field", { nested: [1, 2, 3] }))).toEqual(WHOLE);
  });

  it("an unknown value of an open field is kept as written", () => {
    expect(recordedSystem(withKey("effort", "turbo")).effort).toEqual(read("turbo"));
    expect(recordedSystem(withKey("design_review", "repair:9")).designReview).toEqual(
      read("repair:9"),
    );
    expect(recordedSystem(withKey("gate_mode", "audit")).gateMode).toEqual(read("audit"));
  });

  const HELD = ["held_out", "held_out_canaries", "held_out_sha256"] as const;

  it("reads the same whether the held-out keys are present, absent or replaced by a count", () => {
    const present = answer();
    const absent = answer();
    for (const key of HELD) Reflect.deleteProperty(absent.config, key);
    const counted = answer();
    for (const key of HELD) counted.config[key] = 1;
    for (const a of [present, absent, counted]) expect(recordedSystem(a)).toEqual(WHOLE);
  });

  it("carries no value of the held-out keys", () => {
    const text = JSON.stringify(recordedSystem(answer()));
    for (const key of HELD) {
      const values = answer().config[key] as readonly string[];
      for (const value of values) expect(text).not.toContain(value);
    }
  });

  it("the guard's source names none of the held-out keys", () => {
    const source = readFileSync(fileURLToPath(new URL("./settings.ts", import.meta.url)), "utf8");
    expect(source).not.toMatch(/held_out/);
  });
});

describe("numbers are the record's own, whole where the record has whole numbers", () => {
  it("refuses a whole number beyond what a page can hold exactly", () => {
    const got = recordedSystem(withKey("token_ceiling", 2 ** 53));
    expect(got.tokenCeiling.kind).toBe("refused");
    expect(recordedSystem(withKey("token_ceiling", 2 ** 53 - 1)).tokenCeiling).toEqual(
      read({ value: 2 ** 53 - 1, unit: "tokens" }),
    );
  });

  it("refuses a fraction where the record holds a whole number", () => {
    expect(recordedSystem(withKey("token_ceiling", 1000.5)).tokenCeiling.kind).toBe("refused");
    expect(recordedSystem(withKey("max_output_tokens", 8.25)).maxOutputTokens.kind).toBe("refused");
  });

  it("keeps a fraction where the record holds one, unrounded", () => {
    const a = answer();
    a.config.bounds = {
      ...(a.config.bounds as Record<string, unknown>),
      session_wall_clock_s: 0.1 + 0.2,
    };
    const got = recordedSystem(a);
    if (got.bounds.kind !== "read") assert.fail("the bounds were not read");
    expect(got.bounds.value.wallClock).toEqual(read({ value: 0.1 + 0.2, unit: "s" }));
  });
});

describe("the one whole refusal", () => {
  it("is an answer, or a configuration, that is not a record", () => {
    for (const bad of [null, [], "x", 3, { config: null }, { config: [] }, { config: "x" }, {}])
      expect(() => recordedSystem(bad), JSON.stringify(bad)).toThrow(ShapeError);
  });

  it("is never a configuration with every drawn field wrong", () => {
    const a = answer();
    for (const [key, , wrong] of DRAWN) a.config[key] = wrong;
    const got = recordedSystem(a);
    for (const [, name] of DRAWN) expect(got[name].kind, name).toBe("refused");
  });
});

describe("the guard Home and Run records read is not changed", () => {
  it("reads the same answer exactly as before", () => {
    expect(runConfig(answer())).toEqual({
      manifestId: "f".repeat(64),
      runId: "run-17",
      gateMode: "observe",
      harnessCommit: "a".repeat(40),
      auth: "subscription",
      briefSha256: "b".repeat(64),
      seed: 7,
      roleModels: { electrical: "claude-opus-5-5", control: "claude-sonnet-5" },
      decompositionModel: "claude-opus-5-5",
      reviewerModels: {
        electrical: "claude-sonnet-5",
        control: "claude-opus-5-5",
        design: "claude-sonnet-5",
      },
      osLayer: { state: "present", mechanism: "seatbelt" },
      repairBudget: 3,
    });
  });

  it("still refuses what it refused, and still passes what it does not read", () => {
    expect(() => runConfig(withKey("auth", 1))).toThrow(ShapeError);
    expect(runConfig(withKey("effort", 1)).runId).toBe("run-17");
  });
});
