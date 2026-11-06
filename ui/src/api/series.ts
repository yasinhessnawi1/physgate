/** A run's simulation records, as the server sends them: not written yet. */
import type { Quantity } from "../design/quantity";

export const LOOP_MAGNITUDE = "";
export const LOOP_PHASE = "";
export const EXTRACTORS = [] as readonly string[];
export type Extractor = string;

export const seriesRoute = (_base: string): string => "";
export const attemptRoute = (_base: string, _subtask: string, _attempt: number): string => "";
export const recordRoute = (
  _base: string,
  _subtask: string,
  _attempt: number,
  _record: string,
): string => "";

export interface Unread {
  readonly kind: "unread";
  readonly error: string;
}
export interface ColumnSummary {
  readonly name: string;
  readonly unit: string;
  readonly samples: number;
  readonly first: number | string;
  readonly last: number | string;
  readonly smallest: number | string;
  readonly largest: number | string;
}
export interface GateEntry {
  readonly seq: number;
  readonly check: number;
  readonly name: string;
  readonly outcome: string;
  readonly gateMode: string;
  readonly blocking: boolean;
  readonly expected: string | null;
  readonly low: Quantity | null;
  readonly high: Quantity | null;
}
export interface SeriesCheck {
  readonly kind: "check";
  readonly nodeId: string;
  readonly quantity: string;
  readonly recordId: string;
  readonly extract: string;
  readonly trace: string | null;
  readonly sessionId: string | null;
  readonly declared: Quantity;
  readonly read: Quantity | null;
  readonly outcome: string;
  readonly reason: string | null;
  readonly gate: readonly GateEntry[] | string;
}
export interface ListedAttempt {
  readonly kind: "attempt";
  readonly subtaskId: string;
  readonly attempt: number;
  readonly ownerRole: string | null;
  readonly merged: boolean;
  readonly rejected: boolean;
  readonly refusedBy: string | null;
  readonly sessions: readonly unknown[];
  readonly records: readonly unknown[];
  readonly superseded: readonly unknown[];
  readonly setAside: readonly unknown[];
  readonly checks: readonly (SeriesCheck | Unread)[];
}
export interface SeriesListing {
  readonly tolerance: string;
  readonly attempts: readonly (ListedAttempt | Unread)[];
}
export interface ShownRecord {
  readonly kind: "shown";
  readonly [field: string]: unknown;
}
export type AttemptRecord =
  | ShownRecord
  | { readonly kind: "unread"; readonly recordId: string | null; readonly error: string };
export interface Column {
  readonly name: string;
  readonly unit: string;
  readonly values: readonly number[];
}
export interface RecordSamples {
  readonly axis: "time" | "frequency";
  readonly x: Column;
  readonly traces: readonly Column[];
}

export const seriesListing = (_value: unknown): SeriesListing => ({ tolerance: "", attempts: [] });
export const attemptRecords = (_value: unknown) => ({
  subtaskId: "",
  attempt: 0,
  records: [] as readonly AttemptRecord[],
});
export const recordSamples = (_value: unknown): RecordSamples => ({
  axis: "time",
  x: { name: "", unit: "", values: [] },
  traces: [],
});
