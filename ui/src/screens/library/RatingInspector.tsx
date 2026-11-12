/**
 * One rating's whole record in the inspector: for a range or an envelope, its values with their
 * units, its component class, its full source citation, when it was retrieved and confirmed, its
 * note, and the bounds file it comes from with that file's digest and a way to open it; for an
 * energy-store class, its rated discharge and its citation in the gate's catalogue.
 */
import type { Ratings as RatingsRecord } from "../../api/library";
import { Id } from "../../design/components/data/Id";
import { Quantity } from "../../design/components/data/Quantity";
import { SourceChip } from "../../design/components/data/SourceChip";
import { sourceAttribute } from "../../design/components/data/source";
import { Inspector, InspectorSection } from "../../design/components/layout/Inspector";
import { EmptyState } from "../../design/components/status/States";
import { quantityLabel } from "../../words/humanise";
import { documentLabel, LIBRARY_COPY } from "../../words/library";
import type { Open } from "./model";
import { useFocusOnOpen } from "./parts";
import { RangeOf, storeLabel, tableRole } from "./Ratings";

export function RatingInspector({
  open,
  ratings,
  hrefFile,
}: {
  readonly open: Open & { readonly kind: "range" | "envelope" | "store" };
  readonly ratings: RatingsRecord;
  /** The address that opens a bounds file, by its role. */
  readonly hrefFile: (role: string) => string;
}) {
  const focus = useFocusOnOpen(JSON.stringify(open));
  if (open.kind === "store") {
    const store = ratings.storeClasses[open.index];
    if (store === undefined) return <Missing />;
    return (
      <Inspector
        label="Rating"
        crumbs={["Library", LIBRARY_COPY.storeClasses]}
        title={
          <span ref={focus} tabIndex={-1} className="pg-lib-focus">
            {storeLabel(store.name)}
          </span>
        }
      >
        <div data-source={sourceAttribute({ id: LIBRARY_COPY.catalogue, commit: null })}>
          <InspectorSection label="Rating">
            <dl className="pg-facts">
              <dt>Fastest rated discharge</dt>
              <dd>
                <Quantity {...store.fastestDischarge} />
              </dd>
            </dl>
          </InspectorSection>
          <InspectorSection label="Source">
            <dl className="pg-facts">
              <dt>Cited</dt>
              <dd>{store.source}</dd>
              <dt>Confirmed</dt>
              <dd>{store.confirmed}</dd>
              <dt>Catalogue digest</dt>
              <dd>
                <Id value={ratings.catalogueDigest} />
              </dd>
            </dl>
            <SourceChip id={LIBRARY_COPY.catalogue} commit={null} />
          </InspectorSection>
        </div>
      </Inspector>
    );
  }
  const table = ratings.tables[open.table];
  const rating = (open.kind === "range" ? table?.ranges : table?.envelopes)?.[open.index];
  if (table === undefined || rating === undefined) return <Missing />;
  const role = tableRole(table);
  return (
    <Inspector
      label="Rating"
      crumbs={["Library", documentLabel("bounds", role)]}
      title={
        <span ref={focus} tabIndex={-1} className="pg-lib-focus">
          {quantityLabel(rating.key)}
        </span>
      }
      badges={<Id value={rating.key} copy={false} />}
    >
      <div data-source={sourceAttribute({ id: table.path, commit: null })}>
        <InspectorSection label="Rating">
          <dl className="pg-facts">
            <dt>Range</dt>
            <dd>
              <RangeOf rating={rating} />
            </dd>
            <dt>Component class</dt>
            <dd>{rating.componentClass}</dd>
            {rating.kind !== null && (
              <>
                <dt>Kind</dt>
                <dd>{rating.kind}</dd>
              </>
            )}
          </dl>
        </InspectorSection>
        <InspectorSection label="Source">
          <dl className="pg-facts">
            <dt>Cited</dt>
            <dd>{rating.source}</dd>
            <dt>Retrieved</dt>
            <dd>{rating.retrieved}</dd>
            <dt>Confirmed</dt>
            <dd>{rating.confirmed}</dd>
            <dt>Note</dt>
            <dd>{rating.note === "" ? <span className="pg-muted">none</span> : rating.note}</dd>
          </dl>
        </InspectorSection>
        <InspectorSection label="File">
          <dl className="pg-facts">
            <dt>Path</dt>
            <dd>
              <Id value={table.path} />
            </dd>
            <dt>sha256</dt>
            <dd>
              <Id value={table.sha256} />
            </dd>
          </dl>
          <SourceChip id={table.path} commit={null} compact />
          <a className="pg-hit pg-lib-open" href={hrefFile(role)}>
            {LIBRARY_COPY.openTheFile}
          </a>
        </InspectorSection>
      </div>
    </Inspector>
  );
}

/** An address naming a rating the answer does not hold. */
function Missing() {
  return (
    <Inspector label="Rating" crumbs={["Library"]} title="Not in the ratings">
      <EmptyState title="The ratings hold no record at this address." icon="table" />
    </Inspector>
  );
}
