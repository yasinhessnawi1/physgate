/**
 * Every sentence the Queue screen says about a part of the plan a person decides (ARCH-122): the
 * three choices, what each states, the hints under the values, why a choice cannot be recorded
 * yet, a part the release gate raised again, and the run released once every part is decided.
 * Plain words: no command, no record's raw field, and never more than the run does.
 */
import type { PartsPosition, StatedPart } from "../api/queue";
import { countOf } from "./count";
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
  findAllLead:
    "Or find every part still open in one step: each is sourced and sized as before, and you " +
    "state nothing of any. A part raised again is left as it is.",
  findAllLabel: "Find every remaining part…",
  findAllTitle: "Record that every remaining part is to be found?",
  findAllCheck:
    "that each item is still the one shown (its digest is in its line), one part at a time in " +
    "the queue's order; the first part the server refuses stops the rest, and those before it " +
    "stay recorded",
  findAllOutcome: "Each part is sourced and sized as before.",
  findAllWritten:
    "None can be edited or undone; each item closes. Each time is stamped when it is written.",
  findAllSending: "Recording each part in turn…",
  findAllTime: "‹the time it is written›",
  noOperator: "no operator: this page names none",
  raisedTitle: "The physics gate stopped this part at the release",
  raisedTitleInterface:
    "At the release, an interface the design produced holds another value than one stated for " +
    "this part",
  raisedTitleUnread: "This part was raised again at the release",
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
  refused: "The server refused this choice, and nothing was written:",
  refusedReread:
    "The queue is read again: if the part changed or was decided meanwhile, the page now shows " +
    "it as it is.",
  unchecked:
    "The physics gate's catalogue does not name this quantity, so its value is recorded as " +
    "unchecked: written onto the part, but held to no unit or range.",
  next:
    "Every part is decided. The run takes up your decisions when it goes on, or when it is " +
    "resumed if it is not going now: it writes what you stated onto each part's node, and the " +
    "physics gate checks each value's unit and range. The run then continues, or brings the " +
    "part back here with the gate's finding.",
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

/** What the find-all confirmation records, naming each part: `"A", "B"`. */
export function findAllSummary(who: string, labels: readonly string[]): string {
  return `This records: ${who} chose "${CHOICE_WORDS.find.label}" for ${countOf(labels.length, "part")}: ${labels.map((l) => `"${l}"`).join(", ")}.`;
}

/** Where the find-all's lines go. */
export function findAllLines(n: number, runId: string): string {
  return `${n === 1 ? "One line" : `${String(n)} lines, one per part,`} appended to queue_decisions.jsonl in run ${runId}.`;
}

/** Every remaining part recorded as to be found. */
export function foundAllWords(n: number, by: string): string {
  return `Recorded "choose find" for ${countOf(n, "part")} by ${by}.`;
}

/** The find-all stopped by a refusal: how many were recorded before it. */
export function foundAllStoppedWords(recorded: number, of: number): string {
  return `${String(recorded)} of ${countOf(of, "part")} were recorded as to be found before the server refused the next, and nothing was written for it or any after it:`;
}
