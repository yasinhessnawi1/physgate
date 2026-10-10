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

/** The name of the ``<meta>`` element the server puts its action token in. */
export const ACT_TOKEN_META = "physgate-act-token";

/** The name of the ``<meta>`` element naming the operator decisions are recorded under. */
export const OPERATOR_META = "physgate-operator";

/**
 * Who decisions taken here are recorded under, as the server put it in this page, or ``null`` when
 * the server was started without naming anyone, in which case nothing can be decided here.
 */
export function pageOperator(doc: Document = document): string | null {
  const meta = doc.querySelector<HTMLMetaElement>(`meta[name="${OPERATOR_META}"]`);
  return meta === null || meta.content === "" ? null : meta.content;
}

/** The header an action carries the token back in. */
export const ACT_TOKEN_HEADER = "X-Physgate-Act-Token";

/**
 * The action token this page was served with, or ``null`` when the page carries none. The server
 * made it at start and put it only in this page; another site's page cannot read it.
 */
export function actToken(doc: Document = document): string | null {
  const meta = doc.querySelector<HTMLMetaElement>(`meta[name="${ACT_TOKEN_META}"]`);
  return meta === null || meta.content === "" ? null : meta.content;
}

/**
 * The one request that acts: a JSON body posted to ``path`` with this page's action token. The
 * browser sends the page's own origin with it. The answer is held to ``guard``, or is the
 * server's refusal with its reason; a page with no token sends nothing.
 */
export async function postAction<T>(
  path: string,
  body: string,
  guard: (value: unknown) => T,
  token: string | null = actToken(),
): Promise<Result<T>> {
  if (token === null)
    return {
      ok: false,
      refusal: {
        status: 0,
        error: "this page carries no action token, so it cannot act",
        context: {},
      },
    };
  const response = await fetch(path, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      [ACT_TOKEN_HEADER]: token,
    },
    body,
    credentials: "omit",
  });
  const text = await response.text();
  if (response.ok) return guarded(text, guard);
  let parsed: unknown = {};
  try {
    parsed = JSON.parse(text);
  } catch {
    parsed = {};
  }
  return { ok: false, refusal: refusalOf(response.status, parsed) };
}
