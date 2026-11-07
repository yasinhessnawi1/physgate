/**
 * The harness terms a screen uses, each with one plain sentence. One table: the inline
 * explanations read it, and the Glossary screen lists it, group by group. Written for a
 * first-year mechatronics student: the engineering terms stay, the harness's own words are
 * explained.
 */
import { DECISION_COPY } from "../../../words/queue";

export const GLOSSARY_GROUPS = [
  "The gate and its verdicts",
  "How a run works",
  "The queue",
  "Who did what",
  "Drafts and records",
] as const;
export type GlossaryGroup = (typeof GLOSSARY_GROUPS)[number];

export interface GlossaryEntry {
  readonly term: string;
  readonly means: string;
  readonly group: GlossaryGroup;
}

export const GLOSSARY = {
  gate: {
    term: "Gate",
    means:
      "The physics checks a design must pass before any reviewer sees it: units, power, sizing and the like. It is a deterministic checker, not a model.",
    group: "The gate and its verdicts",
  },
  "gate-on": {
    term: "Gate on",
    means: "The gate checked the work and a failing check stopped it.",
    group: "The gate and its verdicts",
  },
  observe: {
    term: "Observe",
    means:
      "The gate checked this but was not allowed to stop it. A failure here would have stopped the work, but did not.",
    group: "The gate and its verdicts",
  },
  "gate-off": {
    term: "Gate off",
    means: "The gate did not run, so nothing here was checked by it.",
    group: "The gate and its verdicts",
  },
  verdicts: {
    term: "Pass · Fail · Warn",
    means:
      "The only three verdicts. Warn is a check that failed where its failure does not block the attempt. Each is always shown as glyph, word and colour.",
    group: "The gate and its verdicts",
  },
  unchecked: {
    term: "Unchecked",
    means:
      "The check did not run. It is never counted as a pass, and never among the checks that were evaluated.",
    group: "The gate and its verdicts",
  },
  "not-run": {
    term: "Not run",
    means: "A whole stage, such as a review, that did not happen for this attempt.",
    group: "The gate and its verdicts",
  },
  partial: {
    term: "Partial",
    means: "The run is still going, so these figures can still change. Running totals say so far.",
    group: "The gate and its verdicts",
  },
  subtask: {
    term: "Subtask",
    means: "One piece of the design, built by one agent's sessions.",
    group: "How a run works",
  },
  attempt: {
    term: "Attempt",
    means: "One try at a subtask: the agent's work, the gate's checks and the reviews of that try.",
    group: "How a run works",
  },
  repair: {
    term: "Repair",
    means:
      "After a failed check or review the agent gets a further attempt that reads why it failed. The run allows a fixed number of attempts per subtask.",
    group: "How a run works",
  },
  "safe-point": {
    term: "Safe point",
    means:
      "A moment between attempts when the harness can take a change without disturbing work in progress.",
    group: "How a run works",
  },
  merged: {
    term: "Merged",
    means: "An attempt that passed the gate and the review; its values enter the design.",
    group: "How a run works",
  },
  blocked: {
    term: "Blocked",
    means: "Stopped before it could happen, by a rule the harness enforces.",
    group: "How a run works",
  },
  "queue-item": {
    term: "Queue item",
    means: DECISION_COPY.queueItem,
    group: "The queue",
  },
  decision: {
    term: "Approve · Reject",
    means:
      "Your answer to a queue item. It is written as one line in the run's decisions file, under your name; a rejection says why.",
    group: "The queue",
  },
  actor: {
    term: "Actor",
    means:
      "Who did something: the harness itself, an agent (with its model), the collaborator, or a named person.",
    group: "Who did what",
  },
  deterministic: {
    term: "Deterministic",
    means:
      "A step the harness's own code took, such as the orchestrator or the gate: no model was involved.",
    group: "Who did what",
  },
  agent: {
    term: "Agent",
    means:
      "A model working in a role, such as the electrical agent. Its model is shown when the run records it.",
    group: "Who did what",
  },
  verdict: {
    term: "Reviewer verdict",
    means:
      "What a reviewer, running on a different model from the one that did the work, decided about it.",
    group: "Who did what",
  },
  "os-layer": {
    term: "OS layer",
    means:
      "The operating system's own sandbox, which keeps an agent's commands inside the run's folders.",
    group: "Who did what",
  },
  "what-if": {
    term: "What-if",
    means:
      "A value from a draft re-run with a changed parameter. It was never checked, so it has no verdict.",
    group: "Drafts and records",
  },
  sealed: {
    term: "Sealed",
    means: "A record whose digest was taken when it was written, so any later change to it shows.",
    group: "Drafts and records",
  },
  digest: {
    term: "Digest",
    means:
      "A fingerprint of a file's exact bytes. Two files with the same digest are the same file.",
    group: "Drafts and records",
  },
  seed: {
    term: "Seed",
    means:
      "The number a run's random choices start from. Two runs of one brief and seed differ only in what was changed on purpose.",
    group: "Drafts and records",
  },
  manifest: {
    term: "Manifest",
    means:
      "The digest of a run's whole configuration: models, gate mode, limits. Runs with the same manifest were set up the same way.",
    group: "Drafts and records",
  },
  "list-price": {
    term: "List-price estimate",
    means:
      "What the run's tokens would cost at the provider's published prices on a dated price sheet. It is not a bill.",
    group: "Drafts and records",
  },
  // How physgate is set up: the Settings screen's terms.
  engine: {
    term: "Engine",
    means:
      "What the agents' sessions run on: Claude Code with a subscription, or the Claude API with a key. A run's parameters name how its sessions reach it.",
    group: "How a run works",
  },
  "engine-catalogue": {
    term: "Engine catalogue",
    means:
      "The list of engines the desktop app's engine step offers, kept in the checkout. Engines marked Not yet are listed so the choice can be switched on later; nothing runs on them.",
    group: "How a run works",
  },
  "builder-model": {
    term: "Builder model",
    means:
      "The model a role's sessions build the work on, named for each role in the run's parameters.",
    group: "How a run works",
  },
  "reviewer-model": {
    term: "Reviewer model (pairing)",
    means:
      "The model a role's reviewer runs on. It must differ from the model whose work it reviews: the harness refuses to start a reviewer on its builder's model, however the model is spelled.",
    group: "How a run works",
  },
  "plan-reviewer": {
    term: "Plan reviewer",
    means:
      "A reviewer that judges the plan the brief was split into, before anything is dispatched. It runs on a model other than the one that split the brief.",
    group: "How a run works",
  },
  endpoint: {
    term: "Endpoint",
    means:
      "The address the engine's requests go to. Most runs use the engine's own; a run may name another, and records it.",
    group: "How a run works",
  },
  effort: {
    term: "Effort",
    means:
      "How much reasoning each request may spend before it answers, from low to maximum, passed to every session of the run.",
    group: "How a run works",
  },
  "token-ceiling": {
    term: "Token ceiling",
    means:
      "The most a role session may load before it starts work: its standards, its spec and its skill file. It is counted generously, one token for every byte, so a set can be refused while really under it. It is not a budget for the run.",
    group: "How a run works",
  },
  "session-limits": {
    term: "Session limits",
    means:
      "The bounds each session of a run works within: how long it may run, how many turns it may take, how many times the engine's binary may try again, and how long the harness waits before trying a failed start again.",
    group: "How a run works",
  },
  "default-for-new-runs": {
    term: "Default for new runs",
    means:
      "A value a new run would take when its parameters name none. physgate keeps none yet: every run names its own values in its parameters, and records them.",
    group: "Drafts and records",
  },
  "recorded-value": {
    term: "Recorded value",
    means:
      "What a run wrote in its record when it was set up. A run recorded before a field existed did not write it; the harness reads such a run as having run under that field's documented setting, and Settings shows what the harness reads.",
    group: "Drafts and records",
  },
} as const satisfies Record<string, GlossaryEntry>;

export type TermKey = keyof typeof GLOSSARY;
