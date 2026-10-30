/**
 * Approve or reject an open item, or, on an arbitration item, choose one of its two positions. Each button opens a confirmation that says first, in one
 * sentence, what is recorded and by whom; then the exact line the queue writes, echoing the note
 * as it is typed; what the server checks first and does not write; and what follows: what the
 * item says the verb will do where the run acts on decisions, and otherwise nothing else in it. Only a rejection needs a reason. What the page showed of the item goes
 * with the decision, so the server refuses it if the item changed meanwhile.
 */
import { useMemo, useState } from "react";

import type { Result } from "../../api/client";
import { type ItemView, POSITIONS, type Position, type Resolved, type Verb } from "../../api/queue";
import { Button, type Confirmation } from "../../design/components/actions/Button";
import { ErrorState } from "../../design/components/status/States";
import { usePaletteEntries } from "../../shell/palette";
import {
  APPROVE_RECORDS_ONLY,
  CHOOSE_WORDS,
  consequenceWords,
  DECISION_COPY,
  decisionSummary,
  POSITION_WORDS,
} from "../../words/queue";
import { lineToWrite, whyNot } from "./model";

export function Decide({
  view,
  runId,
  operator,
  holdsToken,
  send,
  onDecided,
}: {
  readonly view: ItemView;
  readonly runId: string;
  readonly operator: string | null;
  /** Whether this page holds the action token; without it, it can only read. */
  readonly holdsToken: boolean;
  readonly send: (verb: Verb, note: string, position?: Position) => Promise<Result<Resolved>>;
  readonly onDecided: () => void;
}) {
  const [answer, setAnswer] = useState<Result<Resolved> | null>(null);
  // The buttons and the command palette open the same confirmation, under the same rules.
  const [opened, setOpened] = useState<Verb | Position | null>(null);
  const why = whyNot(operator, holdsToken);
  // A primitive, so the palette's entries are recomputed exactly when the label changes.
  const recordsOnly = view.item.consequence?.onApprove === "record_only";
  const entries = useMemo(
    () => [
      {
        id: "queue-approve",
        section: "This item",
        label: recordsOnly ? APPROVE_RECORDS_ONLY : "Approve…",
        disabledBecause: why,
        run: () => {
          setOpened("approve");
        },
      },
      {
        id: "queue-reject",
        section: "This item",
        label: "Reject…",
        disabledBecause: why,
        run: () => {
          setOpened("reject");
        },
      },
    ],
    [why, recordsOnly],
  );
  usePaletteEntries(entries);

  const choices = view.item.consequence === null ? null : consequenceWords(view.item.consequence);
  const approveLabel = choices?.approveLabel ?? "Approve…";
  const confirmation = (verb: Verb, position?: Position): Confirmation => {
    const who = operator ?? "no one";
    const chosen = position === undefined ? undefined : view.item.consequence?.onChoose?.[position];
    return {
      title:
        position !== undefined
          ? `Choose ${POSITION_WORDS[position].toLowerCase()}?`
          : verb === "approve"
            ? "Approve this item?"
            : "Reject this item?",
      summary: (note) => decisionSummary(who, verb, view.item.decisionRequired, note, position),
      writes: (note) =>
        lineToWrite(view, verb, note, who, position) ?? "nothing until the reason is written",
      check:
        `that the item is still the one shown (its digest ${view.itemSha256}) and that each of ` +
        `its ${String(view.trajectories.length)} transcripts is still as sealed`,
      // What follows: the item's own consequence where the run acts on decisions, else nothing.
      outcome:
        position !== undefined
          ? chosen === undefined
            ? DECISION_COPY.then
            : CHOOSE_WORDS[chosen]
          : choices === null
            ? DECISION_COPY.then
            : verb === "approve"
              ? choices.approve
              : choices.reject,
      recordedAs: operator === null ? "no operator: this page names none" : `${operator} (human)`,
      confirmLabel: verb === "approve" ? "Approve" : verb === "reject" ? "Reject" : "Choose",
      ...(verb === "reject" ? { needsReason: true } : { takesNote: true }),
      children: (
        <p className="pg-dialog-note">
          One line appended to queue_decisions.jsonl in run {runId}. This cannot be edited or
          undone; the item closes. The time is stamped when it is written.
        </p>
      ),
      onConfirm: (note) => {
        setAnswer(null);
        // A position goes with a choice alone: approve and reject are sent as they always were.
        const sent = position === undefined ? send(verb, note) : send(verb, note, position);
        void sent.then((result) => {
          setAnswer(result);
          if (result.ok) onDecided();
        });
      },
    };
  };

  return (
    <section className="pg-queue-decide" aria-label="Decide">
      <div className="pg-queue-actions">
        <Button
          variant="act"
          label={approveLabel}
          confirm={confirmation("approve")}
          disabledBecause={why}
          open={opened === "approve"}
          onOpenChange={(open) => {
            setOpened(open ? "approve" : null);
          }}
        />
        <Button
          variant="reject"
          label="Reject…"
          confirm={confirmation("reject")}
          disabledBecause={why}
          open={opened === "reject"}
          onOpenChange={(open) => {
            setOpened(open ? "reject" : null);
          }}
        />
        {view.item.source === "arbitration" &&
          POSITIONS.map((position) => (
            <Button
              key={position}
              variant="act"
              label={`Choose ${POSITION_WORDS[position].toLowerCase()}…`}
              confirm={confirmation("choose", position)}
              disabledBecause={why}
              open={opened === position}
              onOpenChange={(open) => {
                setOpened(open ? position : null);
              }}
            />
          ))}
      </div>
      {why !== null && <p className="pg-queue-why-not">{why}</p>}
      <p className="pg-panel-note">
        {DECISION_COPY.reasonRule} {DECISION_COPY.setAside}
      </p>
      {answer !== null &&
        (answer.ok ? (
          <p className="pg-queue-recorded" role="status">
            Recorded: <span className="mono">{answer.value.decision}</span> by{" "}
            <span className="mono">{answer.value.resolvedBy}</span> at{" "}
            <span className="mono">{answer.value.ts}</span>
          </p>
        ) : (
          <ErrorState title="The decision was refused" {...answer.refusal} />
        ))}
    </section>
  );
}
