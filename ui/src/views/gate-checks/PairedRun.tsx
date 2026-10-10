import { getLines } from "../../api/client";
import type { RunConfig } from "../../api/records";
import { type GateCheck, gateCheck } from "../../api/run";
import { GateModeBadge, GateOutcome } from "../../design/components/GateMode";
import { SourceChip, sourceAttribute } from "../../design/components/SourceChip";
import { EmptyState, ErrorState, LoadingState } from "../../design/components/States";
import { Tally } from "../../design/components/VerdictBadge";
import { tallyOfChecks } from "../../design/tally";
import { baseOfKey, runSource } from "../common/runs";
import { useResult } from "../common/useResult";

/**
 * The same plan's checks in another gate mode, from a run the operator picked among those with
 * the same brief and seed. An observe run's numbers carry no pass or fail of their own: they read
 * as what the gate would have done.
 */
export function PairedRun({
  candidates,
  pairKey,
  pairHref,
}: {
  candidates: readonly (readonly [string, RunConfig])[];
  pairKey: string | null;
  pairHref: (key: string | null) => string;
}) {
  const picked = candidates.find(([key]) => key === pairKey);
  const base = picked === undefined ? null : baseOfKey(picked[0]);
  const checks = useResult(
    base === null ? null : () => getLines(`${base}/gate-checks`, gateCheck),
    `${String(base)}/gate-checks`,
  );
  return (
    <section className="card paired" aria-label="Same plan, another gate mode">
      <h2 className="card-title">Same plan, another gate mode</h2>
      {candidates.length === 0 ? (
        <EmptyState title="No run to read this one against">
          A run is offered here only when another run under the roots has the same brief, by digest,
          and the same seed, in a different gate mode.
        </EmptyState>
      ) : (
        <nav className="run-picker" aria-label="Runs of the same brief and seed">
          {candidates.map(([key, config]) => (
            <a
              key={key}
              className={key === pairKey ? "run-link run-link-on" : "run-link"}
              aria-current={key === pairKey ? "page" : undefined}
              href={pairHref(key === pairKey ? null : key)}
            >
              <span className="mono">{config.runId}</span>
              {pairedWhere(key, config, candidates) !== null && (
                <span className="run-where mono">{pairedWhere(key, config, candidates)}</span>
              )}
              <GateModeBadge mode={config.gateMode} />
            </a>
          ))}
        </nav>
      )}
      {picked !== undefined &&
        (checks === null ? (
          <LoadingState reading="the paired run's gate checks" />
        ) : !checks.ok ? (
          <ErrorState title="The paired run's gate checks: not shown" refusal={checks.refusal} />
        ) : (
          <PairedBody config={picked[1]} checks={checks.value} />
        ))}
    </section>
  );
}

/** Where a candidate is, when its id alone does not tell it apart: its root and directory. */
export function pairedWhere(
  key: string,
  config: RunConfig,
  candidates: readonly (readonly [string, RunConfig])[],
): string | null {
  const [root = "", ...name] = key.split("/");
  const directory = name.join("/");
  const shared = candidates.filter(([, c]) => c.runId === config.runId).length > 1;
  return shared || directory !== config.runId ? `root ${root} · ${directory}` : null;
}

/** The paired run's checks: its mode, its tally, and what failed or warned, in its own mode. */
export function PairedBody({
  config,
  checks,
}: {
  config: RunConfig;
  checks: readonly GateCheck[];
}) {
  return (
    <div className="paired-body" data-source={sourceAttribute(runSource(config))}>
      <div className="title-with-badge">
        <span className="mono">{config.runId}</span>
        <GateModeBadge mode={config.gateMode} />
      </div>
      {config.gateMode === "off" ? (
        <p className="view-note">The gate did not run in this run: no check result exists.</p>
      ) : (
        <>
          <Tally counts={tallyOfChecks(checks)} observed={config.gateMode === "observe"} />
          <ul className="paired-list">
            {checks
              .filter((c) => c.outcome === "fail" || c.outcome === "warn")
              .map((c, i) => (
                <li key={String(i)}>
                  <span>
                    {c.name} · <span className="mono">{c.node ?? "—"}</span> · {c.scope}
                  </span>
                  <GateOutcome mode={c.mode} outcome={c.outcome} />
                </li>
              ))}
          </ul>
        </>
      )}
      {config.gateMode === "observe" && (
        <p className="label">
          Observe runs record what the gate would have done. Their numbers never carry a pass or
          fail of their own.
        </p>
      )}
      <SourceChip source={runSource(config)} />
    </div>
  );
}
