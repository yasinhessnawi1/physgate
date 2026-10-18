/**
 * Approve or reject an open item. Each button opens a confirmation that says first, in one
 * sentence, what is recorded and by whom; then the exact line the queue writes, echoing the note
 * as it is typed; what the server checks first and does not write; and what follows, which is
 * nothing else in the run. Only a rejection needs a reason. What the page showed of the item goes
 * with the decision, so the server refuses it if the item changed meanwhile.
 */
import { useMemo, useState } from "react";

import type { Result } from "../../api/client";
import type { ItemView, Resolved, Verb } from "../../api/queue";
import { Button, type Confirmation } from "../../design/components/actions/Button";
import { ErrorState } from "../../design/components/status/States";
import { usePaletteEntries } from "../../shell/palette";
import { DECISION_COPY, decisionSummary } from "../../words/queue";
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
  readonly send: (verb: Verb, note: string) => Promise<Result<Resolved>>;
  readonly onDecided: () => void;
}) {
  const [answer, setAnswer] = useState<Result<Resolved> | null>(null);
  // The buttons and the command palette open the same confirmation, under the same rules.
  const [opened, setOpened] = useState<Verb | null>(null);
  const why = whyNot(operator, holdsToken);
  const entries = useMemo(
    () => [
      {
        id: "queue-approve",
        section: "This item",
        label: "Approve…",
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
    [why],
  );
  usePaletteEntries(entries);

  const confirmation = (verb: Verb): Confirmation => {
    const who = operator ?? "no one";
    return {
      title: verb === "approve" ? "Approve this item?" : "Reject this item?",
      summary: (note) => decisionSummary(who, verb, view.item.decisionRequired, note),
      writes: (note) => lineToWrite(view, verb, note, who) ?? "nothing until the reason is written",
      check:
        `that the item is still the one shown (its digest ${view.itemSha256}) and that each of ` +
        `its ${String(view.trajectories.length)} transcripts is still as sealed`,
      outcome: DECISION_COPY.then,
      recordedAs: operator === null ? "no operator: this page names none" : `${operator} (human)`,
      confirmLabel: verb === "approve" ? "Approve" : "Reject",
      ...(verb === "reject" ? { needsReason: true } : { takesNote: true }),
      children: (
        <p className="pg-dialog-note">
          One line appended to queue_decisions.jsonl in run {runId}. This cannot be edited or
          undone; the item closes. The time is stamped when it is written.
        </p>
      ),
      onConfirm: (note) => {
        setAnswer(null);
        void send(verb, note).then((result) => {
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
          label="Approve…"
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
