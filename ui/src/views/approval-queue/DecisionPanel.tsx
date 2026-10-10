/**
 * Approve or reject an open item. The note is optional to approve and required to reject. Each
 * button opens a confirmation naming exactly the line that will be written, its file and its
 * run; only confirming sends it. What the page showed of the item goes with the decision, so the
 * server refuses it if the item changed meanwhile, and its answer is shown as it came.
 */
import { useId, useState } from "react";

import type { Result } from "../../api/client";
import type { ItemView, Resolved, Verb } from "../../api/queue";
import { ActButton } from "../../design/components/Buttons";
import { ErrorState } from "../../design/components/States";
import { lineToWrite, whyNot } from "./model";

export function DecisionPanel({
  view,
  runId,
  operator,
  send,
  onDecided,
}: {
  view: ItemView;
  runId: string;
  operator: string | null;
  send: (verb: Verb, note: string) => Promise<Result<Resolved>>;
  onDecided: () => void;
}) {
  const [note, setNote] = useState("");
  const [answer, setAnswer] = useState<Result<Resolved> | null>(null);
  const noteId = useId();

  const act = (verb: Verb) => {
    const line = operator === null ? null : lineToWrite(view, verb, note, operator);
    return {
      label: verb === "approve" ? "Approve" : "Reject",
      writes: `one line appended to queue_decisions.jsonl in run ${runId}`,
      detail: (
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
        <ActButton
          act={act("approve")}
          glyph="✓"
          disabledBecause={whyNot("approve", note, operator)}
        />
        <ActButton act={act("reject")} reject disabledBecause={whyNot("reject", note, operator)} />
        <span className="muted queue-actions-note">
          Each writes one decision, exactly as <span className="mono">physgate queue resolve</span>{" "}
          would{operator === null ? "" : ","}
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
          <ErrorState title="The decision was refused" refusal={answer.refusal} />
        ))}
    </section>
  );
}
