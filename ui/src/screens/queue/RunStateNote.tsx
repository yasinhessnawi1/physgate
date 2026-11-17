/**
 * The line a decision's confirmation leads with on a run that is not going: the run's state, and
 * that the decision is recorded now and taken up when the run is resumed. It reads where the run
 * stands from the queue item it sits in (``RunPhaseContext``), so any decision panel names it
 * with this one element in its confirmation; on a going run, or before the status is read, it is
 * nothing.
 */
import { decisionPendingWords } from "../../words/standing";
import { useRunPhase } from "./runPhase";

export function RunStateNote() {
  const phase = useRunPhase();
  const pending = phase === undefined ? null : decisionPendingWords(phase);
  return pending === null ? null : <p className="pg-dialog-note pg-dialog-run-state">{pending}</p>;
}
