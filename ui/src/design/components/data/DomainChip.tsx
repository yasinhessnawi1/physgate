/** The schema's five domains (`state.schema.DomainKind`); a test holds this list to the tokens. */
export const DOMAIN_KINDS = ["mechanical", "electrical", "control", "firmware", "cross"] as const;
export type Domain = (typeof DOMAIN_KINDS)[number];

const WORDS: Readonly<Record<Domain, string>> = {
  mechanical: "Mechanical",
  electrical: "Electrical",
  control: "Control",
  firmware: "Firmware",
  cross: "Cross-domain",
};

/** A domain is its word, outlined, in a neutral colour: never colour alone. */
export function DomainChip({ domain }: { readonly domain: Domain }) {
  return <span className={`pg-domain pg-domain-${domain}`}>{WORDS[domain]}</span>;
}
