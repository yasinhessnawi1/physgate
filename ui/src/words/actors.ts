/**
 * Who did something, read from the record and nothing else.
 *
 * The harness's own steps are deterministic: the orchestrator, the gate. An agent is named by its
 * role, and shown with its model only when the run records which model that role ran on. A writer
 * the record names that maps to none of these is shown as written, with no actor colour: it is
 * never assigned a kind it may not have.
 */
import type { RunEvent } from "../api/events";
import type { ActorBadgeProps } from "../design/components/actor/ActorBadge";

/** An actor the record maps to a kind, or one shown as written. */
export type Actor = ActorBadgeProps | { readonly kind: "unmapped"; readonly name: string };

/** What a run records about its agents' models. */
export interface Models {
  readonly roleModels: Readonly<Record<string, string>>;
  readonly decompositionModel: string | null;
  readonly reviewerModels: Readonly<Record<string, string>>;
}

export const ORCHESTRATOR: Actor = { kind: "deterministic", name: "Orchestrator" };
export const GATE: Actor = { kind: "deterministic", name: "Gate" };

function capital(text: string): string {
  return `${(text[0] ?? "").toUpperCase()}${text.slice(1)}`;
}

/** An agent of ``role``, with the model the run recorded for it; without one, as written. */
export function agentOf(role: string, model: string | null | undefined): Actor {
  const name = `${capital(role)} agent`;
  if (model === null || model === undefined || model.trim() === "")
    return { kind: "unmapped", name };
  return { kind: "agent", name, role, model };
}

/**
 * A quantity's or a node's writer as recorded: a role the run names a model for, the
 * decomposition, or something else, which is shown as written.
 */
export function writerActor(writtenBy: string | null, models: Models | null): Actor | null {
  if (writtenBy === null) return null;
  if (writtenBy === "decomposition")
    return models?.decompositionModel === null || models === null
      ? { kind: "unmapped", name: writtenBy }
      : {
          kind: "agent",
          name: "Decomposition agent",
          role: "decomposition",
          model: models.decompositionModel,
        };
  const model = models?.roleModels[writtenBy];
  return model === undefined ? { kind: "unmapped", name: writtenBy } : agentOf(writtenBy, model);
}

/**
 * Who wrote an event line: by its kind, and for an agent's line, by its role and model. Every
 * kind is listed; a kind this table does not list gets no actor, never a default one, and a kind
 * the log gains turns this into a type error until it is placed.
 */
export function eventActor(
  event: RunEvent,
  roles: Readonly<Record<string, string>>,
  models: Models,
): Actor | null {
  switch (event.kind) {
    case "run_started":
    case "subtask_planned":
    case "attempt_rejected":
    case "escalated":
    case "merged":
    case "stage_entered":
    case "integration_gate_skipped":
      return ORCHESTRATOR;
    case "decomposed":
      return {
        kind: "agent",
        name: "Decomposition agent",
        role: "decomposition",
        model: event.model,
      };
    case "session_ended": {
      const role = roles[event.subtask];
      return role === undefined
        ? { kind: "unmapped", name: "a session" }
        : agentOf(role, models.roleModels[role]);
    }
    case "review_ran": {
      const role = roles[event.subtask];
      const name = role === undefined ? "Reviewer" : `${capital(role)} reviewer`;
      return event.reviewerModel === null
        ? { kind: "unmapped", name }
        : { kind: "agent", name, role: "reviewer", model: event.reviewerModel };
    }
    case "gate_ran":
    case "gate_skipped":
    case "integration_gate_ran":
      return GATE;
    case "review_unavailable":
    case "other":
      return null;
  }
}
