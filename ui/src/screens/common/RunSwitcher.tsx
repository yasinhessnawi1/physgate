/**
 * The runs a screen can show, each a link led by its label, with its gate mode and its id after
 * it, smaller. The chosen one is marked. A run the server could not read says why.
 */
import type { RunListing } from "../../api/records";
import { Button } from "../../design/components/actions/Button";
import { Id } from "../../design/components/data/Id";
import { GateModeBadge } from "../../design/components/verdict/GateMode";
import type { AreaId } from "../../shell/areas";
import { hrefFor } from "../../shell/route";
import type { RunLabel } from "../../words/runs";
import { FIRST_RUNS, runKey } from "./runs";

export function RunSwitcher({
  runs,
  chosen,
  labels,
  area,
  slug,
  keep,
  allShown,
  showAll,
}: {
  readonly runs: readonly RunListing[];
  readonly chosen: RunListing | undefined;
  readonly labels: ReadonlyMap<string, RunLabel>;
  readonly area: AreaId;
  readonly slug: string;
  /** The query to keep, the run replaced. */
  readonly keep?: URLSearchParams;
  readonly allShown: boolean;
  readonly showAll: () => void;
}) {
  const shown = allShown ? runs : runs.filter((run, i) => i < FIRST_RUNS || run === chosen);
  const chosenLabel = chosen === undefined ? undefined : labels.get(runKey(chosen));
  return (
    <nav className="pg-runs" aria-label="Runs">
      <details className="pg-runs-menu">
        <summary className="pg-runs-summary pg-hit">
          Showing {chosenLabel?.label ?? (chosen === undefined ? "no run" : `Run ${chosen.name}`)}
          <span className="pg-panel-note"> · choose another run</span>
        </summary>
        <ul className="pg-runs-list">
          {shown.map((run) => {
            const key = runKey(run);
            const on = run === chosen;
            const query = new URLSearchParams(keep);
            query.set("run", key);
            const label = labels.get(key);
            return (
              <li key={key} className="pg-runs-item">
                {run.error === null ? (
                  <a
                    className={on ? "pg-run-link pg-run-link-on pg-hit" : "pg-run-link pg-hit"}
                    aria-current={on ? "page" : undefined}
                    href={hrefFor(area, slug, query)}
                    title={label?.detail}
                  >
                    <span className="pg-run-link-label">{label?.label ?? `Run ${run.name}`}</span>
                    {run.gateMode !== null && <GateModeBadge mode={run.gateMode} />}
                  </a>
                ) : (
                  <span className="pg-run-link pg-run-link-unread">
                    <span className="pg-run-link-label">Run {run.name} could not be read</span>
                    <span className="pg-run-why">{run.error}</span>
                  </span>
                )}
                <Id value={run.name} copy={false} />
              </li>
            );
          })}
        </ul>
        {!allShown && shown.length < runs.length && (
          <Button size="sm" onClick={showAll}>
            Show all runs
          </Button>
        )}
      </details>
    </nav>
  );
}
