/**
 * Where the library screen is, read from its address: the section shown and the record open in
 * the inspector. Anything the screen cannot read as one of its own is the default, never a guess.
 * And the changed lines of a proposed change, sorted into what a person reads.
 */
import type { FileState } from "../../api/library";
import type { StatusKind } from "../../design/components/status/StatusTag";

export const TABS = ["standards", "skills", "rubrics", "proposed", "ratings"] as const;
export type Tab = (typeof TABS)[number];

/** The section in the address, or the standards. */
export function parseTab(value: string | null): Tab {
  return (TABS as readonly (string | null)[]).includes(value) ? (value as Tab) : "standards";
}

/** What the inspector shows: one file, one candidate, one range, one envelope, one store class. */
export type Open =
  | { readonly kind: "file"; readonly file: string; readonly role: string }
  | { readonly kind: "candidate"; readonly id: string }
  | { readonly kind: "range" | "envelope"; readonly table: number; readonly index: number }
  | { readonly kind: "store"; readonly index: number };

const FILE = /^file:(standards|skill|bounds)\/([a-z][a-z0-9_]{0,63})$/;
const CANDIDATE = /^candidate:([A-Za-z0-9_-]{1,128})$/;
const RATING = /^(range|envelope):(\d{1,6})\/(\d{1,6})$/;
const STORE = /^store:(\d{1,6})$/;

/** The record the address opens, or ``null``. */
export function parseOpen(value: string | null): Open | null {
  if (value === null) return null;
  const file = FILE.exec(value);
  if (file !== null) return { kind: "file", file: file[1] ?? "", role: file[2] ?? "" };
  const candidate = CANDIDATE.exec(value);
  if (candidate !== null) return { kind: "candidate", id: candidate[1] ?? "" };
  const rating = RATING.exec(value);
  if (rating !== null)
    return {
      kind: rating[1] === "range" ? "range" : "envelope",
      table: Number(rating[2]),
      index: Number(rating[3]),
    };
  const store = STORE.exec(value);
  if (store !== null) return { kind: "store", index: Number(store[1]) };
  return null;
}

/** The address value that opens ``open``. */
export function openValue(open: Open): string {
  switch (open.kind) {
    case "file":
      return `file:${open.file}/${open.role}`;
    case "candidate":
      return `candidate:${open.id}`;
    case "range":
    case "envelope":
      return `${open.kind}:${String(open.table)}/${String(open.index)}`;
    case "store":
      return `store:${String(open.index)}`;
  }
}

/** The neutral tag for each state a file is in. */
export const STATE_TAGS: Readonly<Record<FileState, StatusKind>> = {
  matches: "promotion-matches",
  differs: "promotion-differs",
  "never-promoted": "never-promoted",
  "no-digest": "no-digest",
};

export interface DiffRow {
  readonly kind: "hunk" | "same" | "removed" | "added";
  readonly text: string;
}

/**
 * The changed lines as a person reads them. The two header lines name the file, which the
 * inspector names already, so they are left out; every other line keeps its marker.
 */
export function diffRows(lines: readonly string[]): DiffRow[] {
  const headed = lines.length >= 2 && lines[0]?.startsWith("--- ") && lines[1]?.startsWith("+++ ");
  return (headed === true ? lines.slice(2) : lines).map((text) => ({
    kind: text.startsWith("@@")
      ? "hunk"
      : text.startsWith("-")
        ? "removed"
        : text.startsWith("+")
          ? "added"
          : "same",
    text,
  }));
}
