import type { ReactNode } from "react";

import { Button } from "../actions/Button";
import { ActorBadge } from "../actor/ActorBadge";
import { Icon } from "../icons/Icon";
import { type StatusKind, StatusTag } from "../status/StatusTag";

export type ChangeState = "proposed" | "queued" | "applied" | "declined" | "refused";

const STATE: Readonly<Record<ChangeState, StatusKind | null>> = {
  proposed: null,
  queued: "queued",
  applied: "applied",
  declined: "declined",
  refused: "refused",
};

/** No route applies or declines a change in this build, so both controls stay disabled. */
const NO_ROUTE = "No route records a change yet.";

/**
 * A change the collaborator proposes: what, in plain words; where (the label, then the key); why;
 * and the request that caused it, quoted. Its states are not verdicts: neutral, never pass or fail.
 * In the library only.
 */
export function ChangeCard({
  state,
  id,
  what,
  label,
  target,
  from,
  to,
  why,
  quote,
  quotedBy,
  reason,
}: {
  readonly state: ChangeState;
  readonly id: string;
  readonly what: string;
  readonly label: string;
  readonly target: string;
  readonly from: ReactNode;
  readonly to: ReactNode;
  readonly why?: string;
  /** The person's request, verbatim. */
  readonly quote: string;
  readonly quotedBy: string;
  /** For a refused change: what blocked it. */
  readonly reason?: string;
}) {
  const tag = STATE[state];
  const note =
    state === "proposed"
      ? "Nothing is written until you apply."
      : state === "queued"
        ? "Lands at the next safe point. Nothing in the design has changed yet."
        : state === "declined"
          ? "Declined. It stays in the record."
          : null;
  return (
    <article className={`pg-change pg-change-${state}`} aria-label={`Change ${id}`}>
      <header className="pg-change-head">
        <ActorBadge kind="collaborator" name={`Change ${id}`} quote={quote} size="sm" />
        {tag === null ? <span className="pg-status">Proposed</span> : <StatusTag status={tag} />}
      </header>
      <div className="pg-change-body">
        <span className="pg-change-what">{what}</span>
        <div className="pg-change-diff">
          <span>{label}</span>
          <span className="pg-old">{from}</span>
          <span className="pg-change-arrow">
            <Icon name="arrow-right" />
          </span>
          <span>{to}</span>
          <span className="pg-id">{target}</span>
        </div>
        {why !== undefined && <p className="pg-change-why">{why}</p>}
        <blockquote className="pg-quote">
          “{quote}”<cite>{quotedBy}</cite>
        </blockquote>
        {state === "refused" && reason !== undefined && <p className="pg-change-why">{reason}</p>}
      </div>
      {note !== null && (
        <footer className="pg-change-foot">
          <span className="pg-change-foot-note">{note}</span>
          {state === "proposed" && (
            <>
              <Button
                variant="reject"
                size="sm"
                label="Decline…"
                disabledBecause={NO_ROUTE}
                confirm={{
                  title: `Decline change ${id}?`,
                  writes: `change ${id} → declined`,
                  recordedAs: quotedBy,
                  confirmLabel: "Decline",
                  onConfirm: () => undefined,
                }}
              />
              <Button
                variant="act"
                size="sm"
                label="Apply…"
                disabledBecause={NO_ROUTE}
                confirm={{
                  title: `Apply change ${id}?`,
                  writes: `change ${id} → applied`,
                  recordedAs: quotedBy,
                  confirmLabel: "Apply",
                  onConfirm: () => undefined,
                }}
              />
            </>
          )}
        </footer>
      )}
    </article>
  );
}
