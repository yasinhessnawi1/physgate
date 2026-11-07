import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { assert, describe, expect, it } from "vitest";

import { ShapeError } from "./client";
import { type Engine, engineCatalogue, type EngineEntry, isAvailable } from "./engines";

/** The checkout's own catalogue, as the server reads it once at start. */
const REAL = JSON.parse(
  readFileSync(
    fileURLToPath(new URL("../../../desktop/onboarding/engines.json", import.meta.url)),
    "utf8",
  ),
) as { engines: Record<string, unknown>[] };

/** The engine catalogue's answer as the server sends it, around ``catalogue``. */
function answer(catalogue: unknown = REAL) {
  return {
    file: "desktop/onboarding/engines.json",
    sha256: "e".repeat(64),
    length: 2243,
    catalogue,
  };
}

function engines(...entries: unknown[]): readonly EngineEntry[] {
  return engineCatalogue(answer({ engines: entries })).engines;
}

function only(...entries: unknown[]): Engine {
  const [first] = engines(...entries);
  if (first?.kind !== "read") assert.fail("the entry was not read");
  return first.engine;
}

describe("the catalogue's answer", () => {
  it("reads the file, its digest, its length in bytes and every engine, in order", () => {
    const got = engineCatalogue(answer());
    expect(got.file).toBe("desktop/onboarding/engines.json");
    expect(got.sha256).toBe("e".repeat(64));
    expect(got.length).toEqual({ value: 2243, unit: "B" });
    expect(got.engines.map((e) => (e.kind === "read" ? e.engine.id : e.reason))).toEqual(
      REAL.engines.map((e) => e.id),
    );
  });

  it("reads the real catalogue's models, defaults and local models", () => {
    const got = engineCatalogue(answer()).engines;
    const api = got.find((e) => e.kind === "read" && e.engine.id === "claude-api");
    if (api?.kind !== "read") assert.fail("no API engine");
    expect(api.engine.models).toEqual({
      kind: "read",
      value: [
        { kind: "read", id: "claude-opus-5-5", label: "Claude Opus 5.5" },
        { kind: "read", id: "claude-sonnet-5", label: "Claude Sonnet 5" },
        { kind: "read", id: "claude-haiku-4-5-20251001", label: "Claude Haiku 4.5" },
      ],
    });
    expect(api.engine.defaults).toEqual({
      kind: "read",
      value: {
        implementer: { kind: "read", value: "claude-opus-5-5" },
        reviewer: { kind: "read", value: "claude-sonnet-5" },
      },
    });
    const local = got.find((e) => e.kind === "read" && e.engine.id === "local");
    if (local?.kind !== "read" || local.engine.localModels.kind !== "read")
      assert.fail("no local models");
    expect(local.engine.localModels.value[0]).toEqual({
      kind: "read",
      name: "Llama 3.1 8B Instruct",
      memory: { kind: "read", value: { value: 6, unit: "GB" } },
      disk: { kind: "read", value: { value: 5, unit: "GB" } },
      licence: { kind: "read", value: "Llama 3.1 Community License" },
      source: { kind: "read", value: "https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct" },
    });
  });

  it.each([
    ["the file", { file: 3 }],
    ["the digest", { sha256: "abc" }],
    ["the digest, in capitals", { sha256: "E".repeat(64) }],
    ["the length", { length: 2243.5 }],
    ["the length, as text", { length: "2243" }],
    ["the catalogue", { catalogue: [] }],
    ["the engine list", { catalogue: { engines: {} } }],
    ["the engine list, missing", { catalogue: { _about: "x" } }],
  ])("refuses the whole section when %s is wrong", (_, change) => {
    expect(() => engineCatalogue({ ...answer(), ...change })).toThrow(ShapeError);
  });

  it("refuses an answer that is not a record", () => {
    for (const bad of [null, [], "x"]) expect(() => engineCatalogue(bad)).toThrow(ShapeError);
  });

  it("ignores every key it does not draw, at every level", () => {
    const plain = only({ id: "a", name: "A", status: "available" });
    const extra = engineCatalogue(
      answer({
        _about: "prose the guard never parses",
        held: { layers: 2 },
        engines: [{ id: "a", name: "A", status: "available", pairs: [[1, 2]], tier: "x" }],
      }),
    ).engines[0];
    expect(extra).toEqual({ kind: "read", engine: plain });
  });
});

describe("each engine is read alone", () => {
  it.each([
    ["not a record", "claude-code"],
    ["a list", ["claude-code"]],
    ["no id", { name: "Claude Code" }],
    ["an id that is not text", { id: 3, name: "Claude Code" }],
    ["no name", { id: "claude-code" }],
    ["a name that is not text", { id: "claude-code", name: { en: "Claude Code" } }],
  ])("an entry with %s is a row with its reason, and the others render", (_, bad) => {
    const got = engines({ id: "a", name: "A", status: "available" }, bad, {
      id: "b",
      name: "B",
      status: "not-yet",
    });
    expect(got.map((e) => e.kind)).toEqual(["read", "refused", "read"]);
    const refused = got[1];
    expect(refused?.kind === "refused" ? refused.reason : "").not.toBe("");
  });

  it.each([
    ["detail", 4],
    ["auth", ["subscription"]],
    ["status", 1],
    ["models", { id: "m" }],
    ["defaults", "claude-opus-5-5"],
    ["local_models", "none"],
  ] as const)("a wrong %s refuses that part of its row only", (key, wrong) => {
    const whole = {
      id: "e",
      name: "E",
      detail: "d",
      auth: "api_key",
      status: "available",
      models: [{ id: "m", label: "M" }],
      defaults: { implementer: "m", reviewer: "m" },
      local_models: [],
    };
    const good = only(whole);
    const got = only({ ...whole, [key]: wrong });
    const name = (
      {
        detail: "detail",
        auth: "auth",
        status: "status",
        models: "models",
        defaults: "defaults",
        local_models: "localModels",
      } as const
    )[key];
    expect(got[name].kind).toBe("refused");
    expect({ ...got, [name]: null }).toEqual({ ...good, [name]: null });
  });

  it("a missing optional part reads as absent", () => {
    const got = only({ id: "e", name: "E" });
    for (const part of ["detail", "auth", "status", "models", "defaults", "localModels"] as const)
      expect(got[part]).toEqual({ kind: "absent", missing: true });
  });

  it("a bad model entry refuses that model only", () => {
    const got = only({
      id: "e",
      name: "E",
      models: [{ id: "m1", label: "M1" }, { id: 2, label: "M2" }, "m3", { id: "m4", label: "M4" }],
    }).models;
    if (got.kind !== "read") assert.fail("the models were not read");
    expect(got.value.map((m) => m.kind)).toEqual(["read", "refused", "refused", "read"]);
  });

  it("a wrong default refuses that default only", () => {
    const got = only({ id: "e", name: "E", defaults: { implementer: "m", reviewer: 5 } }).defaults;
    if (got.kind !== "read") assert.fail("the defaults were not read");
    expect(got.value.implementer).toEqual({ kind: "read", value: "m" });
    expect(got.value.reviewer.kind).toBe("refused");
    const half = only({ id: "e", name: "E", defaults: { reviewer: "m" } }).defaults;
    if (half.kind !== "read") assert.fail("the defaults were not read");
    expect(half.value.implementer).toEqual({ kind: "absent", missing: true });
  });

  it("a local model's size that is not a number refuses its cell only", () => {
    const got = only({
      id: "local",
      name: "Local",
      local_models: [
        { name: "M", memory_gb: "6", disk_gb: 5, licence: "L", source: "S" },
        { memory_gb: 6 },
        { name: "N", memory_gb: 6.5, disk_gb: null, licence: 3, source: "S" },
      ],
    }).localModels;
    if (got.kind !== "read") assert.fail("the local models were not read");
    const [first, second, third] = got.value;
    if (first?.kind !== "read" || third?.kind !== "read") assert.fail("not read");
    expect(first.memory.kind).toBe("refused");
    expect(first.disk).toEqual({ kind: "read", value: { value: 5, unit: "GB" } });
    expect(second?.kind).toBe("refused");
    expect(third.memory).toEqual({ kind: "read", value: { value: 6.5, unit: "GB" } });
    expect(third.disk.kind).toBe("refused");
    expect(third.licence.kind).toBe("refused");
    expect(third.source).toEqual({ kind: "read", value: "S" });
  });
});

describe("an engine's status is open", () => {
  it("only 'available' is available; every other status, or none, is inert", () => {
    expect(isAvailable(only({ id: "a", name: "A", status: "available" }))).toBe(true);
    for (const status of ["not-yet", "available — not for evaluation", "unsupported", "Available"])
      expect(isAvailable(only({ id: "a", name: "A", status })), status).toBe(false);
    expect(isAvailable(only({ id: "a", name: "A" }))).toBe(false);
    expect(isAvailable(only({ id: "a", name: "A", status: 1 }))).toBe(false);
  });

  it("keeps an unknown status as written", () => {
    expect(only({ id: "a", name: "A", status: "unsupported" }).status).toEqual({
      kind: "read",
      value: "unsupported",
    });
  });
});
