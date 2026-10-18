import type { ReactNode } from "react";

import { ActorBadge } from "../actor/ActorBadge";
import { Icon } from "../icons/Icon";

/**
 * A message in the collaborator's panel: the collaborator's question or reply, or a person's
 * answer. Proposals, applied and refused changes are change cards, not messages. In the library
 * only.
 */
export function ChatMessage({
  from,
  question = false,
  author,
  time,
  attachment,
  children,
}: {
  readonly from: "collaborator" | "human";
  readonly question?: boolean;
  /** A person's name; the collaborator is always "Collaborator". */
  readonly author: string;
  readonly time?: string;
  /** What the message carries, for example a check and the run it belongs to. */
  readonly attachment?: string;
  readonly children: ReactNode;
}) {
  const className = [
    "pg-msg",
    from === "human" ? "pg-msg-human" : null,
    question ? "pg-msg-question" : null,
  ]
    .filter((c) => c !== null)
    .join(" ");
  return (
    <div className={className}>
      <div className="pg-msg-head">
        {from === "human" ? (
          <ActorBadge kind="human" name={author} size="sm" />
        ) : (
          <span className="pg-actor pg-actor-collaborator pg-actor-sm">
            <span className="pg-actor-tile">
              <Icon name="messages-square" />
            </span>
            <span className="pg-actor-name">Collaborator</span>
          </span>
        )}
        {question && <span className="pg-status">Question</span>}
        {time !== undefined && <span className="pg-msg-time">{time}</span>}
      </div>
      {attachment !== undefined && (
        <span className="pg-msg-attach">
          <Icon name="paperclip" />
          {attachment}
        </span>
      )}
      <div className="pg-msg-body">{children}</div>
    </div>
  );
}
