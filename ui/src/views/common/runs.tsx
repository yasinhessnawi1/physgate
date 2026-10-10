/**
 * Choosing a run, shared by every view over one run: the run list, the chosen run's
 * configuration and its source, and the picker. The choice lives in the hash's ``run`` query, so
 * a link or a shortcut keeps it.
 */
import { getJson, type Result } from "../../api/client";
import { type RunConfig, runConfig, type RunListing, runListing } from "../../api/records";
import { GateModeBadge } from "../../design/components/GateMode";
import type { Source } from "../../design/components/SourceChip";
import type { AreaId } from "../../shell/areas";
import { hrefFor } from "../../shell/route";
import { useResult } from "./useResult";

export interface ChosenRun {
  readonly runs: Result<readonly RunListing[]> | null;
  readonly chosen: RunListing | undefined;
  readonly config: Result<RunConfig> | null;
  /** The path every route over the chosen run starts with. */
  readonly base: string | null;
}

export function runKey(run: RunListing): string {
  return `${String(run.root)}/${run.name}`;
}

export function runBase(run: RunListing): string {
  return `/api/runs/${String(run.root)}/${encodeURIComponent(run.name)}`;
}

/** The route base of the run a ``root/name`` key names. */
export function baseOfKey(key: string): string {
  const [root = "", ...name] = key.split("/");
  return `/api/runs/${root}/${encodeURIComponent(name.join("/"))}`;
}

/** The run the query names, or the first readable one, with its configuration. */
export function useChosenRun(query: URLSearchParams): ChosenRun {
  const runs = useResult(() => getJson("/api/runs", runListing), "/api/runs");
  const readable = runs?.ok === true ? runs.value.filter((run) => run.error === null) : [];
  const wanted = query.get("run");
  const chosen = readable.find((run) => runKey(run) === wanted) ?? readable[0];
  const base = chosen === undefined ? null : runBase(chosen);
  const config = useResult(
    base === null ? null : () => getJson(`${base}/config`, runConfig),
    `${String(base)}/config`,
  );
  return { runs, chosen, config, base };
}

/** Where a figure of ``config``'s run comes from: the run and the harness commit. */
export function runSource(config: RunConfig): Source {
  return { id: `run ${config.runId}`, commit: config.harnessCommit };
}

/**
 * Where a run is, said when its id alone does not tell it apart: the root it was found under and
 * its directory, for a run whose id another listed run shares or whose directory has another name.
 */
export function whereLabel(run: RunListing, runs: readonly RunListing[]): string | null {
  const id = run.runId ?? run.name;
  const shared = runs.filter((other) => (other.runId ?? other.name) === id).length > 1;
  return shared || id !== run.name ? `root ${String(run.root)} · ${run.name}` : null;
}

/** The runs as links, the chosen one marked; each says its gate mode, and where it is if needed. */
export function RunPicker({
  runs,
  chosen,
  area,
  slug,
  keep,
}: {
  runs: readonly RunListing[];
  chosen: RunListing | undefined;
  area: AreaId;
  slug: string;
  keep?: URLSearchParams;
}) {
  return (
    <nav className="run-picker" aria-label="Runs">
      {runs.map((run) => {
        const key = runKey(run);
        const on = run === chosen;
        const query = new URLSearchParams(keep);
        query.set("run", key);
        return (
          <a
            key={key}
            className={on ? "run-link run-link-on" : "run-link"}
            aria-current={on ? "page" : undefined}
            href={hrefFor(area, slug, query)}
          >
            <span className="mono">{run.runId ?? run.name}</span>
            {whereLabel(run, runs) !== null && (
              <span className="run-where mono">{whereLabel(run, runs)}</span>
            )}
            {run.gateMode !== null && <GateModeBadge mode={run.gateMode} />}
            {run.error !== null && <span className="muted">unreadable: {run.error}</span>}
          </a>
        );
      })}
    </nav>
  );
}
