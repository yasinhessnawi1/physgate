/** A pulsing dot: the figures beside it come from a run still in progress, and are partial. */
export function InProgressBadge() {
  return (
    <span className="pg-badge pg-live">
      <span className="pg-live-dot" aria-hidden="true" />
      In progress · partial
    </span>
  );
}
