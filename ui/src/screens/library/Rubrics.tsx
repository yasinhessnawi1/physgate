/**
 * The reviewers' rubrics, from the promotion log alone: the server withholds the reviewers'
 * folder, so a builder cannot read the rubric it is judged by over this page. Each rubric shows
 * the latest line in log order (who, when, its digest) and how many lines name it. No row opens
 * and none has a state: the file's bytes are never read here.
 */
import type { Rubric } from "../../api/library";
import { Id } from "../../design/components/data/Id";
import { DataTable } from "../../design/components/layout/DataTable";
import { EmptyState } from "../../design/components/status/States";
import { documentLabel, LIBRARY_COPY, promotionLines } from "../../words/library";
import { PromotedAt, PromotedBy, ShortDigest } from "./parts";

export function RubricsTable({ rubrics }: { readonly rubrics: readonly Rubric[] }) {
  return (
    <div className="pg-card pg-panel">
      <p className="pg-panel-note">{LIBRARY_COPY.rubricsNote}</p>
      {rubrics.length === 0 ? (
        <EmptyState title={LIBRARY_COPY.noRubrics} icon="library" />
      ) : (
        <DataTable
          label="Reviewer rubrics"
          rows={rubrics}
          rowKey={(r) => r.path}
          columns={[
            {
              key: "rubric",
              label: "Rubric",
              render: (r) => (
                <span className="pg-lib-doc">
                  <span className="pg-lib-label">
                    {r.role === null ? "A reviewer rubric" : documentLabel("rubric", r.role)}
                  </span>
                  <Id value={r.path} copy={false} />
                </span>
              ),
            },
            {
              key: "promoted",
              label: "Promoted (latest in the log)",
              render: (r) => <PromotedAt line={r.promotions.at(-1) ?? null} />,
            },
            {
              key: "by",
              label: "Promoted by",
              render: (r) => <PromotedBy line={r.promotions.at(-1) ?? null} />,
            },
            {
              key: "sha256",
              label: "sha256",
              render: (r) => {
                const digest = r.promotions.at(-1)?.sha256 ?? null;
                return digest === null ? (
                  <span className="pg-muted">{LIBRARY_COPY.noDigest}</span>
                ) : (
                  <ShortDigest value={digest} />
                );
              },
            },
            {
              key: "lines",
              label: "Lines in the log",
              render: (r) => promotionLines(r.promotions.length),
            },
          ]}
        />
      )}
    </div>
  );
}
