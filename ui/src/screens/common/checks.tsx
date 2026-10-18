/**
 * A gate check as a person reads it: the check's name in words with what it looked at, its
 * outcome in the mode it ran in, what it measured against its bound, and, where it did not pass,
 * the gate's own message. Nothing here explains a check beyond its record.
 */
import type { GateCheck } from "../../api/run";
import { Quantity } from "../../design/components/data/Quantity";
import { checkWords } from "../../words/checks";
import { nodeLabel, quantityLabel } from "../../words/humanise";

/** The gate's message as a sentence: its first letter raised, its words as recorded. */
export function sentenceOf(message: string): string {
  return `${(message[0] ?? "").toUpperCase()}${message.slice(1)}`;
}

/** What the check looked at: a node in words, or the subtask or module it ran over. */
export function subjectOf(check: GateCheck): string {
  if (check.node !== null) return nodeLabel(check.node);
  if (check.subtask === "integration") return "the whole design";
  return `the ${check.scope}`;
}

/** The check's secondary id: its number in the gate's list and its gate line. */
export function checkId(check: GateCheck): string {
  return `${check.check === null ? check.name : `check ${String(check.check)}`} · seq ${String(check.seq)}`;
}

export function CheckName({ check }: { readonly check: GateCheck }) {
  const words = checkWords(check.name);
  return (
    <span className="pg-check-name" title={words.explains}>
      {words.name}
      <span className="pg-check-subject"> · {subjectOf(check)}</span>
    </span>
  );
}

/** What was measured: the value, a count of what a pass looked at, or what was left unchecked. */
export function Measured({ check }: { readonly check: GateCheck }) {
  if (check.outcome === "pass") {
    const n = check.evaluated ?? check.details.evaluated;
    if (n === null) return <span className="pg-muted">count not recorded</span>;
    return n === 0 ? (
      <span className="pg-evaluated pg-evaluated-none">0 evaluated · a pass over nothing</span>
    ) : (
      <span className="pg-evaluated">
        <span className="pg-count">{n}</span> evaluated
      </span>
    );
  }
  if (check.value !== null) return <Quantity {...check.value} />;
  if (check.outcome === "unchecked" && check.details.quantities.length > 0)
    // Each quantity in words, whole on its line: a name never breaks in the middle of a word.
    return (
      <span className="pg-muted pg-unchecked-list">
        left unchecked:{" "}
        {check.details.quantities.map((q, i) => (
          <span key={q} className="pg-unchecked-name">
            {quantityLabel(q)}
            {i < check.details.quantities.length - 1 ? ", " : ""}
          </span>
        ))}
      </span>
    );
  return <span className="pg-muted">nothing measured</span>;
}

/** The bound the check held the value to, as recorded. */
export function Bound({ check }: { readonly check: GateCheck }) {
  const { low, high } = check.details;
  if (low !== null && high !== null)
    return (
      <span className="pg-bound">
        <Quantity {...low} /> to <Quantity {...high} />
      </span>
    );
  return check.expected === null ? (
    <span className="pg-muted">no bound recorded</span>
  ) : (
    <span className="pg-bound-text">{check.expected}</span>
  );
}
