/**
 * The harness terms a screen uses, each with one plain sentence. One table: the inline
 * explanations read it, and the glossary screen will list it. Written for a first-year
 * mechatronics student: the engineering terms stay, the harness's own words are explained.
 */
export const GLOSSARY = {
  gate: {
    term: "Gate",
    means:
      "The physics checks a design must pass before any reviewer sees it: units, power, sizing and the like.",
  },
  "gate-on": {
    term: "Gate on",
    means: "The gate checked the work and a failing check stopped it.",
  },
  observe: {
    term: "Observe",
    means:
      "The gate checked this but was not allowed to stop it. A failure here would have stopped the work, but did not.",
  },
  "gate-off": {
    term: "Gate off",
    means: "The gate did not run, so nothing here was checked by it.",
  },
  attempt: {
    term: "Attempt",
    means: "One try at a subtask: the agent's work, the gate's checks and the reviews of that try.",
  },
  verdict: {
    term: "Reviewer verdict",
    means:
      "What a reviewer, running on a different model from the one that did the work, decided about it.",
  },
  unchecked: {
    term: "Unchecked",
    means:
      "The check did not run. It is never counted as a pass, and never among the checks that were evaluated.",
  },
  blocked: {
    term: "Blocked",
    means: "Stopped before it could happen, by a rule the harness enforces.",
  },
  "what-if": {
    term: "What-if",
    means:
      "A value from a draft re-run with a changed parameter. It was never checked, so it has no verdict.",
  },
  partial: {
    term: "Partial",
    means: "The run is still going, so these figures can still change. Running totals say so far.",
  },
  sealed: {
    term: "Sealed",
    means: "A record whose digest was taken when it was written, so any later change to it shows.",
  },
  "safe-point": {
    term: "Safe point",
    means:
      "A moment between attempts when the harness can take a change without disturbing work in progress.",
  },
  actor: {
    term: "Actor",
    means:
      "Who did something: the harness itself, an agent (with its model), the collaborator, or a named person.",
  },
  "os-layer": {
    term: "OS layer",
    means:
      "The operating system's own sandbox, which keeps an agent's commands inside the run's folders.",
  },
} as const;

export type TermKey = keyof typeof GLOSSARY;
