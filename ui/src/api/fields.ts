/**
 * One drawn field of a record, read alone: its value, its absence, or the reason it could not be
 * read. A guard built from these refuses a wrong field in that field's own row and never empties
 * the rest, and it fills nothing: an absent field stays absent.
 */
import { requireQuantity, type Quantity } from "../design/quantity";

export type Field<T> =
  | { readonly kind: "read"; readonly value: T }
  /**
   * ``missing``: the key is not in the answer at all. Otherwise the record holds ``null`` where
   * the harness writes ``null`` for "none recorded".
   */
  | { readonly kind: "absent"; readonly missing: boolean }
  | { readonly kind: "refused"; readonly reason: string };

/** Why one value could not be read, said as the end of "This value could not be read: …". */
export class FieldError extends Error {
  constructor(reason: string) {
    super(reason);
    this.name = "FieldError";
  }
}

export type Reader<T> = (raw: unknown) => T;

/**
 * ``raw`` read by ``read``, inside its own ``try``: nothing it throws can reach another field.
 * ``undefined`` is a missing key; ``null`` is absent only where ``nullable`` says the harness
 * writes it, and is refused anywhere else.
 */
export function cell<T>(raw: unknown, read: Reader<T>, nullable = false): Field<T> {
  if (raw === undefined) return { kind: "absent", missing: true };
  if (raw === null)
    return nullable
      ? { kind: "absent", missing: false }
      : { kind: "refused", reason: "it is empty where a value is recorded" };
  try {
    return { kind: "read", value: read(raw) };
  } catch (error) {
    return {
      kind: "refused",
      reason: error instanceof Error ? error.message : "it is not of the kind recorded",
    };
  }
}

/** The value at ``key`` of ``record``, read alone. A key the record does not own is missing. */
export function at<T>(
  record: Readonly<Record<string, unknown>>,
  key: string,
  read: Reader<T>,
  nullable = false,
): Field<T> {
  return cell(Object.hasOwn(record, key) ? record[key] : undefined, read, nullable);
}

export function record(raw: unknown, what = "it"): Readonly<Record<string, unknown>> {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw))
    throw new FieldError(`${what} is not a record`);
  return raw as Record<string, unknown>;
}

export function list(raw: unknown, what = "it"): readonly unknown[] {
  if (!Array.isArray(raw)) throw new FieldError(`${what} is not a list`);
  return raw;
}

export function text(raw: unknown, what = "it"): string {
  if (typeof raw !== "string") throw new FieldError(`${what} is not text`);
  return raw;
}

export function flag(raw: unknown, what = "it"): boolean {
  if (typeof raw !== "boolean") throw new FieldError(`${what} is neither true nor false`);
  return raw;
}

/**
 * A number as the record holds it. The server sends whole numbers as JSON numbers, so one beyond
 * 2^53 − 1 has already lost its exact value on the way, and is refused rather than shown wrong.
 */
export function number(raw: unknown, what = "it"): number {
  if (typeof raw !== "number" || !Number.isFinite(raw))
    throw new FieldError(`${what} is not a number`);
  if (Math.abs(raw) > Number.MAX_SAFE_INTEGER)
    throw new FieldError(`${what} is beyond the largest number this page holds exactly`);
  return raw;
}

/** A whole number, where the record holds only whole numbers. */
export function whole(raw: unknown, what = "it"): number {
  const n = number(raw, what);
  if (!Number.isInteger(n)) throw new FieldError(`${what} is not a whole number`);
  return n;
}

/** ``read``'s number with ``unit``: never a bare number. */
export function quantity(read: (raw: unknown) => number, unit: string): Reader<Quantity> {
  return (raw) => requireQuantity({ value: read(raw), unit });
}
