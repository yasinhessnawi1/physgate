/**
 * The task ledger as a person reads it: one row per subtask, in plan order, saying where it
 * stands, how many of its attempts it used, and what the gate and the review said of the latest
 * attempt. Each row opens its history, every ledger line of that subtask as written.
 */
import { Fragment, useState } from "react";

import { Button } from "../../design/components/actions/Button";
import { Id } from "../../design/components/data/Id";
import { Term } from "../../design/components/help/Term";
import { GateOutcome, type GateMode } from "../../design/components/verdict/GateMode";
import { VerdictBadge } from "../../design/components/verdict/VerdictBadge";
import type { LedgerLine } from "../../api/records";
import { hrefFor } from "../../shell/route";
import {
  attemptsWords,
  type StageResult,
  stateWords,
  type SubtaskRow,
  subtaskLabel,
} from "./ledgerRows";

/** Why a review reached no verdict, for the causes whose words are plain; others as written. */
const NO_VERDICT_CAUSES: Readonly<Record<string, string>> = {
  invalid_verdict: "its answer was not a valid verdict",
  no_verdict: "the reviewer gave none",
  infrastructure: "the reviewer's session failed",
  context_exceeded: "the reviewer ran out of context",
  blocking_spec_defect: "the specification lacks an input",
};

function recorded(mode: GateMode, result: LedgerLine["gate"], gate: boolean) {
  if (result === null) return <span className="pg-muted">none recorded</span>;
  if (result === "skipped")
    return <span className="pg-muted">{gate ? "skipped · gate off" : "skipped"}</span>;
  return gate ? <GateOutcome mode={mode} outcome={result} /> : <VerdictBadge verdict={result} />;
}

function Stage({
  result,
  mode,
  gate,
}: {
  readonly result: StageResult;
  readonly mode: GateMode;
  readonly gate: boolean;
}) {
  switch (result.kind) {
    case "recorded":
      return recorded(mode, result.result, gate);
    case "no-verdict":
      return (
        <span className="pg-muted">
          no verdict: {NO_VERDICT_CAUSES[result.cause] ?? result.cause.replaceAll("_", " ")}
        </span>
      );
    case "not-yet":
      return <span className="pg-muted">not yet</span>;
    case "not-run":
      return (
        <span className="pg-muted">
          <Term term="not-run">not run</Term>
        </span>
      );
    case "no-attempt":
      return <span className="pg-muted">no attempt yet</span>;
  }
}

function Standing({ row, run }: { readonly row: SubtaskRow; readonly run: string }) {
  const words = stateWords(row.state);
  const state = row.state;
  if (state.kind === "waiting" || state.kind === "sent" || state.kind === "decided")
    return (
      <span className="pg-ledger-state">
        <span>{words}</span>
        <a
          className="pg-hit"
          href={hrefFor(
            "collaboration",
            "approval-queue",
            new URLSearchParams({ run, item: state.itemId }),
          )}
        >
          Open the queue item
        </a>
      </span>
    );
  return <span className={state.kind === "merged" ? undefined : "pg-muted"}>{words}</span>;
}

function History({ row, mode }: { readonly row: SubtaskRow; readonly mode: GateMode }) {
  return (
    <div className="pg-table-wrap">
      <table className="pg-table pg-ledger-history" aria-label={`History of ${subtaskLabel(row)}`}>
        <thead>
          <tr>
            <th scope="col">Ledger line</th>
            <th scope="col">Attempts</th>
            <th scope="col">Gate</th>
            <th scope="col">Review</th>
            <th scope="col">Merge commit</th>
          </tr>
        </thead>
        <tbody>
          {row.history.map(({ position, line }) => (
            <tr key={position}>
              <td className="pg-count">{position}</td>
              <td className="pg-count">{line.attempts}</td>
              <td>{recorded(mode, line.gate, true)}</td>
              <td>{recorded(mode, line.review, false)}</td>
              <td>
                {line.mergeCommit === null ? (
                  <span className="pg-muted">none</span>
                ) : (
                  <Id value={line.mergeCommit.slice(0, 7)} copy={false} />
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const COLUMNS = 7;

/**
 * The folded ledger. ``run`` is the run's key, for the queue item's link; ``lines`` the number
 * of ledger lines the rows were folded from.
 */
export function LedgerTable({
  rows,
  lines,
  mode,
  run,
}: {
  readonly rows: readonly SubtaskRow[];
  readonly lines: number;
  readonly mode: GateMode;
  readonly run: string;
}) {
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const toggle = (id: string) => {
    setOpen((was) => {
      const next = new Set(was);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  };
  return (
    <>
      <p className="pg-panel-note">
        View: one row per <Term term="subtask">subtask</Term>, in the order the run planned them,
        folded from {lines} ledger lines. Gate and review are the latest{" "}
        <Term term="attempt">attempt</Term>'s; each row's history shows every line.
      </p>
      <div className="pg-table-wrap" role="region" aria-label="Task ledger table" tabIndex={0}>
        <table className="pg-table" aria-label="Task ledger">
          <thead>
            <tr>
              <th scope="col">Subtask</th>
              <th scope="col">Where it stands</th>
              <th scope="col">Attempts used</th>
              <th scope="col">Gate</th>
              <th scope="col">Review</th>
              <th scope="col">Merge commit</th>
              <th scope="col">
                <span className="pg-visually-hidden">History</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const shown = open.has(row.id);
              const label = subtaskLabel(row);
              return (
                <Fragment key={row.id}>
                  <tr data-subtask={row.id}>
                    <td>
                      <span className="pg-ledger-name">
                        <span>{label}</span>
                        <span className="pg-ledger-sub">
                          Subtask {row.position} of {row.of} · {row.role} agent{" "}
                          <Id value={row.id} copy={false} />
                        </span>
                      </span>
                    </td>
                    <td>
                      <Standing row={row} run={run} />
                    </td>
                    <td className="pg-count">{attemptsWords(row)}</td>
                    <td>
                      <Stage result={row.gate} mode={mode} gate />
                    </td>
                    <td>
                      <Stage result={row.review} mode={mode} gate={false} />
                    </td>
                    <td>
                      {row.mergeCommit === null ? (
                        <span className="pg-muted">none</span>
                      ) : (
                        <Id value={row.mergeCommit.slice(0, 7)} copy={false} />
                      )}
                    </td>
                    <td>
                      <Button
                        size="sm"
                        expanded={shown}
                        onClick={() => {
                          toggle(row.id);
                        }}
                      >
                        {shown ? "Hide history" : `History · ${String(row.history.length)}`}
                        <span className="pg-visually-hidden"> of {label}</span>
                      </Button>
                    </td>
                  </tr>
                  {shown && (
                    <tr className="pg-ledger-history-row">
                      <td colSpan={COLUMNS}>
                        <History row={row} mode={mode} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
