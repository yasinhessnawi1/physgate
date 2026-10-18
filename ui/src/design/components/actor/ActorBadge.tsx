import { Icon, type IconName } from "../icons/Icon";
import { Avatar } from "./Avatar";

interface Common {
  readonly size?: "sm" | "md";
}

/**
 * Who did it. Deterministic (the orchestrator, the gate, the hooks), an agent (its role and its
 * model, both required), the collaborator (the request that caused the action, quoted), or a
 * human (named).
 */
export type ActorBadgeProps = Common &
  (
    | { readonly kind: "deterministic"; readonly name: string }
    | {
        readonly kind: "agent";
        readonly name: string;
        readonly role: string;
        readonly model: string;
      }
    | { readonly kind: "collaborator"; readonly name?: string; readonly quote: string }
    | { readonly kind: "human"; readonly name: string }
  );

export class ActorError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ActorError";
  }
}

const ICON: Readonly<Record<"deterministic" | "agent" | "collaborator", IconName>> = {
  deterministic: "cog",
  agent: "bot",
  collaborator: "messages-square",
};

const blank = (text: unknown): boolean => typeof text !== "string" || text.trim() === "";

export function ActorBadge(props: ActorBadgeProps) {
  const size = props.size === "sm" ? " pg-actor-sm" : "";
  switch (props.kind) {
    case "human":
      if (blank(props.name)) throw new ActorError("a human actor is named");
      return (
        <span className={`pg-actor pg-actor-human${size}`}>
          <Avatar name={props.name} />
          <span className="pg-actor-name">{props.name}</span>
        </span>
      );
    case "agent":
      if (blank(props.name) || blank(props.role) || blank(props.model))
        throw new ActorError("an agent actor names its role and its model");
      return (
        <span className={`pg-actor pg-actor-agent${size}`}>
          <span className="pg-actor-tile">
            <Icon name={ICON.agent} />
          </span>
          <span className="pg-actor-name">{props.name}</span>
          <span className="pg-actor-meta">
            {props.role} · {props.model}
          </span>
        </span>
      );
    case "collaborator":
      if (blank(props.quote))
        throw new ActorError("a collaborator action quotes the request that caused it");
      return (
        <span className={`pg-actor pg-actor-collaborator${size}`}>
          <span className="pg-actor-tile">
            <Icon name={ICON.collaborator} />
          </span>
          <span className="pg-actor-name">{props.name ?? "Collaborator"}</span>
          <q className="pg-actor-quote">{props.quote}</q>
        </span>
      );
    case "deterministic":
      if (blank(props.name)) throw new ActorError("a deterministic actor is named");
      return (
        <span className={`pg-actor pg-actor-deterministic${size}`}>
          <span className="pg-actor-tile">
            <Icon name={ICON.deterministic} />
          </span>
          <span className="pg-actor-name">{props.name}</span>
        </span>
      );
  }
}
