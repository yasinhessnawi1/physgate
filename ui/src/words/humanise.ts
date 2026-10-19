/**
 * Plain words for a design-state key, and never more than the key says.
 *
 * The graph's records carry no label a person wrote, so a node or a quantity is read from its
 * key: split on "." and "_", each token expanded only if this one table names it, and the result
 * written in sentence case. A token the table does not hold is shown exactly as written: it is
 * never guessed at. So `elec.driver` reads "Driver" under an Electrical chip, and never "Motor
 * driver", which the record does not say.
 */
import type { Domain } from "../api/graph";

/**
 * The only expansions the humaniser makes. Each is an abbreviation, or a word written as
 * itself, found in the keys today's runs record. Every entry has a test.
 */
export const VOCABULARY: Readonly<Record<string, string>> = {
  elec: "electrical",
  mech: "mechanical",
  ctl: "control",
  ctrl: "control",
  fw: "firmware",
  iface: "interface",
  bw: "bandwidth",
  temp: "temperature",
  max: "maximum",
  min: "minimum",
  pwr: "power",
  freq: "frequency",
  req: "requirement",
  pm: "phase margin",
  foc: "field-oriented control",
  pcb: "circuit board",
  mcu: "microcontroller",
};

/** The tokens that name a domain, whichever way the key writes it. */
const DOMAIN_TOKENS: Readonly<Record<string, Domain>> = {
  electrical: "electrical",
  elec: "electrical",
  mechanical: "mechanical",
  mech: "mechanical",
  control: "control",
  ctl: "control",
  ctrl: "control",
  firmware: "firmware",
  fw: "firmware",
  cross: "cross",
};

/** One token in words: from the table, or as written. */
export function word(token: string): string {
  return VOCABULARY[token.toLowerCase()] ?? token;
}

function sentence(words: readonly string[]): string {
  const text = words.filter((w) => w !== "").join(" ");
  return text === "" ? text : `${(text[0] ?? "").toUpperCase()}${text.slice(1)}`;
}

/** A quantity's name in words: `stall_current` reads "Stall current". */
export function quantityLabel(name: string): string {
  const label = sentence(name.split(/[._]/).map(word));
  return label === "" ? name : label;
}

/**
 * A node's key in words. When the key's first segment names the node's own domain, it is left
 * out: the domain chip beside the label already says it. A key that is nothing but its domain
 * keeps it.
 */
export function nodeLabel(key: string, domain?: Domain): string {
  const segments = key.split(".");
  const first = segments[0] ?? "";
  const rest =
    segments.length > 1 && domain !== undefined && DOMAIN_TOKENS[first.toLowerCase()] === domain
      ? segments.slice(1)
      : segments;
  const label = sentence(rest.flatMap((s) => s.split("_")).map(word));
  return label === "" ? key : label;
}
