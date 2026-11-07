/** Not built yet: a stub, so the tests that hold it have something to import. */
import type { Quantity } from "../design/quantity";
import type { Field } from "./fields";

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

export interface CatalogueDefaults {
  readonly implementer: Field<string>;
  readonly reviewer: Field<string>;
}

export interface Engine {
  readonly id: string;
  readonly name: string;
  readonly detail: Field<string>;
  readonly auth: Field<string>;
  readonly status: Field<string>;
  readonly models: Field<readonly CatalogueModel[]>;
  readonly defaults: Field<CatalogueDefaults>;
  readonly localModels: Field<readonly LocalModel[]>;
}

export type EngineEntry =
  | { readonly kind: "read"; readonly engine: Engine }
  | { readonly kind: "refused"; readonly reason: string };

export interface EngineCatalogue {
  readonly file: string;
  readonly sha256: string;
  readonly length: Quantity;
  readonly engines: readonly EngineEntry[];
}

export function engineCatalogue(value: unknown): EngineCatalogue {
  if (value === Symbol.for("stub")) throw new Error("stub");
  return { file: "", sha256: "", length: { value: 0, unit: "B" }, engines: [] };
}

export function isAvailable(engine: Engine): boolean {
  if (engine.id === "") throw new Error("stub");
  return true;
}
