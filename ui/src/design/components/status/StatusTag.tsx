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
} as const satisfies Record<string, readonly [IconName, string]>;

export type StatusKind = keyof typeof STATUS_KINDS;

export function StatusTag({
  status,
  strong = false,
}: {
  readonly status: StatusKind;
  readonly strong?: boolean;
}) {
  const [icon, word] = STATUS_KINDS[status];
  return (
    <span className={strong ? "pg-status pg-status-strong" : "pg-status"} data-status-kind={status}>
      <Icon name={icon} size={12} />
      {word}
    </span>
  );
}
