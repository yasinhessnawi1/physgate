/**
 * The consented recording state of a study session, always visible while recording. In the
 * library only: no session records anything in this build.
 */
export function ResearchIndicator({
  session,
  recording = true,
}: {
  readonly session?: string;
  readonly recording?: boolean;
}) {
  return (
    <span className={recording ? "pg-badge pg-research" : "pg-badge pg-neutral"}>
      <span className="pg-rec-dot" aria-hidden="true" />
      {recording ? "Recording" : "Paused"}
      {session !== undefined && <span className="pg-research-session">· {session}</span>}
    </span>
  );
}
