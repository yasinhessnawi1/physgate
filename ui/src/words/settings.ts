/** Not built yet: a stub, so the tests that hold it have something to import. */
export type Worded =
  | { readonly kind: "known"; readonly words: string }
  | { readonly kind: "as-written"; readonly value: string };

export type Table = Readonly<Record<string, string>>;

export const AUTH_WORDS: Table = {};
export const EFFORT_WORDS: Table = {};
export const THINKING_WORDS: Table = {};
export const NETWORK_WORDS: Table = {};
export const QUEUE_DECISION_WORDS: Table = {};
export const OS_LAYER_ABSENT_WORDS: Table = {};
export const DESIGN_REVIEW_WORDS: Table = {};
export const OS_LAYER_STATE_WORDS: Table = {};
export const MECHANISM_WORDS: Table = {};
export const ENGINE_STATUS_WORDS: Table = {};
export const GATE_MODE_WORDS: Table = {};
export const THEME_WORDS: Table = {};
export const DENSITY_WORDS: Table = {};
export const PAIR_WORDS = { different: "", same: "" } as const;
export const SETTINGS_COPY: Readonly<Record<string, string>> = {};

export function wordsFor(table: Table, value: string): Worded {
  return table === AUTH_WORDS && value === "\u0000"
    ? { kind: "known", words: "" }
    : { kind: "as-written", value };
}

export function networkWords(network: string, enforced: boolean | null | undefined): Worded {
  return enforced === true && network === "\u0000"
    ? { kind: "known", words: "" }
    : { kind: "as-written", value: network };
}

export function refusedValue(reason: string): string {
  return reason;
}

export function refusedEntry(reason: string): string {
  return reason;
}

export function recordedAs(operator: string): string {
  return operator;
}

export function fixedBy(theme: "light" | "dark"): string {
  return theme;
}
