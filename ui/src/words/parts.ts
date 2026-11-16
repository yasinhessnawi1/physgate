/**
 * Every sentence the Queue screen says about a part of the plan a person decides (ARCH-122): the
 * three choices, what each states, the hints under the values, why a choice cannot be recorded
 * yet, a part the release gate raised again, and the run released once every part is decided.
 * Plain words: no command, no record's raw field, and never more than the run does.
 */
import type { PartsPosition, StatedPart } from "../api/queue";
import { quantityLabel } from "./humanise";

/** Each choice as its radio button names it, and the line under it. */
export const CHOICE_WORDS: Readonly<
  Record<PartsPosition, { readonly label: string; readonly said: string }>
> = {
  have: {
    label: "I have it",
    said: "You own this part. State its real values, each with its unit.",
  },
  make: {
    label: "I will make it",
    said: "You will make this part. State what it must meet: values, short texts, or both.",
  },
  find: {
    label: "Find it",
    said: "The run sources and sizes this part as it would without asking. You state nothing.",
  },
};

export const PARTS_COPY = {
  legend: "What will you do with this part?",
  values: "Its values",
  valuesHint:
    "Leave a row empty to state nothing of it. Write each unit as the physics gate reads it: " +
    "V, A, ohm, N*m (not N·m), rpm (not rev/min), kg, m, and 1 for a ratio.",
  addQuantity: "Add another quantity",
  texts: "What it must meet, in words",
  textsHint: "Each text is at most 500 characters; at most 8 texts.",
  addText: "Add a text",
  record: "Record this choice…",
  fixProblems: "Correct what is listed above first.",
  findAll:
    "Finding every remaining part in one step is not offered on this page yet: it is done from " +
    "the command line. Here, choose Find it on each part you do not state.",
  raisedTitle: "The physics gate stopped this part at the release",
  raisedRule:
    "Choose I have it or I will make it again, and state every value you stated before, with " +
    "the value it now has. Find it is not offered: the values are already on the part's node.",
  noComponent:
    "The plan's line for this part could not be read, so its domain and the quantities it " +
    "states are not shown; the item's own text is under Details. You may still state values.",
  declare:
    "Once every part is decided, the run writes what you stated onto the part's node as fixed " +
    "values, and the physics gate checks each value's unit and range before any agent starts. " +
    "No agent may change them. A value the gate stops comes back to you as this part again.",
  find: "The part is sourced and sized as before.",
  written:
    "This cannot be edited or undone; the item closes. The time is stamped when it is written.",
} as const;

/** The confirmation's title for each choice. */
export const CONFIRM_TITLE: Readonly<Record<PartsPosition, string>> = {
  have: "Record that you have this part?",
  make: "Record that you will make this part?",
  find: "Record that this part is to be found?",
};

/** The value a person stated of a name in the round before, after "Stated before: ". */
export function beforeWords(value: number, unit: string): string {
  return `Stated before: ${String(value)} ${unit}`;
}

/** The run released once every part is decided, with how many of each choice. */
export function releasedWords(choices: readonly { readonly choice: string }[]): string {
  const count = (c: string) => choices.filter((x) => x.choice === c).length;
  const said = [
    [count("have"), "you have"],
    [count("make"), "you will make"],
    [count("find"), "to find"],
  ]
    .filter(([n]) => n !== 0)
    .map(([n, what]) => `${String(n)} ${String(what)}`);
  return said.length === 0
    ? "The run asked about its parts, found none to ask, and was released."
    : `Every part is decided, and the run was released: ${said.join(", ")}.`;
}

/** What a decision stated of a part, each value with its unit and each text quoted. */
export function statedWords(stated: StatedPart): string {
  const values = Object.entries(stated.declared).map(
    ([name, q]) => `${quantityLabel(name)} ${String(q.value)} ${q.unit}`,
  );
  const texts = stated.texts.map((t) => `"${t}"`);
  return [...values, ...texts].join("; ");
}
