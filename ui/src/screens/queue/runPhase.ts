/**
 * Where the run of the item on screen stands, for what a decision on it says: a queue item gives
 * it to the decision it holds, so a decision's confirmation names the run's state without each
 * screen passing it along. ``undefined`` until the run's status is read.
 */
import { createContext, useContext } from "react";

import type { Phase } from "../../words/standing";

export const RunPhaseContext = createContext<Phase | undefined>(undefined);

/** Where the run of the item this decision is on stands, if known. */
export function useRunPhase(): Phase | undefined {
  return useContext(RunPhaseContext);
}
