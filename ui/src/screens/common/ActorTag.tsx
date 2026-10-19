import { ActorBadge } from "../../design/components/actor/ActorBadge";
import type { Actor } from "../../words/actors";

/** An actor as the record names it: a badge in its kind's colour, or, unmapped, as written. */
export function ActorTag({ actor, size }: { readonly actor: Actor; readonly size?: "sm" | "md" }) {
  if (actor.kind === "unmapped")
    return (
      <span className="pg-actor pg-actor-unmapped" data-actor="unmapped">
        <span className="pg-actor-name">{actor.name}</span>
      </span>
    );
  return <ActorBadge {...actor} {...(size === undefined ? {} : { size })} />;
}
