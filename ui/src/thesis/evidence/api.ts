/**
 * A stub of the Evidence screen's routes and guards: the types and names only, so the red rows
 * fail on their assertions until the guards are built.
 */
import type { CostRecord } from "../../api/records";
import type { Refusal } from "../../design/components/status/States";

export const KINDS = ["reportable", "development", "ablation"] as const;
export type Kind = (typeof KINDS)[number];

export const HELD_OUT: readonly string[] = ["held_out", "held_out_canaries", "held_out_sha256"];

export const RUNS_ROUTE = "/api/evidence/runs";
export const CATCHES_ROUTE = "/api/evidence/catches";
export const PRICES_ROUTE = "/api/prices";

export interface Place {
  readonly root: number;
  readonly name: string;
}

export function spendRoute(place: Place, date: string): string {
  void place;
  void date;
  return "";
}

export function compareRoute(a: Place, b: Place): string {
  void a;
  void b;
  return "";
}

export interface EvidenceSource extends Place {
  readonly runId: string;
  readonly manifestId: string;
  readonly kind: Kind;
  readonly commit: string | null;
  readonly clean: boolean;
}

export interface ReadRun extends Place {
  readonly read: true;
  readonly runId: string;
  readonly seed: number;
  readonly manifestId: string;
  readonly kind: Kind;
  readonly flags: Readonly<Record<string, unknown>>;
  readonly pins: Readonly<Record<string, unknown>>;
}

export interface UnreadRun extends Place {
  readonly read: false;
  readonly error: string;
  readonly record: string;
  readonly offset: string | null;
  readonly reason: string | null;
}

export type RunRow = ReadRun | UnreadRun;

export function evidenceRuns(value: unknown): readonly RunRow[] {
  void value;
  return [];
}

export function byKind(rows: readonly RunRow[]): readonly ReadRun[] {
  void rows;
  return [];
}

export interface Tokens {
  readonly input: number;
  readonly output: number;
  readonly cacheRead: number;
  readonly cacheCreation: number;
}

export interface Sum {
  readonly tokens: Tokens;
  readonly usd: string;
  readonly lowerBound: boolean;
}

export interface PricedCall {
  readonly attribution: string;
  readonly model: string;
  readonly tokens: Tokens;
  readonly usd: string;
  readonly sealBroken: boolean;
  readonly lowerBound: boolean;
}

export interface PricedSession extends PricedCall {
  readonly sessionId: string;
  readonly subtaskId: string;
  readonly attempt: number;
  readonly outcome: string;
}

export interface RoleSpend {
  readonly role: string;
  readonly sum: Sum;
  readonly sessions: readonly PricedSession[];
}

export const APART = ["decomposition", "review", "routing", "left_over"] as const;
export type ApartGroup = (typeof APART)[number];

export interface Apart {
  readonly sum: Sum | null;
  readonly calls: readonly PricedCall[];
}

export interface Reconciliation {
  readonly binaryUsd: string;
  readonly pricedUsd: string;
  readonly differs: readonly string[];
  readonly unread: readonly string[];
  readonly ttlUnread: readonly string[];
  readonly sealBroken: readonly string[];
}

export interface Spend {
  readonly source: EvidenceSource;
  readonly line: CostRecord;
  readonly reconciliation: Reconciliation | null;
  readonly view: string;
  readonly roles: readonly RoleSpend[];
  readonly apart: Readonly<Record<ApartGroup, Apart>>;
}

export function evidenceSpend(value: unknown): Spend {
  return value as Spend;
}

export function newestDate(dates: readonly string[]): string | null {
  void dates;
  return null;
}

export type Cell = string | number | boolean | null | Readonly<Record<string, number>>;
export type RunNumbers = Readonly<Record<string, Cell>>;

export interface Comparison {
  readonly a: EvidenceSource;
  readonly b: EvidenceSource;
  readonly baseline: RunNumbers;
  readonly candidate: RunNumbers;
  readonly differsIn: readonly string[];
}

export function evidenceComparison(value: unknown): Comparison {
  return value as Comparison;
}

export function driftedOf(refusal: Refusal): readonly string[] | null {
  void refusal;
  return null;
}

export interface CatchRow {
  readonly gateMode: string;
  readonly check: number | null;
  readonly name: string;
  readonly checksRun: number;
  readonly blockingFailures: number;
  readonly reviewerHadPassed: number;
  readonly reviewerHadFailed: number;
  readonly noReview: number;
  readonly artefactsCaught: number;
  readonly caughtAfterReviewerPassed: number;
}

export interface KindCatches {
  readonly kind: Kind;
  readonly runs: readonly EvidenceSource[];
  readonly rows: readonly CatchRow[];
}

export interface Catches {
  readonly kinds: readonly KindCatches[];
  readonly unread: readonly UnreadRun[];
}

export function evidenceCatches(value: unknown): Catches {
  void value;
  return { kinds: [], unread: [] };
}
