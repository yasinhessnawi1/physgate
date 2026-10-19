/**
 * The physics gate's seven checks in words: one human name and a one-line explanation each. The
 * table is keyed by the schema's own list of check names, so a check the gate gains and this
 * table lacks is a type error, and a test holds the list to the schema.
 */
import type { CheckName } from "../api/run";

export interface CheckWords {
  /** What a person reads first: "Power balance check". */
  readonly name: string;
  /** One sentence: what the check looks at. */
  readonly explains: string;
}

export const CHECK_WORDS: Readonly<Record<CheckName, CheckWords>> = {
  units: {
    name: "Units check",
    explains: "Every quantity's unit is one the gate knows, and the units in each relation agree.",
  },
  magnitude: {
    name: "Plausible value check",
    explains: "Each value lies inside the range a source gives for its kind of quantity.",
  },
  equilibrium: {
    name: "Static balance check",
    explains: "The loads on each mount are carried by its supports, so it is in equilibrium.",
  },
  power: {
    name: "Power balance check",
    explains: "What the consumers on a supply draw does not exceed what it supplies.",
  },
  conservation: {
    name: "Conservation check",
    explains:
      "A module's mass is the sum of its parts', and a node's power in equals its power out plus its heat.",
  },
  thermal: {
    name: "Thermal margin check",
    explains: "Each part stays below its maximum temperature, and each module can reject its heat.",
  },
  propagation: {
    name: "Change propagation check",
    explains: "A changed value reaches every node it constrains, or that node says why not.",
  },
};

/** The words for a check name as recorded; an unknown name is shown as written. */
export function checkWords(name: string): CheckWords {
  return (CHECK_WORDS as Readonly<Record<string, CheckWords>>)[name] ?? { name, explains: "" };
}
