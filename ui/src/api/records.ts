/**
 * The records the smoke page reads, as the server sends them, with a guard for each that
 * checks the fields the page shows. A field the page does not show is not checked here and
 * not shown.
 */
import type { GateMode } from "../design/components/GateMode";
import type { Verdict } from "../design/components/VerdictBadge";
import type { Quantity } from "../design/quantity";
import { requireQuantity } from "../design/quantity";
import { ShapeError } from "./client";

function object(value: unknown, what: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value))
    throw new ShapeError(what);
  return value as Record<string, unknown>;
}

function text(value: unknown, what: string): string {
  if (typeof value !== "string") throw new ShapeError(what);
  return value;
}

function optionalText(value: unknown, what: string): string | null {
  return value === null || value === undefined ? null : text(value, what);
}

function count(value: unknown, what: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0)
    throw new ShapeError(what);
  return value;
}

function gateMode(value: unknown): GateMode {
  if (value === "on" || value === "observe" || value === "off") return value;
  throw new ShapeError("a gate mode");
}

export interface RunListing {
  readonly root: number;
  readonly name: string;
  readonly runId: string | null;
  readonly manifestId: string | null;
  readonly gateMode: GateMode | null;
  readonly error: string | null;
}

export function runListing(value: unknown): readonly RunListing[] {
  const runs = object(value, "a run list").runs;
  if (!Array.isArray(runs)) throw new ShapeError("a run list");
  return runs.map((raw) => {
    const run = object(raw, "a run");
    const failed = run.error !== undefined;
    return {
      root: count(run.root, "a root position"),
      name: text(run.name, "a run name"),
      runId: failed ? null : text(run.run_id, "a run id"),
      manifestId: failed ? null : text(run.manifest_id, "a manifest id"),
      gateMode: failed ? null : gateMode(run.gate_mode),
      error: failed ? text(run.error, "a refusal") : null,
    };
  });
}

export interface RunConfig {
  readonly manifestId: string;
  readonly runId: string;
  readonly gateMode: GateMode;
  readonly harnessCommit: string | null;
  readonly auth: string;
}

export function runConfig(value: unknown): RunConfig {
  const answer = object(value, "a run configuration");
  const config = object(answer.config, "a run configuration");
  const harness = object(config.harness, "the harness record");
  return {
    manifestId: text(answer.manifest_id, "a manifest id"),
    runId: text(config.run_id, "a run id"),
    gateMode: gateMode(config.gate_mode),
    harnessCommit: optionalText(harness.commit, "a commit"),
    auth: text(config.auth, "an auth mode"),
  };
}

function outcome(value: unknown): Verdict {
  if (value === "pass" || value === "fail" || value === "warn" || value === "unchecked")
    return value;
  throw new ShapeError("a check outcome");
}

function ledgerResult(value: unknown): Verdict | "skipped" | null {
  if (value === null) return null;
  if (value === "pass" || value === "fail" || value === "skipped") return value;
  throw new ShapeError("a ledger result");
}

export interface LedgerLine {
  readonly id: string;
  readonly role: string;
  readonly attempts: number;
  readonly gate: Verdict | "skipped" | null;
  readonly review: Verdict | "skipped" | null;
  readonly mergeCommit: string | null;
}

export function ledgerLine(value: unknown): LedgerLine {
  const line = object(value, "a ledger line");
  return {
    id: text(line.id, "a subtask id"),
    role: text(line.assigned_role, "a role"),
    attempts: count(line.attempt_count, "an attempt count"),
    gate: ledgerResult(line.gate_result),
    review: ledgerResult(line.review_result),
    mergeCommit: optionalText(line.merge_commit, "a commit"),
  };
}

export interface GateEventLine {
  readonly seq: number;
  readonly subtask: string;
  readonly check: string;
  readonly scope: string;
  readonly mode: GateMode;
  readonly outcome: Verdict;
  readonly value: Quantity | null;
  readonly node: string | null;
  readonly reviewerHadPassed: boolean | null;
}

export function gateEventLine(value: unknown): GateEventLine {
  const line = object(value, "a gate event");
  const passed = line.reviewer_had_passed;
  if (passed !== null && typeof passed !== "boolean") throw new ShapeError("a reviewer verdict");
  return {
    seq: count(line.seq, "a sequence number"),
    subtask: text(line.subtask_id, "a subtask id"),
    check: text(line.name, "a check name"),
    scope: text(line.scope, "a scope"),
    mode: gateMode(line.gate_mode),
    outcome: outcome(line.outcome),
    value: line.value === null ? null : requireQuantity(line.value),
    node: optionalText(line.node, "a node id"),
    reviewerHadPassed: passed,
  };
}

export interface GraphRecord {
  readonly headRevision: number;
  readonly nodes: readonly {
    readonly id: string;
    readonly kind: string;
    readonly domain: string;
    readonly revision: number;
    readonly constrains: readonly string[];
    readonly quantities: readonly (readonly [string, Quantity])[];
  }[];
}

export function graphRecord(value: unknown): GraphRecord {
  const graph = object(value, "a graph");
  const nodes = object(graph.nodes, "the graph's nodes");
  return {
    headRevision: count(graph.head_revision, "a revision"),
    nodes: Object.entries(nodes).map(([id, raw]) => {
      const entry = object(raw, "a graph entry");
      const node = object(entry.node, "a node");
      const constrains = node.constrains;
      if (!Array.isArray(constrains)) throw new ShapeError("a node's edges");
      return {
        id,
        kind: text(node.kind, "a node kind"),
        domain: text(node.domain, "a node domain"),
        revision: count(entry.revision, "a revision"),
        constrains: constrains.map((c) => text(c, "an edge target")),
        quantities: Object.entries(object(node.quantities, "a node's quantities")).map(
          ([name, q]): readonly [string, Quantity] => [name, requireQuantity(q)],
        ),
      };
    }),
  };
}

export interface CostRecord {
  readonly usd: Quantity;
  readonly nok: Quantity;
  readonly basis: string;
  readonly pricesDate: string;
  readonly partial: boolean;
}

export function costRecord(value: unknown): CostRecord {
  const line = object(value, "a cost line");
  const partial = line.partial;
  if (typeof partial !== "boolean") throw new ShapeError("a partial flag");
  return {
    usd: requireQuantity({ value: text(line.usd, "an exact amount"), unit: "USD" }),
    nok: requireQuantity({ value: text(line.nok, "an exact amount"), unit: "NOK" }),
    basis: text(line.basis, "a cost basis"),
    pricesDate: text(line.prices_date, "a price sheet date"),
    partial,
  };
}

export function priceDates(value: unknown): readonly string[] {
  const prices = object(value, "a list of price sheets").prices;
  if (!Array.isArray(prices)) throw new ShapeError("a list of price sheets");
  return prices.map((date) => text(date, "a price sheet date"));
}

export interface SealedSession {
  readonly sessionId: string;
  readonly subtask: string;
  readonly attempt: number;
  readonly length: Quantity;
}

/** The sessions whose trajectory the run sealed, from its event log. */
export function sealedSessions(events: readonly unknown[]): readonly SealedSession[] {
  const found: SealedSession[] = [];
  for (const raw of events) {
    const event = object(raw, "an event");
    if (
      event.kind !== "session_ended" ||
      event.trajectory_seal === null ||
      event.trajectory_seal === undefined
    )
      continue;
    const seal = object(event.trajectory_seal, "a seal");
    found.push({
      sessionId: text(event.session_id, "a session id"),
      subtask: text(event.subtask_id, "a subtask id"),
      attempt: count(event.attempt, "an attempt"),
      length: requireQuantity({ value: count(seal.length, "a length"), unit: "B" }),
    });
  }
  return found;
}

/** An event line, kept whole: the page only reads it to find sealed sessions and to count. */
export function anyEvent(value: unknown): unknown {
  return object(value, "an event");
}
