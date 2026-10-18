import type { ReactNode } from "react";

import { Segmented } from "../actions/Segmented";
import { type Domain, DomainChip } from "../data/DomainChip";
import type { DataTableColumn } from "../layout/DataTable";
import type { Provenance } from "./ProvenanceTag";

/** A component from the decomposition, with the person's have, make or find decision. */
export interface Part {
  readonly name: string;
  /** The node key, for example "elec.driver". */
  readonly role: string;
  readonly domain: Domain;
  readonly choice: Provenance;
  /** Where the decision stands, in words: "Specs 6 of 6 · gate checked: fail". */
  readonly status: ReactNode;
}

const OPTIONS = [
  { value: "have", label: "Have", icon: "package-check" },
  { value: "make", label: "Make", icon: "hammer" },
  { value: "find", label: "Find", icon: "search" },
] as const;

/**
 * The sourcing control and, wrapped beneath it, the status: the status never sits in a column of
 * its own that a narrow table would cut. No route records a parts decision in this build, so the
 * control shows the choice and cannot change it.
 */
export function Sourcing({
  part,
  onChoose,
}: {
  readonly part: Part;
  readonly onChoose?: (c: Provenance) => void;
}) {
  return (
    <span className="pg-part-sourcing">
      <Segmented
        label={`Sourcing for ${part.name}`}
        value={part.choice}
        options={OPTIONS}
        disabled={onChoose === undefined}
        {...(onChoose === undefined ? {} : { onChange: onChoose })}
      />
      <span className="pg-part-status">{part.status}</span>
    </span>
  );
}

/** The parts table's columns: the part (name, then key), its domain, and its sourcing with status. */
export function partColumns(
  onChoose?: (part: Part, choice: Provenance) => void,
): DataTableColumn<Part>[] {
  return [
    {
      key: "part",
      label: "Part",
      wrap: true,
      sortValue: (p) => p.name,
      render: (p) => <PartName part={p} />,
    },
    {
      key: "domain",
      label: "Domain",
      sortValue: (p) => p.domain,
      render: (p) => <DomainChip domain={p.domain} />,
    },
    {
      key: "sourcing",
      label: "Sourcing",
      wrap: true,
      render: (p) =>
        onChoose === undefined ? (
          <Sourcing part={p} />
        ) : (
          <Sourcing
            part={p}
            onChoose={(c) => {
              onChoose(p, c);
            }}
          />
        ),
    },
  ];
}

function PartName({ part }: { readonly part: Part }) {
  return (
    <span className="pg-part-name">
      <strong>{part.name}</strong>
      <span className="pg-id">{part.role}</span>
    </span>
  );
}

/** One part as a row outside a table: its name, key, domain, sourcing and status. */
export function PartRow({
  part,
  onChoose,
}: {
  readonly part: Part;
  readonly onChoose?: (c: Provenance) => void;
}) {
  return (
    <div className="pg-part">
      <PartName part={part} />
      <DomainChip domain={part.domain} />
      {onChoose === undefined ? (
        <Sourcing part={part} />
      ) : (
        <Sourcing part={part} onChoose={onChoose} />
      )}
    </div>
  );
}
