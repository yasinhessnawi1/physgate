/**
 * What is waiting for promotion: every staged candidate, read-only, in two groups. A change to a
 * standards or skill file reads differently from an antipattern, which always adds to a skill
 * file, so each has its own group, every row labelled by the file it would change. A staged file
 * promotion would refuse keeps its row, with the reason as a sentence.
 */
import { STAGED_ROUTE, type StagedCandidate, stagedList } from "../../api/library";
import { Id } from "../../design/components/data/Id";
import { Quantity } from "../../design/components/data/Quantity";
import { sourceAttribute } from "../../design/components/data/source";
import { DataTable } from "../../design/components/layout/DataTable";
import { EmptyState, ErrorState, LoadingState } from "../../design/components/status/States";
import {
  candidateErrorWords,
  candidateLabel,
  LIBRARY_COPY,
  stagedErrorLabel,
  writtenWords,
} from "../../words/library";
import { useJson } from "../common/read";

const ANTIPATTERN = "antipattern";

function label(c: StagedCandidate): string {
  return c.error === null ? candidateLabel(c.kind, c.replaces, c.role) : stagedErrorLabel(c.kind);
}

function CandidatesTable({
  name,
  candidates,
  hrefOpen,
  selected,
}: {
  readonly name: string;
  readonly candidates: readonly StagedCandidate[];
  readonly hrefOpen: (id: string) => string;
  readonly selected: string | null;
}) {
  return (
    <section className="pg-card pg-panel pg-lib-group">
      <h2 className="pg-panel-title">{name}</h2>
      <DataTable
        label={name}
        rows={candidates}
        rowKey={(c) => (c.error === null ? c.candidateId : `${c.kind}/${c.name}`)}
        selectedKey={selected}
        columns={[
          {
            key: "candidate",
            label: "Proposed change",
            wrap: true,
            render: (c) => (
              <span className="pg-lib-doc">
                <span className="pg-lib-label">{label(c)}</span>
                {c.error === null ? (
                  <>
                    <span className="pg-panel-note">{writtenWords(c.written)}</span>
                    <span className="pg-lib-ids">
                      <span className="pg-label">Episode</span>
                      <Id value={c.episodeId} copy={false} />
                      <span className="pg-label">Candidate</span>
                      <Id value={c.candidateId} copy={false} />
                    </span>
                  </>
                ) : (
                  <>
                    <Id value={c.name} copy={false} />
                    <span className="pg-lib-row-error-text">{candidateErrorWords(c.error)}</span>
                  </>
                )}
              </span>
            ),
          },
          {
            key: "destination",
            label: "Would change",
            render: (c) => (c.error === null ? <Id value={c.destination} copy={false} /> : null),
          },
          {
            key: "size",
            label: "Staged file size",
            numeric: true,
            render: (c) =>
              c.error === null ? (
                <span data-source={sourceAttribute({ id: c.name, commit: null })}>
                  <Quantity value={c.size} unit="B" />
                </span>
              ) : null,
          },
          {
            key: "open",
            label: "Open",
            render: (c) =>
              c.error === null ? (
                <a className="pg-hit pg-lib-open" href={hrefOpen(c.candidateId)}>
                  Open<span className="pg-visually-hidden"> {label(c)}</span>
                </a>
              ) : null,
          },
        ]}
      />
    </section>
  );
}

export function Proposed({
  hrefOpen,
  selected,
}: {
  readonly hrefOpen: (id: string) => string;
  readonly selected: string | null;
}) {
  const read = useJson(STAGED_ROUTE, stagedList);
  if (read.result === null) return <LoadingState reading={LIBRARY_COPY.reading} />;
  if (!read.result.ok)
    return (
      <ErrorState
        title={LIBRARY_COPY.stagedError}
        {...read.result.refusal}
        route={read.route}
        onRetry={read.again}
      />
    );
  const all = read.result.value;
  if (all.length === 0) return <EmptyState title={LIBRARY_COPY.nothingProposed} icon="inbox" />;
  const changes = all.filter((c) => c.kind !== ANTIPATTERN);
  const antipatterns = all.filter((c) => c.kind === ANTIPATTERN);
  return (
    <>
      {changes.length > 0 && (
        <CandidatesTable
          name={LIBRARY_COPY.changes}
          candidates={changes}
          hrefOpen={hrefOpen}
          selected={selected}
        />
      )}
      {antipatterns.length > 0 && (
        <CandidatesTable
          name={LIBRARY_COPY.antipatterns}
          candidates={antipatterns}
          hrefOpen={hrefOpen}
          selected={selected}
        />
      )}
    </>
  );
}
