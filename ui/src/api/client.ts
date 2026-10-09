/**
 * The API client. Every response is either the record, checked at this boundary, or the
 * server's refusal with its reason: a view receives one or the other, never a partial record.
 */
import type { Refusal } from "../design/components/States";

export type Result<T> =
  { readonly ok: true; readonly value: T } | { readonly ok: false; readonly refusal: Refusal };

/** Raised by a guard when a response is not the shape the server promises. */
export class ShapeError extends Error {
  constructor(what: string) {
    super(`the server's answer is not ${what}`);
    this.name = "ShapeError";
  }
}

function refusalOf(status: number, body: unknown): Refusal {
  const record = typeof body === "object" && body !== null ? (body as Record<string, unknown>) : {};
  const context: Record<string, string> = {};
  for (const [key, value] of Object.entries(record)) {
    if (key !== "error") context[key] = String(value);
  }
  const error =
    typeof record.error === "string" ? record.error : `the server answered ${String(status)}`;
  return { status, error, context };
}

async function request(path: string): Promise<Result<string>> {
  const response = await fetch(path, {
    headers: { Accept: "application/json" },
    credentials: "omit",
  });
  const text = await response.text();
  if (response.ok) return { ok: true, value: text };
  let body: unknown = {};
  try {
    body = JSON.parse(text);
  } catch {
    body = {};
  }
  return { ok: false, refusal: refusalOf(response.status, body) };
}

function guarded<T>(text: string, guard: (value: unknown) => T): Result<T> {
  try {
    return { ok: true, value: guard(JSON.parse(text)) };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return { ok: false, refusal: { status: 0, error: message, context: {} } };
  }
}

/** One JSON document, held to ``guard``. */
export async function getJson<T>(path: string, guard: (value: unknown) => T): Promise<Result<T>> {
  const answer = await request(path);
  return answer.ok ? guarded(answer.value, guard) : answer;
}

/** A JSON-lines document: every line held to ``guard``; one bad line refuses the whole. */
export async function getLines<T>(
  path: string,
  guard: (value: unknown) => T,
): Promise<Result<readonly T[]>> {
  const answer = await request(path);
  if (!answer.ok) return answer;
  const lines = answer.value.split("\n").filter((line) => line !== "");
  return guarded(`[${lines.join(",")}]`, (value) => {
    if (!Array.isArray(value)) throw new ShapeError("a list of records");
    return value.map(guard);
  });
}
