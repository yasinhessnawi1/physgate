/**
 * Approve or reject an open item. The note is optional to approve and required to reject. Each
 * button opens a confirmation naming exactly the line that will be written, its file and its
 * run; only confirming sends it. What the page showed of the item goes with the decision, so the
 * server refuses it if the item changed meanwhile, and its answer is shown as it came.
 */
import { useId, useMemo, useState } from "react";

import type { Result } from "../../api/client";
import type { ItemView, Resolved, Verb } from "../../api/queue";
import { Button, type Confirmation } from "../../design/components/actions/Button";
import { ErrorState } from "../../design/components/status/States";
import { usePaletteEntries } from "../../shell/palette";
import { lineToWrite, whyNot } from "./model";

export function DecisionPanel({
  view,
  runId,
  operator,
  holdsToken,
  send,
  onDecided,
}: {
  view: ItemView;
  runId: string;
  operator: string | null;
  /** Whether this page holds the action token; without it, it can only read. */
  holdsToken: boolean;
  send: (verb: Verb, note: string) => Promise<Result<Resolved>>;
  onDecided: () => void;
}) {
  const [note, setNote] = useState("");
  const [answer, setAnswer] = useState<Result<Resolved> | null>(null);
  // The buttons and the command palette open the same confirmation, under the same rules.
  const [opened, setOpened] = useState<Verb | null>(null);
  const approveWhyNot = whyNot("approve", note, operator, holdsToken);
  const rejectWhyNot = whyNot("reject", note, operator, holdsToken);
  const entries = useMemo(
    () => [
      {
        id: "queue-approve",
        section: "This item",
        label: "Approve…",
        disabledBecause: approveWhyNot,
        run: () => {
          setOpened("approve");
        },
      },
      {
        id: "queue-reject",
        section: "This item",
        label: "Reject…",
        disabledBecause: rejectWhyNot,
        run: () => {
          setOpened("reject");
        },
      },
    ],
    [approveWhyNot, rejectWhyNot],
  );
  usePaletteEntries(entries);
  const noteId = useId();

  const confirmation = (verb: Verb): Confirmation => {
    const line = operator === null ? null : lineToWrite(view, verb, note, operator);
    const label = verb === "approve" ? "Approve" : "Reject";
    return {
      title: `${label}?`,
      writes: `one line appended to queue_decisions.jsonl in run ${runId}`,
      recordedAs: operator === null ? "no operator: this page names none" : `${operator} (human)`,
      confirmLabel: label,
      children: (
        <>
          <pre className="confirm-line" aria-label="The line that will be written">
            {line ?? ""}
          </pre>
          <p className="confirm-note">
            This cannot be edited or undone; the item closes. The time is stamped when it is
            written.
          </p>
        </>
      ),
      onConfirm: () => {
        setAnswer(null);
        void send(verb, note).then((result) => {
          setAnswer(result);
          if (result.ok) onDecided();
        });
      },
    };
  };

  return (
    <section className="queue-section queue-decide" aria-label="Decide">
      <label className="label" htmlFor={noteId}>
        Note for the ledger (optional to approve, required to reject)
      </label>
      <textarea
        id={noteId}
        className="queue-note"
        value={note}
        maxLength={4000}
        onChange={(event) => {
          setNote(event.target.value);
        }}
      />
      <div className="queue-actions">
        <Button
          variant="act"
          label="Approve…"
          confirm={confirmation("approve")}
          disabledBecause={approveWhyNot}
          open={opened === "approve"}
          onOpenChange={(open) => {
            setOpened(open ? "approve" : null);
          }}
        />
        <Button
          variant="reject"
          label="Reject…"
          confirm={confirmation("reject")}
          disabledBecause={rejectWhyNot}
          open={opened === "reject"}
          onOpenChange={(open) => {
            setOpened(open ? "reject" : null);
          }}
        />
        <span className="muted queue-actions-note">
          Each writes one decision to this run's queue{operator === null ? "" : ","}
          {operator === null ? (
            "."
          ) : (
            <>
              {" "}
              recorded as <span className="mono">{operator}</span>.
            </>
          )}
        </span>
      </div>
      {answer !== null &&
        (answer.ok ? (
          <p className="queue-recorded" role="status">
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
