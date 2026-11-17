/**
 * Each run's name as every other screen gives it ("Run a2-g11-12 · 16 Nov, 19:52"), read from the
 * run list once for the whole Evidence screen; a run the list does not name keeps its folder name.
 */
import { createContext, useContext } from "react";

import { useLabels, useRunList, useStarts } from "../../screens/common/runs";
import { type Place, placeKey } from "./api";

const NO_RUNS: readonly never[] = [];

export const RunNamesContext = createContext<ReadonlyMap<string, string>>(new Map());

/** Every listed run's name by its ``root/name`` key, once the run list is read. */
export function useRunNamesRead(): ReadonlyMap<string, string> {
  const listed = useRunList();
  const runs = listed?.ok === true ? listed.value : NO_RUNS;
  const labels = useLabels(runs, useStarts(runs));
  return new Map([...labels].map(([key, label]) => [key, label.label]));
}

/** The name a run is given on every screen, or its folder name when the run list does not name it. */
export function useRunName(place: Place): string {
  return useContext(RunNamesContext).get(placeKey(place)) ?? place.name;
}
