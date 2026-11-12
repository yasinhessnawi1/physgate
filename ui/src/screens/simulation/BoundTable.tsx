/**
 * What was read off a record, and what the gate said: one row per quantity the attempt's change
 * check held to a record. The gate column shows only what a gate record of the same attempt says
 * about that quantity. Where none says anything, it says so in words, with no glyph and no
 * verdict colour: a pass that names no quantity is not a pass of this one.
 */
import type { GateEntry, SeriesCheck, Unread } from "../../api/series";
import { Id } from "../../design/components/data/Id";
import { Quantity } from "../../design/components/data/Quantity";
import { SourceChip } from "../../design/components/data/SourceChip";
import { type Source, sourceAttribute } from "../../design/components/data/source";
import { Term } from "../../design/components/help/Term";
import { DataTable } from "../../design/components/layout/DataTable";
import { GateOutcome } from "../../design/components/verdict/GateMode";
import type { Verdict } from "../../design/components/verdict/verdict";
import { hrefFor } from "../../shell/route";
import { checkWords } from "../../words/checks";
import { nodeLabel, quantityLabel } from "../../words/humanise";
import {
  agreementWords,
  asSentence,
  extractorWords,
  gateWords,
  SERIES_COPY,
  toleranceWords,
  unreadWords,
} from "../../words/series";
import { nodeAddress } from "../common/addresses";
import { Tag } from "./Tag";

const VERDICTS: readonly string[] = ["pass", "fail", "warn", "unchecked"];
const RUNNING_MODES: readonly string[] = ["on", "observe"];

/** The id of a row's first cell, which "Show its row" moves focus to. */
export function rowAnchor(row: number): string {
  return `sim-check-${String(row)}`;
}

/** One gate record that names the quantity, as the gate wrote it. */
function GateRecord({ entry }: { readonly entry: GateEntry }) {
  const known = VERDICTS.includes(entry.outcome) && RUNNING_MODES.includes(entry.gateMode);
  return (
    <div className="pg-sim-gate">
      {known ? (
        <GateOutcome mode={entry.gateMode as "on" | "observe"} outcome={entry.outcome as Verdict} />
      ) : (
        <Tag icon="circle-dot" kind="as-written">
          {`${entry.outcome} · ${entry.gateMode}`}
        </Tag>
      )}
      <span>{checkWords(entry.name).name}</span>
      {entry.low !== null && entry.high !== null && (
        <span className="pg-bound">
          <Quantity {...entry.low} /> to <Quantity {...entry.high} />
        </span>
      )}
      {entry.expected !== null && <span className="pg-muted">{entry.expected}</span>}
      <Id value={`check ${String(entry.check)} · seq ${String(entry.seq)}`} copy={false} />
    </div>
  );
}

function GateCell({
  gate,
  gateChecks,
}: {
  readonly gate: SeriesCheck["gate"];
  readonly gateChecks: string;
}) {
  if (typeof gate !== "string" && gate.length > 0)
    return (
      <div className="pg-sim-gates">
        {gate.map((entry) => (
          <GateRecord key={`${String(entry.seq)}-${String(entry.check)}`} entry={entry} />
        ))}
      </div>
    );
  const state = typeof gate === "string" ? gate : "not_named";
  return (
    <span className="pg-sim-gate-words">
      <span>{gateWords(state)}</span>
      {(state === "not_named" || state === "unmatched") && (
        <a className="pg-hit" href={gateChecks}>
          {SERIES_COPY.openGateChecks}
        </a>
      )}
    </span>
  );
}

interface Row {
  readonly row: number;
  readonly check: SeriesCheck | Unread;
}

export function BoundTable({
  checks,
  tolerance,
  run,
  graphSource,
  titles,
  notSealed,
}: {
  readonly checks: readonly (SeriesCheck | Unread)[];
  readonly tolerance: string;
  /** The run's ``root/name``, for the links to the design graph and the gate checks. */
  readonly run: string;
  /** Where the design graph's values come from. */
  readonly graphSource: Source;
  /** Each record's title, by id, for the records this attempt sealed and the screen read. */
  readonly titles: ReadonlyMap<string, string>;
  /** The records whose seal the server found broken. */
  readonly notSealed: ReadonlySet<string>;
}) {
  const gateChecks = hrefFor("orchestration", "gate-checks", new URLSearchParams({ run }));
  const rows: Row[] = checks.map((check, row) => ({ row, check }));
  return (
    <section
      className="pg-card pg-panel pg-sim-bound"
      aria-label={SERIES_COPY.tableTitle}
      data-source={sourceAttribute(graphSource)}
    >
      <header className="pg-panel-head">
        <h2 className="pg-panel-title">{SERIES_COPY.tableTitle}</h2>
      </header>
      <p className="pg-panel-note">{SERIES_COPY.aboveTable}</p>
      <p className="pg-panel-note">
        <Term term="agreement">Agreement</Term> is within {toleranceWords(tolerance).full}.
      </p>
      {rows.length === 0 ? (
        <p className="pg-panel-empty">{SERIES_COPY.noChecks}</p>
      ) : (
        <DataTable<Row>
          label={SERIES_COPY.tableTitle}
          rows={rows}
          rowKey={(r) => String(r.row)}
          columns={[
            {
              key: "quantity",
              label: "Quantity",
              wrap: true,
              render: ({ row, check }) =>
                check.kind === "unread" ? (
                  <span id={rowAnchor(row)} tabIndex={-1}>
                    {unreadWords(check.error)}
                  </span>
                ) : (
                  <span className="pg-sim-cell" id={rowAnchor(row)} tabIndex={-1}>
                    <span className="pg-sim-cell-lead">{quantityLabel(check.quantity)}</span>
                    <a className="pg-hit pg-sim-node" href={nodeAddress(run, check.nodeId)}>
                      {nodeLabel(check.nodeId)}
                    </a>
                    <Id value={check.nodeId} copy={false} />
                  </span>
                ),
            },
            {
              key: "read",
              label: "Read off the record",
              wrap: true,
              render: ({ check }) =>
                check.kind === "unread" ? null : (
                  <span className="pg-sim-cell">
                    {check.read === null ? (
                      <span className="pg-muted">{SERIES_COPY.notRead}</span>
                    ) : (
                      <Quantity {...check.read} />
                    )}
                    <span className="pg-muted">{extractorWords(check.extract, check.trace)}</span>
                    {notSealed.has(check.recordId) ? (
                      <Tag icon="ban" kind="not-what-was-sealed">
                        {SERIES_COPY.notWhatWasSealed}
                      </Tag>
                    ) : (
                      <span>
                        {titles.get(check.recordId) ?? "Record"}{" "}
                        <Id value={check.recordId} copy={false} />
                      </span>
                    )}
                  </span>
                ),
            },
            {
              key: "declared",
              label: "In the design graph",
              render: ({ check }) =>
                check.kind === "unread" ? null : (
                  <span className="pg-sim-cell">
                    <Quantity {...check.declared} />
                    <SourceChip {...graphSource} compact />
                  </span>
                ),
            },
            {
              key: "agreement",
              label: "Agreement",
              wrap: true,
              render: ({ check }) =>
                check.kind === "unread" ? null : (
                  <span className="pg-sim-cell">
                    <Tag icon="circle-dot" kind={`agreement-${check.outcome}`}>
                      {agreementWords(check.outcome, tolerance)}
                    </Tag>
                    {check.reason !== null && (
                      <span className="pg-muted">{asSentence(check.reason)}</span>
                    )}
                  </span>
                ),
            },
            {
              key: "gate",
              label: "Gate",
              wrap: true,
              render: ({ check }) =>
                check.kind === "unread" ? null : (
                  <GateCell gate={check.gate} gateChecks={gateChecks} />
                ),
            },
          ]}
        />
      )}
    </section>
  );
}
