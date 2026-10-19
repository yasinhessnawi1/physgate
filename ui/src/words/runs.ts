/**
 * A run's human label: "Run 16 Oct, 13:58", from the time its first event (the run_started line)
 * was written, in the viewer's time zone. The UTC time and the run's id stay one hover, one
 * focus or one screen reader away. Two runs that would read the same are told apart by their run
 * id, and by their folder when the ids are the same too.
 */

const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
] as const;

/** Milliseconds since the epoch of a log timestamp (``2026-10-10T12:00:00.123456Z``). */
export function instant(ts: string): number {
  return Date.parse(ts.replace(/(\.\d{3})\d*Z$/, "$1Z"));
}

const two = (n: number) => String(n).padStart(2, "0");

/** "16 Oct, 13:58" in the viewer's time zone. */
export function dayAndMinute(ts: string): string {
  const d = new Date(instant(ts));
  if (Number.isNaN(d.getTime())) return ts;
  return `${String(d.getDate())} ${MONTHS[d.getMonth()] ?? ""}, ${two(d.getHours())}:${two(d.getMinutes())}`;
}

/** "13:58:04" in the viewer's time zone: a row's time on a timeline. */
export function clockTime(ts: string): string {
  const d = new Date(instant(ts));
  if (Number.isNaN(d.getTime())) return ts;
  return `${two(d.getHours())}:${two(d.getMinutes())}:${two(d.getSeconds())}`;
}

/** The time as recorded, in UTC, to the second: what the hover says. */
export function utc(ts: string): string {
  const d = new Date(instant(ts));
  if (Number.isNaN(d.getTime())) return ts;
  return `${d.toISOString().slice(0, 19).replace("T", " ")} UTC`;
}

export interface LabelledRun {
  /** The run's folder, unique under its root. */
  readonly key: string;
  readonly name: string;
  readonly runId: string | null;
  /** When the run started, as recorded; ``null`` until it is read, or when it cannot be. */
  readonly started: string | null;
}

export interface RunLabel {
  /** What a person reads first. */
  readonly label: string;
  /** "2026-10-16 11:58:04 UTC · run drive-on": the hover, and the accessible name's tail. */
  readonly detail: string;
}

/**
 * Every run's label. A run whose start is not read yet reads by its folder name until it is.
 * Labels that would be equal get the run id after them; ids that are equal too, the folder.
 */
export function runLabels(runs: readonly LabelledRun[]): ReadonlyMap<string, RunLabel> {
  const base = (run: LabelledRun) =>
    run.started === null ? `Run ${run.name}` : `Run ${dayAndMinute(run.started)}`;
  const byBase = new Map<string, LabelledRun[]>();
  for (const run of runs) byBase.set(base(run), [...(byBase.get(base(run)) ?? []), run]);
  const found = new Map<string, RunLabel>();
  for (const [shared, group] of byBase) {
    for (const run of group) {
      const id = run.runId ?? run.name;
      let label = shared;
      if (group.length > 1 && run.started !== null) {
        const sameId = group.filter((other) => (other.runId ?? other.name) === id).length > 1;
        label = `${shared} · ${sameId ? run.name : id}`;
      }
      const when = run.started === null ? "start not read" : utc(run.started);
      found.set(run.key, { label, detail: `${when} · run ${id} · folder ${run.name}` });
    }
  }
  return found;
}
