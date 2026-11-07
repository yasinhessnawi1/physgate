import { ENGINE_STATUS_WORDS, PAIR_WORDS } from "../../../words/settings";
import { Icon, type IconName } from "../icons/Icon";

/**
 * The states that are not verdicts. Each is neutral: an icon and a word, never a check or a cross, and never
 * the pass, fail or warn colours, because none of them is a judgement by the gate or a reviewer.
 */
export const STATUS_KINDS = {
  applied: ["arrow-up-from-line", "Applied"],
  refused: ["ban", "Refused"],
  declined: ["minus", "Declined"],
  resolved: ["inbox", "Resolved"],
  waiting: ["clock", "Waiting"],
  frozen: ["lock", "Frozen"],
  confirmed: ["lock", "Confirmed"],
  complete: ["circle-dot", "Complete"],
  queued: ["clock", "Queued"],
  "seal-holds": ["lock", "Seal holds"],
  "seal-tampered": ["ban", "Seal broken"],
  "seal-missing": ["minus", "Transcript missing"],
  "seal-none": ["minus", "No seal"],
  "seal-elsewhere": ["minus", "Not in this run"],
  "seal-too-large": ["minus", "Too large to check"],
  "coming-soon": ["clock", "Coming soon"],
  // How physgate is set up: an engine's status in the catalogue, and a reviewer's model string
  // beside its builder's. A comparison of two strings is not a review's verdict.
  "engine-available": ["circle-dot", ENGINE_STATUS_WORDS.available],
  "pair-different-strings": ["git-compare", PAIR_WORDS.different],
  "pair-same-string": ["ban", PAIR_WORDS.same],
  "engine-not-yet": ["clock", ENGINE_STATUS_WORDS["not-yet"]],
} as const satisfies Record<string, readonly [IconName, string]>;

export type StatusKind = keyof typeof STATUS_KINDS;

/**
 * The states drawn dashed: none is a state recorded as reached, such as an engine the catalogue
 * lists but does not offer yet. Dashed in neutral ink, never in the unchecked verdict's colours.
 */
const DASHED: ReadonlySet<StatusKind> = new Set(["engine-not-yet"]);

export function StatusTag({
  status,
  strong = false,
}: {
  readonly status: StatusKind;
  readonly strong?: boolean;
}) {
  const [icon, word] = STATUS_KINDS[status];
  return (
    <span
      className={[
        "pg-status",
        strong ? "pg-status-strong" : null,
        DASHED.has(status) ? "pg-status-dashed" : null,
      ]
        .filter((c) => c !== null)
        .join(" ")}
      data-status-kind={status}
    >
      <Icon name={icon} size={12} />
      {word}
    </span>
  );
}
