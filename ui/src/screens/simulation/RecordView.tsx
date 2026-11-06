/**
 * One record: its title as the role wrote it, then a plot per unit of its sealed columns, each
 * with the server's summary as text and every row as a table, then what was read off it, then
 * its inputs and how it was produced.
 *
 * A record that is not what its session sealed, or that this version cannot read, is a sentence
 * in its place and nothing else: no plot, no table, no summary and no input from it. The samples
 * are read only when the record is opened, and only from the record's sealed bytes.
 */
import { type ReactNode, useEffect, useMemo, useRef } from "react";

import {
  type AttemptRecord,
  type RecordSamples,
  recordRoute,
  recordSamples,
  type SeriesCheck,
  type ShownRecord,
} from "../../api/series";
import { Button } from "../../design/components/actions/Button";
import { Id } from "../../design/components/data/Id";
import { Quantity } from "../../design/components/data/Quantity";
import { SourceChip } from "../../design/components/data/SourceChip";
import { type Source, sourceAttribute } from "../../design/components/data/source";
import { Term } from "../../design/components/help/Term";
import { Plot, PlotTable } from "../../design/components/plot/Plot";
import { PlotFrame } from "../../design/components/plot/PlotFrame";
import { ErrorState, LoadingState, type Refusal } from "../../design/components/status/States";
import { quantityLabel } from "../../words/humanise";
import {
  agreementWords,
  extractorWords,
  heldWords,
  SEAL_WORDS,
  SERIES_COPY,
  titledBy,
  unreadWords,
} from "../../words/series";
import { useJson } from "../common/read";
import { plotsOf } from "./model";
import { Tag } from "./Tag";

/** What the reader reported about a record it would not serve: shown under "Details". */
interface Seal {
  readonly record: string | null;
  readonly sealedSha256: string | null;
  readonly sealedLength: string | null;
  readonly foundSha256: string | null;
  readonly foundLength: string | null;
  readonly reason: string;
}

/**
 * A record refused on its seal, or held as unreadable: its sentence, and the seal under Details.
 * Neutral ink: a refusal, not a verdict.
 */
export function SealRefusal({
  title,
  recordId,
  seal,
}: {
  readonly title: string;
  readonly recordId: string;
  readonly seal: Seal;
}) {
  const rows: [string, string | null][] = [
    ["record", recordId],
    ["place in the run", seal.record],
    ["reason", seal.reason],
    ["sealed sha256", seal.sealedSha256],
    ["sealed length", seal.sealedLength === null ? null : `${seal.sealedLength} B`],
    ["found sha256", seal.foundSha256],
    ["found length", seal.foundLength === null ? null : `${seal.foundLength} B`],
  ];
  return (
    <section className="pg-state pg-sim-refused" role="status" aria-label={title}>
      <h2 className="pg-state-title">{title}</h2>
      <details className="pg-details" open>
        <summary>Details</summary>
        <dl className="pg-state-context">
          {rows
            .filter((row): row is [string, string] => row[1] !== null)
            .map(([key, value]) => (
              <div key={key} className="pg-state-context-row">
                <dt>{key}</dt>
                <dd>{value}</dd>
              </div>
            ))}
        </dl>
      </details>
    </section>
  );
}

/** The refusal S3 answered with, as the screen shows it; ``null`` when it is not a seal's. */
function sealOf(refusal: Refusal): { readonly title: string; readonly seal: Seal } | null {
  const c = refusal.context;
  const seal: Seal = {
    record: c.record ?? null,
    sealedSha256: c.sealed_sha256 ?? null,
    sealedLength: c.sealed_length ?? null,
    foundSha256: c.found_sha256 ?? null,
    foundLength: c.found_length ?? null,
    reason: c.reason ?? refusal.error,
  };
  if (refusal.status === 422 && c.seal === "broken") return { title: SERIES_COPY.broken, seal };
  if (refusal.status === 422 && c.seal === "held")
    return { title: heldWords(c.reason ?? refusal.error), seal };
  return null;
}

/** The legend: each trace's label, never an id. */
function Legend({ labels }: { readonly labels: readonly string[] }) {
  return (
    <>
      {labels.map((label) => (
        <span key={label} className="pg-sim-key">
          <span className="pg-sim-swatch" aria-hidden="true" />
          {label}
        </span>
      ))}
    </>
  );
}

/** Each quantity read off this record, as the change check recorded it. */
function ReadOff({
  checks,
  tolerance,
  onShowRow,
}: {
  readonly checks: readonly { readonly check: SeriesCheck; readonly row: number }[];
  readonly tolerance: string;
  readonly onShowRow: (row: number) => void;
}) {
  if (checks.length === 0) return null;
  return (
    <section className="pg-sim-readoff" aria-label={SERIES_COPY.readOffTitle}>
      <h3 className="pg-sim-section-title">
        <Term term="read-off">{SERIES_COPY.readOffTitle}</Term>
      </h3>
      <ul className="pg-list">
        {checks.map(({ check, row }) => (
          <li key={row} className="pg-sim-readoff-row">
            <span className="pg-sim-readoff-main">
              <span>{quantityLabel(check.quantity)}</span>
              {check.read === null ? (
                <span className="pg-muted">{SERIES_COPY.notRead}</span>
              ) : (
                <Quantity {...check.read} />
              )}
              <span className="pg-muted">({extractorWords(check.extract, check.trace)})</span>
            </span>
            <span className="pg-sim-readoff-main">
              <Tag icon="circle-dot" kind={`agreement-${check.outcome}`}>
                {agreementWords(check.outcome, tolerance)}
              </Tag>
              <span className="pg-muted">In the design graph</span>
              <Quantity {...check.declared} />
            </span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                onShowRow(row);
              }}
            >
              {SERIES_COPY.showRow}
            </Button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Produced({ record }: { readonly record: ShownRecord }) {
  return (
    <details className="pg-details pg-sim-produced">
      <summary>{SERIES_COPY.inputsTitle}</summary>
      <div className="pg-sim-produced-body">
        <h4 className="pg-sim-section-title">{SERIES_COPY.inputs}</h4>
        {record.inputs.length === 0 ? (
          <p className="pg-muted">{SERIES_COPY.noInputs}</p>
        ) : (
          <dl className="pg-sim-inputs">
            {record.inputs.map(([name, value]) => (
              <div key={name} className="pg-sim-input">
                <dt>
                  {quantityLabel(name)} <Id value={name} copy={false} />
                </dt>
                <dd>
                  <Quantity {...value} />
                </dd>
              </div>
            ))}
          </dl>
        )}
        <h4 className="pg-sim-section-title">{SERIES_COPY.producedBy}</h4>
        <ul className="pg-list">
          <li className="pg-sim-file-row">
            <span className="pg-sim-file">{record.script.path}</span>
            <span>
              sha256 <Id value={record.script.sha256} />
            </span>
            {record.script.blob !== null && (
              <span>
                blob <Id value={record.script.blob} />
              </span>
            )}
          </li>
        </ul>
        {record.loaded.length + record.environment.length > 0 && (
          <>
            <h4 className="pg-sim-section-title">{SERIES_COPY.loaded}</h4>
            <ul className="pg-list">
              {record.loaded.map((file) => (
                <li key={file.path} className="pg-sim-file-row">
                  <span className="pg-sim-file">{file.path}</span>
                  {file.blob === null ? (
                    <span>
                      sha256 <Id value={file.sha256} copy={false} />
                    </span>
                  ) : (
                    <span>
                      blob <Id value={file.blob} copy={false} />
                    </span>
                  )}
                </li>
              ))}
              {record.environment.map((file) => (
                <li key={file.path} className="pg-sim-file-row">
                  <span className="pg-sim-file">{file.path}</span>
                  <span className="pg-muted">{SERIES_COPY.environment}</span>
                </li>
              ))}
            </ul>
          </>
        )}
        <p className="pg-sim-provenance">{SERIES_COPY.provenance}</p>
        <p className="pg-sim-seal">
          {SEAL_WORDS.sealedWhen} <Id value={record.sessionId} copy={false} /> {SEAL_WORDS.ended} ·{" "}
          <Quantity value={record.length} unit="B" /> · sha256 <Id value={record.sha256} />.{" "}
          {SERIES_COPY.checkedOnRead}
        </p>
      </div>
    </details>
  );
}

function Plots({
  record,
  samples,
  source,
}: {
  readonly record: ShownRecord;
  readonly samples: RecordSamples;
  readonly source: Source;
}): ReactNode {
  const plans = useMemo(() => plotsOf(record, samples, source), [record, samples, source]);
  return (
    <div className="pg-sim-plots">
      {plans.map((plan) => (
        <div key={plan.key} className="pg-sim-plot">
          <PlotFrame
            title={plan.title}
            subtitle={plan.subtitle}
            legend={<Legend labels={plan.legend} />}
            summary={plan.summary}
            source={source}
            plot={<Plot spec={plan.spec} />}
            data={<PlotTable spec={plan.spec} />}
          />
          {plan.note !== null && <p className="pg-panel-note">{plan.note}</p>}
        </div>
      ))}
    </div>
  );
}

function Shown({
  record,
  base,
  subtask,
  attempt,
  runId,
  role,
  checks,
  tolerance,
  onShowRow,
  focus,
}: {
  readonly record: ShownRecord;
  readonly base: string;
  readonly subtask: string;
  readonly attempt: number;
  readonly runId: string;
  readonly role: string | null;
  readonly checks: readonly { readonly check: SeriesCheck; readonly row: number }[];
  readonly tolerance: string;
  readonly onShowRow: (row: number) => void;
  readonly focus: boolean;
}) {
  const samples = useJson(recordRoute(base, subtask, attempt, record.recordId), recordSamples);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (focus) heading.current?.focus();
  }, [focus, record.recordId]);
  const source = useMemo<Source>(
    () => ({ id: `run ${runId}`, commit: record.attemptCommit }),
    [runId, record.attemptCommit],
  );
  const result = samples.result;
  if (result !== null && !result.ok) {
    const refused = sealOf(result.refusal);
    return refused === null ? (
      <ErrorState
        title={SERIES_COPY.recordError}
        {...result.refusal}
        route={samples.route}
        onRetry={samples.again}
      />
    ) : (
      <SealRefusal title={refused.title} recordId={record.recordId} seal={refused.seal} />
    );
  }
  return (
    <article className="pg-sim-record" data-source={sourceAttribute(source)}>
      <header className="pg-sim-record-head">
        <h2 className="pg-sim-record-heading" ref={heading} tabIndex={-1}>
          {record.title}
        </h2>
        {role !== null && <p className="pg-muted pg-sim-titled">{titledBy(role)}</p>}
        <p className="pg-sim-ids">
          <Id value={record.recordId} copy={false} />
          <span className="pg-muted">· sealed by session</span>
          <Id value={record.sessionId} copy={false} />
          <SourceChip {...source} />
          <span className="pg-muted">sha256</span>
          <Id value={record.sha256} />
        </p>
      </header>
      {result === null ? (
        <LoadingState reading={SERIES_COPY.readingRecord} />
      ) : (
        <>
          <Plots record={record} samples={result.value} source={source} />
          <ReadOff checks={checks} tolerance={tolerance} onShowRow={onShowRow} />
          <Produced record={record} />
        </>
      )}
    </article>
  );
}

/** The chosen record, or the sentence that stands in its place. */
export function RecordView({
  record,
  base,
  subtask,
  attempt,
  runId,
  role,
  checks,
  tolerance,
  onShowRow,
  focus,
}: {
  readonly record: AttemptRecord;
  readonly base: string;
  readonly subtask: string;
  readonly attempt: number;
  readonly runId: string;
  readonly role: string | null;
  readonly checks: readonly { readonly check: SeriesCheck; readonly row: number }[];
  readonly tolerance: string;
  readonly onShowRow: (row: number) => void;
  readonly focus: boolean;
}) {
  if (record.kind === "unread")
    return (
      <SealRefusal
        title={unreadWords(record.error)}
        recordId={record.recordId ?? "unknown"}
        seal={{
          record: null,
          sealedSha256: null,
          sealedLength: null,
          foundSha256: null,
          foundLength: null,
          reason: record.error,
        }}
      />
    );
  if (record.kind === "refused")
    return (
      <SealRefusal
        title={
          record.refused === "seal"
            ? SERIES_COPY.broken
            : record.refused === "format"
              ? heldWords(record.error)
              : `${record.refused}: ${record.error}`
        }
        recordId={record.recordId}
        seal={{
          record: record.record,
          sealedSha256: record.sealedSha256,
          sealedLength: String(record.sealedLength),
          foundSha256: record.foundSha256,
          foundLength: record.foundLength === null ? null : String(record.foundLength),
          reason: record.error,
        }}
      />
    );
  return (
    <Shown
      key={record.recordId}
      record={record}
      base={base}
      subtask={subtask}
      attempt={attempt}
      runId={runId}
      role={role}
      checks={checks}
      tolerance={tolerance}
      onShowRow={onShowRow}
      focus={focus}
    />
  );
}
