import type { RunEvent } from "./events";

export interface LogTail {
  readonly count: number;
  readonly from: number;
  readonly text: string;
}

export interface Followed {
  readonly raw: readonly string[];
  readonly events: readonly RunEvent[];
}

export type Step =
  { readonly kind: "grown"; readonly followed: Followed } | { readonly kind: "again" };

export function logTail(value: unknown): LogTail {
  void value;
  return { count: 0, from: 0, text: "" };
}

export function wholeLines(text: string): readonly string[] {
  return text === "" ? [] : [text];
}

export function follow(held: Followed | null, tail: LogTail): Step {
  void held;
  void tail;
  return { kind: "again" };
}
