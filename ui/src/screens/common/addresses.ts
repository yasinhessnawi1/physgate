/**
 * The addresses one screen links to another by, over the same run: a node in the design graph,
 * and a simulation record of the attempt that wrote it.
 */
import { hrefFor } from "../../shell/route";

/** The design graph over the run ``run`` (``root/name``), with ``node`` selected. */
export function nodeAddress(run: string, node: string): string {
  return hrefFor("orchestration", "design-graph", new URLSearchParams({ run, node }));
}

/** The Simulation screen over the run ``run``, at one attempt and, given one, one record. */
export function recordAddress(
  run: string,
  subtask: string,
  attempt: number,
  record: string | null,
): string {
  const query = new URLSearchParams({ run, subtask, attempt: String(attempt) });
  if (record !== null) query.set("record", record);
  return hrefFor("simulation", "series", query);
}
