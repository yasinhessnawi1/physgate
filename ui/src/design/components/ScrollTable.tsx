import type { ReactNode } from "react";

/**
 * A table that may be wider than its card: it scrolls in a region the keyboard can reach and a
 * screen reader can name, so no column is out of reach.
 */
export function ScrollTable({ label, children }: { label: string; children: ReactNode }) {
  return (
    // A scrolling region must be focusable to be scrolled by keyboard (axe: scrollable-region-focusable).
    <div className="table-scroll" role="region" aria-label={label} tabIndex={0}>
      {children}
    </div>
  );
}
