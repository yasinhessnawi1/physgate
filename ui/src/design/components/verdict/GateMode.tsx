import { Icon, type IconName } from "../icons/Icon";
import type { Verdict } from "./verdict";
import { VerdictBadge } from "./VerdictBadge";

/** The gate mode a run was recorded under. */
export type GateMode = "on" | "observe" | "off";

const MODES: Readonly<Record<GateMode, readonly [IconName, string]>> = {
  on: ["shield-check", "Gate on"],
  observe: ["eye", "Observe · not gated"],
  off: ["shield-off", "Gate off"],
};

/** On is solid ink; observe is purple, hatched and says it is not gated; off is grey. */
export function GateModeBadge({ mode }: { readonly mode: GateMode }) {
  const [icon, word] = MODES[mode];
  return (
    <span className={`pg-badge pg-gate pg-gate-${mode}`}>
      <Icon name={icon} size={11} />
      {word}
    </span>
  );
}

const WOULD: Readonly<Record<"pass" | "fail" | "warn", string>> = {
  pass: "Would pass",
  fail: "Would fail",
  warn: "Would warn",
};

/**
 * A gate check's outcome under the mode it ran in. Under observe nothing was enforced, so a
 * result there is never a filled pass or fail: it reads "Would fail · not enforced" in a dashed,
 * hatched outline. An unchecked outcome is unchecked in every mode.
 */
export function GateOutcome({
  mode,
  outcome,
}: {
  readonly mode: GateMode;
  readonly outcome: Verdict;
}) {
  if (mode === "observe" && outcome !== "unchecked") {
    return (
      <span className={`pg-badge pg-observed pg-observed-${outcome}`}>
        {WOULD[outcome]} · not enforced
      </span>
    );
  }
  return <VerdictBadge verdict={outcome} />;
}
