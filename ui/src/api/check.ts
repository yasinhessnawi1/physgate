/**
 * The small checks every record guard is built from. Each refuses a value of the wrong shape
 * with a ``ShapeError`` naming what was expected, so a view gets the record or a refusal.
 */
import { ShapeError } from "./client";

export function object(value: unknown, what: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value))
    throw new ShapeError(what);
  return value as Record<string, unknown>;
}

export function list(value: unknown, what: string): readonly unknown[] {
  if (!Array.isArray(value)) throw new ShapeError(what);
  return value;
}

export function text(value: unknown, what: string): string {
  if (typeof value !== "string") throw new ShapeError(what);
  return value;
}

export function optionalText(value: unknown, what: string): string | null {
  return value === null || value === undefined ? null : text(value, what);
}

export function count(value: unknown, what: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0)
    throw new ShapeError(what);
  return value;
}

export function optionalCount(value: unknown, what: string): number | null {
  return value === null || value === undefined ? null : count(value, what);
}

export function seconds(value: unknown, what: string): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) throw new ShapeError(what);
  return value;
}

export function flag(value: unknown, what: string): boolean {
  if (typeof value !== "boolean") throw new ShapeError(what);
  return value;
}

export function oneOf<T extends string>(value: unknown, allowed: readonly T[], what: string): T {
  if (typeof value === "string" && (allowed as readonly string[]).includes(value))
    return value as T;
  throw new ShapeError(what);
}
