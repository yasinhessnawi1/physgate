/**
 * The library's records, as the server sends them, with a guard for each. A kind or a role the
 * screen does not know passes through as a string, to be shown as written; a state or an effect
 * the screen could not name, a size that is not a count, a digest that is not one and a value
 * without its unit are refused at this boundary.
 *
 * A promotion line is shown as recorded: the log is appended by hand-run commands across
 * versions, so a field it lacks is ``null`` here rather than a refusal of the whole listing.
 */
import { type Quantity, requireQuantity } from "../design/quantity";
import { ShapeError } from "./client";

export const LIBRARY_ROUTE = "/api/library";
export const STAGED_ROUTE = "/api/library/staged";
export const RATINGS_ROUTE = "/api/library/ratings";
/** Where the promotion log is, as the log names every file: relative to the checkout. */
export const PROMOTIONS_PATH = "knowledge/promotions.jsonl";
/** The kinds of file a role's folder holds, as the routes name them. */
export const LIBRARY_KINDS = ["standards", "skill", "bounds"] as const;
export type LibraryKind = (typeof LIBRARY_KINDS)[number];

/** One library file, by its kind and role. */
export function fileRoute(kind: string, role: string): string {
  return `/api/library/files/${encodeURIComponent(kind)}/${encodeURIComponent(role)}`;
}

/** One staged candidate, by its id. */
export function candidateRoute(id: string): string {
  return `/api/library/staged/${encodeURIComponent(id)}`;
}

export const FILE_STATES = ["matches", "differs", "never-promoted", "no-digest"] as const;
export type FileState = (typeof FILE_STATES)[number];

export const EFFECTS = ["creates", "adds to", "replaces whole"] as const;
export type Effect = (typeof EFFECTS)[number];

function object(value: unknown, what: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value))
    throw new ShapeError(what);
  return value as Record<string, unknown>;
}

function list(value: unknown, what: string): readonly unknown[] {
  if (!Array.isArray(value)) throw new ShapeError(what);
  return value;
}

function text(value: unknown, what: string): string {
  if (typeof value !== "string") throw new ShapeError(what);
  return value;
}

function count(value: unknown, what: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0)
    throw new ShapeError(what);
  return value;
}

function flag(value: unknown, what: string): boolean {
  if (typeof value !== "boolean") throw new ShapeError(what);
  return value;
}

const HEX64 = /^[0-9a-f]{64}$/;

function digest(value: unknown): string {
  if (typeof value !== "string" || !HEX64.test(value)) throw new ShapeError("a sha256 digest");
  return value;
}

function oneOf<T extends string>(value: unknown, allowed: readonly T[], what: string): T {
  if (typeof value === "string" && (allowed as readonly string[]).includes(value))
    return value as T;
  throw new ShapeError(what);
}

/** A recorded field as written: ``null`` when the line has none, any other value as JSON. */
function asWritten(value: unknown): string | null {
  if (value === undefined || value === null) return null;
  return typeof value === "string" ? value : JSON.stringify(value);
}

/** One promotion line, as recorded. The server never sends its canary. */
export interface PromotionLine {
  readonly candidateId: string | null;
  readonly kind: string | null;
  readonly domain: string | null;
  readonly episodeId: string | null;
  readonly destination: string | null;
  /** The person, as the line names them: never merged with another spelling. */
  readonly promotedBy: string | null;
  /** When, as recorded (``YYYY-MM-DDTHH:MM:SSZ``). The log's times are not in order. */
  readonly promoted: string | null;
  /** ``null`` on a line written before digests were recorded. */
  readonly sha256: string | null;
  readonly replaces: boolean;
}

function promotionLine(value: unknown): PromotionLine {
  const line = object(value, "a promotion line");
  return {
    candidateId: asWritten(line.candidate_id),
    kind: asWritten(line.kind),
    domain: asWritten(line.domain),
    episodeId: asWritten(line.episode_id),
    destination: asWritten(line.destination),
    promotedBy: asWritten(line.promoted_by),
    promoted: asWritten(line.promoted),
    sha256: typeof line.sha256 === "string" ? line.sha256 : null,
    replaces: line.replaces === true,
  };
}

interface Located {
  readonly kind: string;
  readonly role: string;
  /** As the promotion log names it: ``knowledge/<role>/<file>``. */
  readonly path: string;
}

/** A library file the server read, with its state chosen by its bytes. */
export interface ReadDocument extends Located {
  readonly error: null;
  readonly size: number;
  readonly sha256: string;
  /** The line that wrote these bytes; ``null`` unless the state is ``matches``. */
  readonly promotion: PromotionLine | null;
  readonly state: FileState;
}

/** A library file the server refused or could not read: its own row, never the whole table. */
export interface RefusedDocument extends Located {
  readonly error: string;
}

export type LibraryDocument = ReadDocument | RefusedDocument;

export interface Rubric {
  /** The role the log names, or ``null`` when its lines name none. */
  readonly role: string | null;
  readonly path: string;
  /** Every line that names it, in log order. */
  readonly promotions: readonly PromotionLine[];
}

export interface LibraryListing {
  /** The library's real path, as the server's start announcement prints it. */
  readonly library: string;
  readonly documents: readonly LibraryDocument[];
  readonly rubrics: readonly Rubric[];
  /** Lines in the promotion log. */
  readonly promotions: number;
  /** Valid staged candidates. */
  readonly staged: number;
}

function libraryDocument(value: unknown): LibraryDocument {
  const raw = object(value, "a library file");
  const located = {
    kind: text(raw.kind, "a library file's kind"),
    role: text(raw.role, "a role"),
    path: text(raw.path, "a library path"),
  };
  if (raw.error !== undefined) return { ...located, error: text(raw.error, "a refusal") };
  return {
    ...located,
    error: null,
    size: count(raw.size, "a size in bytes"),
    sha256: digest(raw.sha256),
    promotion: raw.promotion === null ? null : promotionLine(raw.promotion),
    state: oneOf(raw.state, FILE_STATES, "a library file's state"),
  };
}

export function libraryListing(value: unknown): LibraryListing {
  const answer = object(value, "the library's listing");
  return {
    library: text(answer.library, "the library's path"),
    documents: list(answer.documents, "the library's files").map(libraryDocument),
    rubrics: list(answer.rubrics, "the rubrics").map((raw) => {
      const rubric = object(raw, "a rubric's record");
      return {
        role: asWritten(rubric.role),
        path: text(rubric.path, "a rubric's path"),
        promotions: list(rubric.promotions, "a rubric's promotions").map(promotionLine),
      };
    }),
    promotions: count(answer.promotions, "a count of promotions"),
    staged: count(answer.staged, "a count of staged candidates"),
  };
}

export interface LibraryFile extends Located {
  readonly size: number;
  readonly sha256: string;
  /** The file's text, shown as text. */
  readonly text: string;
  /** Every line naming this file, in log order. */
  readonly promotions: readonly PromotionLine[];
  /** The index in ``promotions`` of the line that wrote these bytes, or ``null``. */
  readonly wrote: number | null;
  readonly state: FileState;
}

export function libraryFile(value: unknown): LibraryFile {
  const answer = object(value, "a library file");
  const promotions = list(answer.promotions, "a file's promotions").map(promotionLine);
  const wrote = answer.wrote === null ? null : count(answer.wrote, "a line's position");
  if (wrote !== null && wrote >= promotions.length)
    throw new ShapeError("a position in the file's promotions");
  return {
    kind: text(answer.kind, "a library file's kind"),
    role: text(answer.role, "a role"),
    path: text(answer.path, "a library path"),
    size: count(answer.size, "a size in bytes"),
    sha256: digest(answer.sha256),
    text: text(answer.text, "a file's text"),
    promotions,
    wrote,
    state: oneOf(answer.state, FILE_STATES, "a library file's state"),
  };
}

/** A staged candidate, listed without its content. */
export interface StagedRow {
  readonly name: string;
  readonly kind: string;
  readonly error: null;
  readonly candidateId: string;
  readonly role: string;
  readonly episodeId: string;
  /** As the candidate states it: informational. */
  readonly written: string;
  readonly replaces: boolean;
  readonly destination: string;
  readonly size: number;
  readonly sha256: string;
}

/** A staged file that promotion would refuse: its own row. */
export interface StagedError {
  readonly name: string;
  readonly kind: string;
  readonly error: string;
}

export type StagedCandidate = StagedRow | StagedError;

export function stagedList(value: unknown): readonly StagedCandidate[] {
  const answer = object(value, "the staged candidates");
  return list(answer.candidates, "the staged candidates").map((raw): StagedCandidate => {
    const row = object(raw, "a staged candidate");
    const named = {
      name: text(row.name, "a staged file's name"),
      kind: text(row.kind, "a staged kind"),
    };
    if (row.error !== undefined) return { ...named, error: text(row.error, "a refusal") };
    return {
      ...named,
      error: null,
      candidateId: text(row.candidate_id, "a candidate id"),
      role: text(row.role, "a role"),
      episodeId: text(row.episode_id, "an episode id"),
      written: text(row.written, "when it was written"),
      replaces: flag(row.replaces, "whether it replaces the file"),
      destination: text(row.destination, "a destination"),
      size: count(row.size, "a size in bytes"),
      sha256: digest(row.sha256),
    };
  });
}

export interface Fingerprint {
  readonly size: number;
  readonly sha256: string;
}

function fingerprint(value: unknown): Fingerprint {
  const raw = object(value, "a file's fingerprint");
  return { size: count(raw.size, "a size in bytes"), sha256: digest(raw.sha256) };
}

export interface CandidateDetail {
  readonly candidate: {
    readonly kind: string;
    readonly domain: string;
    readonly content: string;
    readonly episodeId: string;
    readonly candidateId: string;
    readonly written: string;
    readonly replaces: boolean;
  };
  readonly kind: string;
  readonly destination: string;
  readonly effect: Effect;
  /** The destination now; ``null`` when promotion would create it. */
  readonly now: Fingerprint | null;
  /** What promotion's own code would write. */
  readonly after: Fingerprint;
  /** The unified diff, header lines first. */
  readonly lines: readonly string[];
}

export function candidateDetail(value: unknown): CandidateDetail {
  const answer = object(value, "a staged candidate");
  const candidate = object(answer.candidate, "a staged candidate");
  return {
    candidate: {
      kind: text(candidate.kind, "a staged kind"),
      domain: text(candidate.domain, "a role"),
      content: text(candidate.content, "a candidate's content"),
      episodeId: text(candidate.episode_id, "an episode id"),
      candidateId: text(candidate.candidate_id, "a candidate id"),
      written: text(candidate.written, "when it was written"),
      replaces: flag(candidate.replaces, "whether it replaces the file"),
    },
    kind: text(answer.kind, "a staged kind"),
    destination: text(answer.destination, "a destination"),
    effect: oneOf(answer.effect, EFFECTS, "what a promotion would do"),
    now: answer.now === null ? null : fingerprint(answer.now),
    after: fingerprint(answer.after),
    lines: list(answer.lines, "the changed lines").map((l) => text(l, "a changed line")),
  };
}

/** A range or an envelope from a bounds table: a sourced rating, every value with its unit. */
export interface Rating {
  /** The quantity a range rates, or the kind an envelope bounds. */
  readonly key: string;
  /** The catalogue's kind for the quantity, or ``null`` when it has none. */
  readonly kind: string | null;
  readonly low: Quantity;
  readonly high: Quantity;
  readonly componentClass: string;
  readonly source: string;
  readonly retrieved: string;
  readonly confirmed: string;
  readonly note: string;
}

export interface BoundsTable {
  readonly domain: string;
  readonly path: string;
  readonly sha256: string;
  readonly ranges: readonly Rating[];
  readonly envelopes: readonly Rating[];
}

export interface StoreClassRating {
  readonly name: string;
  readonly fastestDischarge: Quantity;
  readonly source: string;
  readonly confirmed: string;
}

export interface Ratings {
  readonly tables: readonly BoundsTable[];
  readonly storeClasses: readonly StoreClassRating[];
  readonly catalogueDigest: string;
}

function rating(value: unknown, key: "quantity" | "kind"): Rating {
  const raw = object(value, "a rating");
  return {
    key: text(raw[key], "a rated quantity"),
    kind: raw.kind === null ? null : text(raw.kind, "a quantity's kind"),
    low: requireQuantity(raw.low),
    high: requireQuantity(raw.high),
    componentClass: text(raw.class, "a component class"),
    source: text(raw.source, "a source"),
    retrieved: text(raw.retrieved, "when it was retrieved"),
    confirmed: text(raw.confirmed, "when it was confirmed"),
    note: text(raw.note, "a note"),
  };
}

export function ratings(value: unknown): Ratings {
  const answer = object(value, "the ratings");
  return {
    tables: list(answer.tables, "the bounds tables").map((raw) => {
      const table = object(raw, "a bounds table");
      return {
        domain: text(table.domain, "a table's domain"),
        path: text(table.path, "a table's path"),
        sha256: digest(table.sha256),
        ranges: list(table.ranges, "a table's ranges").map((r) => rating(r, "quantity")),
        envelopes: list(table.envelopes, "a table's envelopes").map((e) => rating(e, "kind")),
      };
    }),
    storeClasses: list(answer.store_classes, "the energy store classes").map((raw) => {
      const store = object(raw, "an energy store class");
      return {
        name: text(store.name, "a store class's name"),
        fastestDischarge: requireQuantity(store.fastest_discharge),
        source: text(store.source, "a source"),
        confirmed: text(store.confirmed, "when it was confirmed"),
      };
    }),
    catalogueDigest: digest(answer.catalogue_digest),
  };
}
