import type { ReactNode } from "react";

import { ActorBadge, type ActorBadgeProps } from "../actor/ActorBadge";

/**
 * One recorded event in a run's timeline. The actor is always shown; an action the collaborator
 * took quotes the request that caused it (its badge requires the quote). Depth 0 is the run,
 * 1 a subtask, 2 an attempt.
 */
export function TimelineRow({
  time,
  actor,
  what,
  meta,
  end,
  depth = 0,
}: {
  /** "14:06" or "+00:04:12", as recorded. */
  readonly time: string;
  readonly actor: ActorBadgeProps;
  readonly what: ReactNode;
  readonly meta?: ReactNode;
  /** A trailing verdict, cost or source. */
  readonly end?: ReactNode;
  readonly depth?: 0 | 1 | 2;
}) {
  const className = [
    "pg-trow",
    actor.kind === "collaborator" ? "pg-trow-collaborator" : null,
    depth > 0 ? `pg-trow-depth-${String(depth)}` : null,
  ]
    .filter((c) => c !== null)
    .join(" ");
  return (
    <div className={className} data-depth={depth}>
      <span className="pg-trow-time">{time}</span>
      <ActorBadge {...actor} size="sm" />
      <span className="pg-trow-main">
        <span className="pg-trow-what">{what}</span>
        {meta !== undefined && <span className="pg-trow-meta">{meta}</span>}
      </span>
      <span className="pg-trow-end">{end}</span>
    </div>
  );
}
