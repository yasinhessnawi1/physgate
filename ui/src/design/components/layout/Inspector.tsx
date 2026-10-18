import type { ReactNode } from "react";

import { Button } from "../actions/Button";

/**
 * The right-hand inspector, the same at every level: where the selection sits, its title, its
 * badges, then labelled sections.
 */
export function Inspector({
  label,
  crumbs = [],
  title,
  badges,
  onClose,
  children,
}: {
  /** The inspector's accessible name, for example "Node inspector". */
  readonly label: string;
  readonly crumbs?: readonly string[];
  readonly title: ReactNode;
  readonly badges?: ReactNode;
  readonly onClose?: () => void;
  readonly children?: ReactNode;
}) {
  return (
    <aside className="pg-inspector" aria-label={label}>
      <div className="pg-inspector-head">
        <div className="pg-inspector-bar">
          {crumbs.length > 0 && (
            <ol className="pg-crumbs" aria-label="Where this is">
              {crumbs.map((crumb, i) => (
                <li key={`${String(i)}-${crumb}`}>{crumb}</li>
              ))}
            </ol>
          )}
          {onClose !== undefined && (
            <Button
              variant="ghost"
              size="sm"
              icon="x"
              title="Close the inspector"
              onClick={onClose}
            />
          )}
        </div>
        <h2 className="pg-inspector-title">{title}</h2>
        {badges !== undefined && <div className="pg-inspector-badges">{badges}</div>}
      </div>
      {children}
    </aside>
  );
}

/** A labelled section of the inspector. */
export function InspectorSection({
  label,
  aside,
  children,
}: {
  readonly label: string;
  readonly aside?: ReactNode;
  readonly children?: ReactNode;
}) {
  return (
    <section className="pg-inspector-section" aria-label={label}>
      <h3 className="pg-section-label">
        <span>{label}</span>
        {aside}
      </h3>
      {children}
    </section>
  );
}
