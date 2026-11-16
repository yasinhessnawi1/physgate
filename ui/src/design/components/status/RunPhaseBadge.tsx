import type { Phase } from "../../../words/standing";
import { Icon, type IconName } from "../icons/Icon";
import { InProgressBadge } from "./InProgressBadge";

/** Each phase but going: its icon and its word. Neutral: none is a verdict on the run's work. */
export const PHASE_BADGES: Readonly<Record<Exclude<Phase, "going">, readonly [IconName, string]>> =
  {
    stopped: ["pause", "Stopped · no end recorded"],
    "waiting-person": ["clock", "Waiting for you"],
    "waiting-limit": ["clock", "Waiting for the usage limit"],
    halted: ["octagon-x", "Halted"],
    "halt-owed": ["octagon-x", "Halt owed"],
    done: ["circle-dot", "Ended"],
  };

/**
 * Where a run stands, as a badge beside its gate mode: the pulsing "in progress" badge only while
 * it is going, and otherwise what it is: stopped, waiting, halted or ended. ``word`` replaces the
 * ended run's word with a finer one ("Complete").
 */
export function RunPhaseBadge({ phase, word }: { readonly phase: Phase; readonly word?: string }) {
  if (phase === "going") return <InProgressBadge />;
  const [icon, said] = PHASE_BADGES[phase];
  return (
    <span className="pg-badge pg-neutral pg-phase" data-phase={phase}>
      <Icon name={icon} size={12} />
      {word ?? said}
    </span>
  );
}
