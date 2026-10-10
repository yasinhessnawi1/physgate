/**
 * A quantity is a value and its unit, always together. There is no way to hand a component a
 * bare number: the type has no such form, and the runtime check refuses one that arrives cast
 * through `unknown` from a record.
 *
 * A value is a number, or a decimal numeral exactly as the record wrote it (costs are recorded
 * as exact decimals, and turning one into a float would change the figure shown).
 */
export interface Quantity {
  readonly value: number | string;
  readonly unit: string;
}

/** Raised for anything that is not a value-and-unit pair: the UI never strips a unit. */
export class BareNumberError extends Error {
  constructor(received: unknown) {
    super(
      `a quantity is a value and its unit, never a bare number: received ${JSON.stringify(received)}`,
    );
    this.name = "BareNumberError";
  }
}

const DECIMAL = /^-?(0|[1-9][0-9]*)(\.[0-9]+)?$/;

/** ``candidate`` if it is a value-and-unit pair; otherwise refuse it. */
export function requireQuantity(candidate: unknown): Quantity {
  if (typeof candidate !== "object" || candidate === null) throw new BareNumberError(candidate);
  const { value, unit } = candidate as { value?: unknown; unit?: unknown };
  const isNumber = typeof value === "number" && Number.isFinite(value);
  const isDecimal = typeof value === "string" && DECIMAL.test(value);
  if (!(isNumber || isDecimal) || typeof unit !== "string" || unit.trim() === "") {
    throw new BareNumberError(candidate);
  }
  return { value, unit };
}

/** The unit as shown: a dimensionless quantity says so rather than showing nothing. */
export function unitLabel(unit: string): string {
  return unit === "1" || unit === "dimensionless" ? "dimensionless" : unit;
}

/** The value as recorded, never rounded here: precision belongs to the record, not the view. */
export function valueLabel(value: number | string): string {
  return typeof value === "number" ? String(value) : value;
}
