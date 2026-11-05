/**
 * The ratings the gate checks values against: each bounds table's ranges and envelopes, and the
 * catalogue's energy-store classes. Every value is a quantity with its unit, as recorded, never
 * rounded. Every rating names its file as its source; a read route runs no git, so the commit is
 * never known here and the chip says so. Each row opens its whole record in the inspector.
 */
import type { BoundsTable, Rating, Ratings as RatingsRecord } from "../../api/library";
import { Id } from "../../design/components/data/Id";
import { Quantity } from "../../design/components/data/Quantity";
import { SourceChip } from "../../design/components/data/SourceChip";
import { sourceAttribute } from "../../design/components/data/source";
import { DataTable } from "../../design/components/layout/DataTable";
import { EmptyState } from "../../design/components/status/States";
import { quantityLabel } from "../../words/humanise";
import { documentLabel, LIBRARY_COPY } from "../../words/library";
import type { Open } from "./model";

/** A store class's name, as the catalogue writes it, in sentence case. */
export function storeLabel(name: string): string {
  return `${(name[0] ?? "").toUpperCase()}${name.slice(1)}`;
}

/** The role folder a table's file lies in, from its path; its domain if the path names none. */
export function tableRole(table: BoundsTable): string {
  return table.path.split("/")[1] ?? table.domain;
}

export function RangeOf({ rating }: { readonly rating: Rating }) {
  return (
    <span className="pg-lib-range">
      <Quantity {...rating.low} />
      <span className="pg-muted">to</span>
      <Quantity {...rating.high} />
    </span>
  );
}

function RatingsTable({
  name,
  table,
  at,
  ratings,
  kind,
  hrefOpen,
}: {
  readonly name: string;
  readonly table: BoundsTable;
  /** The table's position in the answer, which the address names it by. */
  readonly at: number;
  readonly ratings: readonly Rating[];
  readonly kind: "range" | "envelope";
  readonly hrefOpen: (open: Open) => string;
}) {
  const index = new Map(ratings.map((r, i) => [r, i]));
  return (
    <DataTable
      label={name}
      rows={ratings}
      rowKey={(r) => r.key}
      columns={[
        {
          key: "quantity",
          label: kind === "range" ? "Quantity" : "Kind",
          // The link holds the label and the key under it, so its hit area is the whole cell's
          // and never reaches into the table's header.
          render: (r) => (
            <a
              className="pg-hit pg-lib-open pg-lib-doc"
              href={hrefOpen({ kind, table: at, index: index.get(r) ?? 0 })}
            >
              <span className="pg-lib-label">{quantityLabel(r.key)}</span>
              <Id value={r.key} copy={false} />
            </a>
          ),
        },
        { key: "range", label: "Range", render: (r) => <RangeOf rating={r} /> },
        {
          key: "class",
          label: "Component class",
          wrap: true,
          render: (r) => r.componentClass,
        },
        { key: "confirmed", label: "Confirmed", render: (r) => r.confirmed },
        {
          key: "source",
          label: "Source",
          render: () => <SourceChip id={table.path} commit={null} compact />,
        },
      ]}
    />
  );
}

export function RatingsSection({
  ratings,
  hrefOpen,
}: {
  readonly ratings: RatingsRecord;
  readonly hrefOpen: (open: Open) => string;
}) {
  return (
    <>
      {ratings.tables.length === 0 ? (
        <EmptyState title={LIBRARY_COPY.noBoundsTable} icon="table" />
      ) : (
        ratings.tables.map((table, t) => {
          const name = documentLabel("bounds", tableRole(table));
          return (
            <section
              key={table.path}
              className="pg-card pg-panel"
              aria-label={name}
              data-source={sourceAttribute({ id: table.path, commit: null })}
            >
              <h2 className="pg-panel-title">{name}</h2>
              <h3 className="pg-section-label">Ranges</h3>
              {table.ranges.length === 0 ? (
                <p className="pg-muted">{LIBRARY_COPY.noRange}</p>
              ) : (
                <RatingsTable
                  name={`${name} ranges`}
                  table={table}
                  ratings={table.ranges}
                  at={t}
                  kind="range"
                  hrefOpen={hrefOpen}
                />
              )}
              <h3 className="pg-section-label">Envelopes</h3>
              {table.envelopes.length === 0 ? (
                <p className="pg-muted">{LIBRARY_COPY.noEnvelope}</p>
              ) : (
                <RatingsTable
                  name={`${name} envelopes`}
                  table={table}
                  ratings={table.envelopes}
                  at={t}
                  kind="envelope"
                  hrefOpen={hrefOpen}
                />
              )}
              <p className="pg-panel-note pg-lib-ids">
                <span>File</span>
                <Id value={table.path} copy={false} />
                <span>sha256</span>
                <Id value={table.sha256} />
              </p>
            </section>
          );
        })
      )}
      <section
        className="pg-card pg-panel"
        data-source={sourceAttribute({ id: LIBRARY_COPY.catalogue, commit: null })}
      >
        <h2 className="pg-panel-title">{LIBRARY_COPY.storeClasses}</h2>
        <DataTable
          label={LIBRARY_COPY.storeClasses}
          rows={ratings.storeClasses}
          rowKey={(s) => s.name}
          columns={[
            {
              key: "class",
              label: "Class",
              wrap: true,
              render: (s) => (
                // A box, not an inline run: a name that wraps keeps one whole target.
                <a
                  className="pg-hit pg-lib-open pg-lib-doc"
                  href={hrefOpen({ kind: "store", index: ratings.storeClasses.indexOf(s) })}
                >
                  {storeLabel(s.name)}
                </a>
              ),
            },
            {
              key: "discharge",
              label: "Fastest rated discharge",
              numeric: true,
              render: (s) => <Quantity {...s.fastestDischarge} />,
            },
            { key: "confirmed", label: "Confirmed", render: (s) => s.confirmed },
            {
              key: "source",
              label: "Source",
              render: () => <SourceChip id={LIBRARY_COPY.catalogue} commit={null} compact />,
            },
          ]}
        />
        <p className="pg-panel-note pg-lib-ids">
          <SourceChip id={LIBRARY_COPY.catalogue} commit={null} />
          <span>Catalogue digest</span>
          <Id value={ratings.catalogueDigest} />
        </p>
      </section>
    </>
  );
}
