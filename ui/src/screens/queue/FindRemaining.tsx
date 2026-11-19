/**
 * Every part still open, found in one step (ARCH-122): what the command line's "find every
 * remaining part" does, from the page. It sends the one decision the page already sends for a
 * part, Find it, once for each part still open and asked for the first time, one after another in
 * the queue's order, each with the view the page holds of it, through the same route and the
 * same confirmation every decision goes through. A part raised again is left as it is: find does
 * not decide it. The first refusal stops the rest; those recorded before it stay recorded.
 */
import { useState } from "react";

import type { Result } from "../../api/client";
import type { ItemView, Resolved } from "../../api/queue";
import { Button, type Confirmation } from "../../design/components/actions/Button";
import type { Refusal } from "../../design/components/status/States";
import { CONFIRM_TITLE, findAllLines, findAllSummary, PARTS_COPY } from "../../words/parts";
import { whyNot } from "./model";
import { RunStateNote } from "./RunStateNote";

/** A part the find-all would decide: the view the page holds of it, and its label. */
export interface RemainingPart {
  readonly view: ItemView;
  readonly label: string;
}

export function FindRemaining({
  parts,
  runId,
  operator,
  holdsToken,
  send,
  onDone,
}: {
  readonly parts: readonly RemainingPart[];
  readonly runId: string;
  readonly operator: string | null;
  readonly holdsToken: boolean;
  /** The page's decision on one part: Find it, on the view given. */
  readonly send: (view: ItemView) => Promise<Result<Resolved>>;
  /** How many were recorded, of how many, and the refusal that stopped the rest, if one did. */
  readonly onDone: (recorded: number, of: number, refusal: Refusal | null) => void;
}) {
  const [sending, setSending] = useState(false);
  if (parts.length === 0) return null;
  const who = operator ?? "no one";
  const why = whyNot(operator, holdsToken);
  const lines = parts.map(({ view }) =>
    JSON.stringify({
      item_id: view.item.itemId,
      ts: PARTS_COPY.findAllTime,
      kind: "resolution",
      decision: "choose find",
      resolved_by: who,
      verb: "choose",
      position: "find",
      shown_sha256: view.itemSha256,
    }),
  );
  const confirmation: Confirmation = {
    title: parts.length === 1 ? CONFIRM_TITLE.find : PARTS_COPY.findAllTitle,
    summary: findAllSummary(
      who,
      parts.map((p) => p.label),
    ),
    writes: lines.join("\n"),
    check: PARTS_COPY.findAllCheck,
    outcome: PARTS_COPY.findAllOutcome,
    recordedAs: operator === null ? PARTS_COPY.noOperator : `${operator} (human)`,
    confirmLabel: "Record",
    children: (
      <>
        <RunStateNote />
        <p className="pg-dialog-note">
          {findAllLines(parts.length, runId)} {PARTS_COPY.findAllWritten}
        </p>
      </>
    ),
    onConfirm: () => {
      setSending(true);
      void (async () => {
        let recorded = 0;
        for (const { view } of parts) {
          const result = await send(view);
          if (!result.ok) {
            setSending(false);
            onDone(recorded, parts.length, result.refusal);
            return;
          }
          recorded += 1;
        }
        setSending(false);
        onDone(recorded, parts.length, null);
      })();
    },
  };
  return (
    <div className="pg-parts-find-all">
      <p className="pg-panel-note">{PARTS_COPY.findAllLead}</p>
      <div className="pg-parts-actions">
        <Button
          variant="act"
          label={PARTS_COPY.findAllLabel}
          confirm={confirmation}
          disabledBecause={why ?? (sending ? PARTS_COPY.findAllSending : null)}
        />
      </div>
    </div>
  );
}
