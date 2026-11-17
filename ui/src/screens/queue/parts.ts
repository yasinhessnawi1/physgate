/**
 * A part's decision as pure functions a test can read (ARCH-122): which component of the plan an
 * item is about, the round before a part raised again and what it stated, and the form's check.
 *
 * The check mirrors what the queue refuses and the page can know: a value is a finite number with
 * its unit, a name is a quantity's name and stated once, at most twelve values and eight texts of
 * at most 500 characters, have states a value and no text, make a value or a text, find nothing,
 * and a part raised again restates every name it stated before and is not found. Whether a unit
 * is of its quantity's kind is the gate's catalogue's to say, which only the server holds; the
 * server checks everything again and its refusal is shown as it gives it.
 */
import catalogueNames from "../../api/catalogue-names.json";
import type { PlanComponent, RunEvent } from "../../api/events";
import {
  type Decided,
  type DeclaredValue,
  isBlank,
  type ItemView,
  type PartsPosition,
  type StatedPart,
} from "../../api/queue";
import { quantityLabel } from "../../words/humanise";

/** A quantity's name as the plan and the queue spell it. */
export const QUANTITY_NAME = /^[a-z][a-z0-9_]{0,63}$/;
/** The most values a decision on a part states, and the most texts and characters a made part's. */
export const MAX_DECLARED = 12;
export const MAX_TEXTS = 8;
export const MAX_TEXT = 500;
/** A number as a person types one: a decimal, with an exponent if they like. */
const NUMBER = /^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$/;

/** A part's item id: the run and the part's number, then its round from the second on. */
const PART_ID = /^(?<base>.+-parts-(?<number>[0-9]+))(?:-r(?<round>[0-9]+))?$/;

export interface PartRound {
  /** The part's place in the plan, from one. */
  readonly number: number;
  readonly round: number;
  /** The item id of the round before; ``null`` for the first. */
  readonly earlier: string | null;
}

/** Where an item id stands among a part's rounds; ``null`` for an id that is not a part's. */
export function partRound(itemId: string): PartRound | null {
  const found = PART_ID.exec(itemId)?.groups;
  if (found?.base === undefined || found.number === undefined) return null;
  const round = Number(found.round ?? "1");
  return {
    number: Number(found.number),
    round,
    earlier: round < 2 ? null : round === 2 ? found.base : `${found.base}-r${String(round - 1)}`,
  };
}

/** The components the decomposition's line lists; ``null`` where none is read. */
export function planComponents(events: readonly RunEvent[]): readonly PlanComponent[] | null {
  const line = events.find((e) => e.kind === "decomposed");
  return line?.kind === "decomposed" ? (line.components ?? null) : null;
}

/**
 * The quantity names the physics gate's catalogue knows, as the page carries them (no route
 * serves the catalogue; a row holds this list equal to it). A value under any other name is
 * written onto the part and recorded by the gate as unchecked.
 */
const CATALOGUE: ReadonlySet<string> = new Set(catalogueNames);

/** Whether ``name``, a quantity's name as typed, is one the gate's catalogue does not know. */
export function uncatalogued(name: string): boolean {
  const said = name.trim();
  return QUANTITY_NAME.test(said) && !CATALOGUE.has(said);
}

/**
 * The open part to show once ``from`` is decided: the next open part after it in the queue's
 * order, else the first still open; ``undefined`` when no part is open.
 */
export function nextOpenPart(views: readonly ItemView[], from: ItemView): ItemView | undefined {
  const open = views
    .filter((v) => v.open && v.item.source === "parts")
    .sort((a, b) => a.position - b.position);
  return open.find((v) => v.position > from.position) ?? open[0];
}

/** Whether every part of a run that asks about its parts is decided, and none is open. */
export function everyPartDecided(views: readonly ItemView[]): boolean {
  const parts = views.filter((v) => v.item.source === "parts");
  return parts.length > 0 && parts.every((v) => !v.open);
}

/** The choices the release recorded, once the run was released; ``null`` before. */
export function releasedChoices(
  events: readonly RunEvent[],
): readonly { readonly choice: string }[] | null {
  const line = events.find((e) => e.kind === "parts_released");
  return line?.kind === "parts_released" ? line.choices : null;
}

/**
 * The component an item is about: the plan's entry at the part's number, held to the node the
 * item's own text names, so a list read out of step is never shown as this part.
 */
export function componentOf(
  itemId: string,
  decisionRequired: string,
  components: readonly PlanComponent[] | null,
): PlanComponent | null {
  const round = partRound(itemId);
  if (round === null || components === null) return null;
  const component = components[round.number - 1];
  return component !== undefined && decisionRequired.includes(`(node ${component.node})`)
    ? component
    : null;
}

/** What the round before stated, for a part raised again; ``null`` for a first round. */
export function earlierDecision(
  itemId: string,
  decided: readonly Decided[],
): { readonly position: PartsPosition; readonly parts: StatedPart } | null {
  const earlier = partRound(itemId)?.earlier;
  if (earlier === null || earlier === undefined) return null;
  const line = decided.find((d) => d.itemId === earlier);
  if (
    line?.parts === undefined ||
    line.parts === null ||
    (line.position !== "have" && line.position !== "make")
  )
    return null;
  return { position: line.position, parts: line.parts };
}

/** One row of values: a name the plan or the round before gives, or one the person adds. */
export interface ValueRow {
  readonly key: string;
  /** Shown before the fields and in what is said about them. */
  readonly label: string;
  readonly name: string;
  readonly value: string;
  readonly unit: string;
  /** A row the person added, whose name they type. */
  readonly added: boolean;
  /** What the round before stated of this name, for a part raised again. */
  readonly before: DeclaredValue | null;
}

/** The rows a part starts with: the plan's names, then any name the round before stated. */
export function startingRows(
  component: PlanComponent | null,
  before: StatedPart | null,
): ValueRow[] {
  const names = [...(component?.own ?? []), ...(component?.shared ?? [])];
  for (const name of Object.keys(before?.declared ?? {}))
    if (!names.includes(name)) names.push(name);
  return names.map((name) => ({
    key: `plan-${name}`,
    label: quantityLabel(name),
    name,
    value: "",
    unit: "",
    added: false,
    before: before?.declared[name] ?? null,
  }));
}

/** The label of the ``n``-th row a person adds. */
export function addedLabel(n: number): string {
  return `Another quantity ${String(n)}`;
}

/** The value a person typed as a number, or ``null`` when it is not a finite one. */
export function numberOf(typed: string): number | null {
  const text = typed.trim();
  if (!NUMBER.test(text)) return null;
  const value = Number(text);
  return Number.isFinite(value) ? value : null;
}

export interface Checked {
  /** What stops the choice from being recorded, each in a sentence; empty when nothing does. */
  readonly problems: readonly string[];
  /** What the choice states of the part, as the request carries it; ``null`` for find. */
  readonly stated: StatedPart | null;
}

/** The form checked as the queue would check it, where the page can know. */
export function checkParts(
  choice: PartsPosition,
  rows: readonly ValueRow[],
  texts: readonly string[],
  again: StatedPart | null,
): Checked {
  const problems: string[] = [];
  if (choice === "find") {
    if (again !== null)
      problems.push(
        "This part was raised again after its values were written: choose I have it or I will " +
          "make it.",
      );
    return { problems, stated: null };
  }
  const declared: Record<string, DeclaredValue> = {};
  for (const row of rows) {
    const name = row.name.trim();
    const value = row.value.trim();
    const unit = row.unit.trim();
    if (value === "" && unit === "" && (!row.added || name === "")) continue;
    if (row.added && name === "") {
      problems.push(`${row.label}: name the quantity.`);
      continue;
    }
    if (row.added && !QUANTITY_NAME.test(name)) {
      problems.push(
        `${row.label}: a quantity's name is lowercase letters, digits and underscores, starting ` +
          "with a letter.",
      );
      continue;
    }
    if (value === "") {
      problems.push(`${row.label}: a unit needs its value.`);
      continue;
    }
    if (unit === "") {
      problems.push(`${row.label}: a value needs its unit.`);
      continue;
    }
    const number = numberOf(value);
    if (number === null) {
      problems.push(`${row.label}: the value must be a number, such as 1.5 or 2e-3.`);
      continue;
    }
    if (name in declared) {
      problems.push(`${name} is stated twice.`);
      continue;
    }
    declared[name] = { value: number, unit };
  }
  if (Object.keys(declared).length > MAX_DECLARED)
    problems.push(`At most ${String(MAX_DECLARED)} values are stated of a part.`);
  const said = choice === "make" ? texts.filter((t) => !isBlank(t)) : [];
  said.forEach((t, i) => {
    if (t.length > MAX_TEXT)
      problems.push(`Text ${String(i + 1)}: at most ${String(MAX_TEXT)} characters.`);
  });
  if (said.length > MAX_TEXTS) problems.push(`At most ${String(MAX_TEXTS)} texts.`);
  const stated = Object.keys(declared).length;
  if (choice === "have" && stated === 0 && !problems.some((p) => p.includes(":")))
    problems.push("To choose I have it, state at least one value with its unit.");
  if (choice === "make" && stated === 0 && said.length === 0 && problems.length === 0)
    problems.push("To choose I will make it, state at least one value or one text it must meet.");
  if (again !== null) {
    const missing = Object.keys(again.declared).filter((n) => !(n in declared));
    if (missing.length > 0)
      problems.push(
        `This part was raised again: state ${missing.join(", ")} again, with the value ` +
          `${missing.length === 1 ? "it" : "each"} now has.`,
      );
  }
  return { problems, stated: { declared, texts: said } };
}
