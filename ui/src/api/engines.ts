/**
 * The engine catalogue as the server read it from this checkout at start: the file it came from,
 * its digest and length, and its engines. The server guarantees the answer's shape, so a wrong one
 * refuses the whole Engines section. Inside it, each engine is read alone, and so is each part of
 * it the screen draws: a wrong entry is a row with its reason, a wrong part leaves its place in the
 * row with its reason, and the rest renders. A key the screen does not draw is ignored, which is
 * how a later catalogue with more in it still reads.
 */
import { requireQuantity, type Quantity } from "../design/quantity";
import { ShapeError } from "./client";
import { at, type Field, FieldError, list, number, quantity, record, text } from "./fields";

export type CatalogueModel =
  | { readonly kind: "read"; readonly id: string; readonly label: string }
  | { readonly kind: "refused"; readonly reason: string };

export type LocalModel =
  | {
      readonly kind: "read";
      readonly name: string;
      readonly memory: Field<Quantity>;
      readonly disk: Field<Quantity>;
      readonly licence: Field<string>;
      readonly source: Field<string>;
    }
  | { readonly kind: "refused"; readonly reason: string };

/** The catalogue's own defaults for an engine's models: never a run's. */
export interface CatalogueDefaults {
  readonly implementer: Field<string>;
  readonly reviewer: Field<string>;
}

export interface Engine {
  readonly id: string;
  readonly name: string;
  readonly detail: Field<string>;
  readonly auth: Field<string>;
  /** Open: the catalogue may name statuses this version has no words for. */
  readonly status: Field<string>;
  readonly models: Field<readonly CatalogueModel[]>;
  readonly defaults: Field<CatalogueDefaults>;
  readonly localModels: Field<readonly LocalModel[]>;
}

export type EngineEntry =
  | { readonly kind: "read"; readonly engine: Engine }
  | { readonly kind: "refused"; readonly reason: string };

export interface EngineCatalogue {
  /** The file inside the checkout, never an absolute path. */
  readonly file: string;
  readonly sha256: string;
  readonly length: Quantity;
  readonly engines: readonly EngineEntry[];
}

const SHA256 = /^[0-9a-f]{64}$/;

/** One entry read alone: ``read``'s result, or the reason it could not be read. */
function entry<T extends { readonly kind: "read" }>(
  raw: unknown,
  read: (raw: unknown) => T,
): T | { readonly kind: "refused"; readonly reason: string } {
  try {
    return read(raw);
  } catch (error) {
    return {
      kind: "refused",
      reason: error instanceof Error ? error.message : "it is not of the kind listed",
    };
  }
}

function model(raw: unknown): CatalogueModel {
  return entry(raw, (m) => {
    const listed = record(m);
    return { kind: "read", id: text(listed.id, "its id"), label: text(listed.label, "its label") };
  });
}

function localModel(raw: unknown): LocalModel {
  return entry(raw, (m) => {
    const listed = record(m);
    return {
      kind: "read",
      name: text(listed.name, "its name"),
      // The catalogue names the unit in the key; the sizes are bare numbers there.
      memory: at(listed, "memory_gb", quantity(number, "GB")),
      disk: at(listed, "disk_gb", quantity(number, "GB")),
      licence: at(listed, "licence", text),
      source: at(listed, "source", text),
    };
  });
}

function engine(raw: unknown): EngineEntry {
  return entry(raw, (e) => {
    const listed = record(e);
    return {
      kind: "read",
      engine: {
        id: text(listed.id, "its id"),
        name: text(listed.name, "its name"),
        detail: at(listed, "detail", text),
        auth: at(listed, "auth", text),
        status: at(listed, "status", text),
        models: at(listed, "models", (m) => list(m).map(model)),
        defaults: at(listed, "defaults", (d) => {
          const defaults = record(d);
          return {
            implementer: at(defaults, "implementer", text),
            reviewer: at(defaults, "reviewer", text),
          };
        }),
        localModels: at(listed, "local_models", (m) => list(m).map(localModel)),
      },
    };
  });
}

export function engineCatalogue(value: unknown): EngineCatalogue {
  try {
    const answer = record(value);
    const sha256 = text(answer.sha256);
    if (!SHA256.test(sha256)) throw new FieldError("the digest is not a sha256");
    const length = answer.length;
    if (typeof length !== "number" || !Number.isSafeInteger(length) || length < 0)
      throw new FieldError("the length is not a whole number of bytes");
    return {
      file: text(answer.file),
      sha256,
      length: requireQuantity({ value: length, unit: "B" }),
      engines: list(record(answer.catalogue).engines).map(engine),
    };
  } catch (error) {
    if (error instanceof FieldError) throw new ShapeError("an engine catalogue");
    throw error;
  }
}

/** Only an engine the catalogue lists as available can be chosen; any other status is inert. */
export function isAvailable(engine: Engine): boolean {
  return engine.status.kind === "read" && engine.status.value === "available";
}
