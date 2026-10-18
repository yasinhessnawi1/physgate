import { Icon, type IconName } from "../icons/Icon";

export type Provenance = "have" | "make" | "find";

const SHOWN: Readonly<Record<Provenance, readonly [IconName, string]>> = {
  have: ["package-check", "Have it"],
  make: ["hammer", "Make it"],
  find: ["search", "Find it"],
};

/** How a component is sourced: declared by the user (have), made (make), or found (find). */
export function ProvenanceTag({ kind }: { readonly kind: Provenance }) {
  const [icon, word] = SHOWN[kind];
  return (
    <span className={`pg-provenance pg-provenance-${kind}`}>
      <Icon name={icon} size={11} />
      {word}
    </span>
  );
}
