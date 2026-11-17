/**
 * Each run's name as every other screen gives it ("Run a2-g11-12 · 16 Nov, 19:52"), read from the
 * run list once for the whole Evidence screen; a run the list does not name keeps its folder name.
 */
import { createContext, useContext, useMemo } from "react";

import { runListing } from "../../api/records";
import { useJson } from "../../screens/common/read";
import { runLabels } from "../../words/runs";
import { type Place, placeKey } from "./api";

export const RunNamesContext = createContext<ReadonlyMap<string, string>>(new Map());

/** Every listed run's name by its ``root/name`` key, once the run list is read. */
export function useRunNamesRead(): ReadonlyMap<string, string> {
  const listed = useJson("/api/runs", runListing).result;
  return useMemo(() => {
    if (listed?.ok !== true) return new Map<string, string>();
    const labels = runLabels(
      listed.value.map((run) => ({
        key: placeKey(run),
        name: run.name,
        runId: run.runId,
        started: run.started ?? null,
      })),
    );
    return new Map([...labels].map(([key, label]) => [key, label.label]));
  }, [listed]);
}

/** The name a run is given on every screen, or its folder name when the run list does not name it. */
export function useRunName(place: Place): string {
  return useContext(RunNamesContext).get(placeKey(place)) ?? place.name;
}
