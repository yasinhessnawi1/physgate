import type { ReactNode } from "react";

import { ActorBadge, type ActorBadgeProps } from "../actor/ActorBadge";

/** An actor the record maps to a kind, or a writer shown as written, with no actor colour. */
export type TimelineActor = ActorBadgeProps | { readonly kind: "unmapped"; readonly name: string };

/**
 * One recorded event in a run's timeline. The actor is shown whenever the record maps to one; a
 * line that maps to none shows none, never a default. An action the collaborator took quotes the
 * request that caused it (its badge requires the quote). Depth 0 is the run, 1 a subtask, 2 an
 * attempt.
 */
export function TimelineRow({
  time,
  actor,
  what,
  meta,
  end,
  depth = 0,
  selected,
  onSelect,
  kind,
}: {
  /** "14:06" or "+00:04:12", as recorded. */
  readonly time: string;
  /** Who did it, when the record says; a line the record maps to no one carries no actor. */
  readonly actor?: TimelineActor;
  readonly what: ReactNode;
  readonly meta?: ReactNode;
  /** A trailing verdict, cost or source. */
  readonly end?: ReactNode;
  readonly depth?: 0 | 1 | 2;
  /** A row that opens something (an attempt in the inspector) is a button, pressed when shown. */
  readonly selected?: boolean;
  readonly onSelect?: () => void;
  /** What the row's end records, for a reader of the page: a gate outcome, a review. */
  readonly kind?: string;
}) {
  const className = [
    "pg-trow",
    actor?.kind === "collaborator" ? "pg-trow-collaborator" : null,
    depth > 0 ? `pg-trow-depth-${String(depth)}` : null,
  ]
    .filter((c) => c !== null)
    .join(" ");
  const who =
    actor === undefined ? (
      <span className="pg-trow-no-actor" aria-hidden="true" />
    ) : actor.kind === "unmapped" ? (
      <span className="pg-actor pg-actor-unmapped pg-actor-sm" data-actor="unmapped">
        <span className="pg-actor-name">{actor.name}</span>
      </span>
    ) : (
      <ActorBadge {...actor} size="sm" />
    );
  const main = (
    <span className="pg-trow-main">
      <span className="pg-trow-what">{what}</span>
      {meta !== undefined && <span className="pg-trow-meta">{meta}</span>}
    </span>
  );
  return (
    <div
      className={selected === true ? `${className} pg-trow-on` : className}
      data-depth={depth}
      data-kind={kind}
    >
      <span className="pg-trow-time">{time}</span>
      {who}
      {onSelect === undefined ? (
        main
      ) : (
        <button
          type="button"
          className="pg-trow-open pg-hit"
          aria-pressed={selected === true}
          onClick={onSelect}
        >
          {main}
        </button>
      )}
      <span className="pg-trow-end">{end}</span>
    </div>
  );
}
