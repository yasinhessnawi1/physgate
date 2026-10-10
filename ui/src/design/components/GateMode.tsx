import { type Verdict, VerdictBadge } from "./VerdictBadge";

/** The gate mode a run was recorded under. */
export type GateMode = "on" | "observe" | "off";

const MODES: Record<GateMode, readonly [string, string]> = {
  on: ["⛨", "Gate on"],
  observe: ["◉", "Observe · not gated"],
  off: ["⊘", "Gate off"],
};

/** On is solid navy; observe is purple and hatched and says it is not gated; off is grey. */
export function GateModeBadge({ mode }: { mode: GateMode }) {
  const [glyph, word] = MODES[mode];
  return (
    <span className={`badge gate-mode gate-mode-${mode}`}>
      <span aria-hidden="true">{glyph}</span> {word}
    </span>
  );
}

/**
 * A gate check's outcome under the mode it ran in. Under observe nothing was enforced, so a
 * result there is never drawn as a filled pass or fail: it reads "would fail" or "would pass",
 * in a dashed outline. An unchecked outcome is unchecked in every mode.
 */
export function GateOutcome({ mode, outcome }: { mode: GateMode; outcome: Verdict }) {
  if (mode === "observe" && outcome !== "unchecked") {
    const word =
      outcome === "pass" ? "Would pass" : outcome === "fail" ? "Would fail" : "Would warn";
    return <span className={`badge observed observed-${outcome}`}>{word} · not enforced</span>;
  }
  return <VerdictBadge verdict={outcome} />;
}
