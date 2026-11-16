/**
 * The gate's catches, per kind of run: each kind counted over its own runs alone, in its own
 * section, and never added to another kind's. A rate is shown only as "k of n". A kind whose
 * runs ran no gate check says so in words, never a zero, and the runs that could not be read
 * are named apart with their reasons.
 */
import { SourceChip } from "../../design/components/data/SourceChip";
import { sourceAttribute } from "../../design/components/data/source";
import type { CatchRow, Catches, KindCatches } from "./api";
import { checkWords } from "../../words/checks";
import { answerSource, KindTag, UnreadList } from "./parts";
import { EVIDENCE_COPY, KIND_HEADINGS, kOfN } from "./words";

const HEADS = [
  EVIDENCE_COPY.checksRun,
  EVIDENCE_COPY.blockingFailures,
  EVIDENCE_COPY.reviewerPassed,
  EVIDENCE_COPY.reviewerFailed,
  EVIDENCE_COPY.notReviewed,
  EVIDENCE_COPY.artefactsCaught,
  EVIDENCE_COPY.caughtAfterPass,
];

function counts(row: CatchRow): readonly string[] {
  return [
    String(row.checksRun),
    String(row.blockingFailures),
    String(row.reviewerHadPassed),
    String(row.reviewerHadFailed),
    String(row.noReview),
    String(row.artefactsCaught),
    kOfN(row.caughtAfterReviewerPassed, row.artefactsCaught),
  ];
}

function checkName(row: CatchRow): string {
  return row.check === null ? EVIDENCE_COPY.allChecks : checkWords(row.name).name;
}

function KindCount({ count }: { readonly count: KindCatches }) {
  const heading = KIND_HEADINGS[count.kind];
  const sources = count.runs.map(answerSource);
  return (
    <section
      className="pg-card pg-panel evidence-kind"
      aria-label={heading}
      data-kind={count.kind}
      data-source={sources.map(sourceAttribute).join(" ")}
    >
      <h2 className="pg-panel-title">{heading}</h2>
      <KindTag kind={count.kind} />
      {count.runs.length === 0 ? (
        <p className="evidence-note">{EVIDENCE_COPY.noneOfKind}</p>
      ) : (
        <p className="evidence-sources">
          <span className="evidence-label">{EVIDENCE_COPY.countedOver}</span>
          {sources.map((source) => (
            <SourceChip key={source.id} id={source.id} commit={source.commit} compact />
          ))}
        </p>
      )}
      {count.runs.length > 0 && count.rows.length === 0 && (
        <p className="evidence-note">{EVIDENCE_COPY.noCheck}</p>
      )}
      {count.rows.length > 0 && (
        <div className="pg-table-wrap" role="region" aria-label={heading} tabIndex={0}>
          <table className="pg-table evidence-catches">
            <thead>
              <tr>
                <th scope="col">{EVIDENCE_COPY.check}</th>
                <th scope="col">{EVIDENCE_COPY.gateMode}</th>
                {HEADS.map((label) => (
                  <th key={label} scope="col" className="pg-num">
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {count.rows.map((row) => (
                <tr key={`${row.gateMode}/${row.name}`} data-check={row.name}>
                  <th scope="row">{checkName(row)}</th>
                  <td>{row.gateMode}</td>
                  {counts(row).map((shown, i) => (
                    <td key={HEADS[i] ?? i} className="pg-num">
                      {shown}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function CatchesTab({ catches }: { readonly catches: Catches }) {
  return (
    <>
      <p className="evidence-note">{EVIDENCE_COPY.catchesLead}</p>
      {catches.kinds.map((count) => (
        <KindCount key={count.kind} count={count} />
      ))}
      <UnreadList title={EVIDENCE_COPY.notCounted} rows={catches.unread} />
    </>
  );
}
