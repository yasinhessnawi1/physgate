/**
 * One kind of library file, a row per role: its label first, its path under it, the role, the
 * promotion that wrote it and who made it, its digest and its state, chosen by its bytes. A file
 * the server could not read keeps its row, with the reason as a sentence.
 */
import type { LibraryDocument } from "../../api/library";
import { Id } from "../../design/components/data/Id";
import { DataTable } from "../../design/components/layout/DataTable";
import { EmptyState } from "../../design/components/status/States";
import { StatusTag } from "../../design/components/status/StatusTag";
import { documentErrorWords, documentLabel } from "../../words/library";
import { STATE_TAGS } from "./model";
import { PromotedAt, PromotedBy, RoleTag, ShortDigest } from "./parts";

const key = (d: LibraryDocument) => `${d.kind}/${d.role}`;

export function DocumentsTable({
  label,
  documents,
  empty,
  hrefOpen,
  selected,
}: {
  /** The table's name: "Standards" or "Skills". */
  readonly label: string;
  readonly documents: readonly LibraryDocument[];
  /** What is said when the library holds none. */
  readonly empty: string;
  readonly hrefOpen: (doc: LibraryDocument) => string;
  /** The ``kind/role`` open in the inspector, if any. */
  readonly selected: string | null;
}) {
  if (documents.length === 0) return <EmptyState title={empty} icon="library" />;
  return (
    <DataTable
      label={label}
      rows={documents}
      rowKey={key}
      selectedKey={selected}
      columns={[
        {
          key: "document",
          label: "Document",
          render: (d) => (
            <span className="pg-lib-doc">
              <span className="pg-lib-label">{documentLabel(d.kind, d.role)}</span>
              <Id value={d.path} copy={false} />
            </span>
          ),
        },
        { key: "role", label: "Role", render: (d) => <RoleTag role={d.role} /> },
        {
          key: "promoted",
          label: "Promoted",
          render: (d) => (d.error === null ? <PromotedAt line={d.promotion} /> : null),
        },
        {
          key: "by",
          label: "Promoted by",
          render: (d) => (d.error === null ? <PromotedBy line={d.promotion} /> : null),
        },
        {
          key: "sha256",
          label: "sha256",
          render: (d) => (d.error === null ? <ShortDigest value={d.sha256} /> : null),
        },
        {
          key: "state",
          label: "State",
          wrap: true,
          render: (d) =>
            d.error === null ? (
              <StatusTag status={STATE_TAGS[d.state]} />
            ) : (
              <span className="pg-lib-row-error">
                <StatusTag status="refused" />
                <span>{documentErrorWords(d.error)}</span>
              </span>
            ),
        },
        {
          key: "open",
          label: "Open",
          render: (d) =>
            d.error === null ? (
              <a className="pg-hit pg-lib-open" href={hrefOpen(d)}>
                Open<span className="pg-visually-hidden"> {documentLabel(d.kind, d.role)}</span>
              </a>
            ) : null,
        },
      ]}
    />
  );
}
