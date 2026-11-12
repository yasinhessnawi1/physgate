import { Icon, type IconName } from "../../design/components/icons/Icon";

/**
 * A state that is not a verdict, in the neutral status style: an icon and its words, never a
 * check or a cross, and never a verdict's colour. The words are the screen's, or a recorded word
 * shown as written.
 */
export function Tag({
  icon,
  kind,
  children,
}: {
  readonly icon: IconName;
  /** What the tag says, for tests and styles: never shown. */
  readonly kind: string;
  readonly children: string;
}) {
  return (
    <span className="pg-status" data-status-kind={kind}>
      <Icon name={icon} size={12} />
      {children}
    </span>
  );
}
