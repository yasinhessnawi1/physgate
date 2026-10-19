/**
 * The same design run with the gate in another mode: the runs of the same brief, by digest, and
 * the same seed, each led by its label. The person picks one; nothing is paired silently, since two
 * runs that differ in more than the mode say nothing about the mode. An observe run's results read
 * as what the gate would have done, never as a pass or a fail of their own.
 */
import { getLines } from "../../api/client";
import type { RunConfig } from "../../api/records";
import { type GateCheck, gateCheck } from "../../api/run";
import { SourceChip } from "../../design/components/data/SourceChip";
import { sourceAttribute } from "../../design/components/data/source";
import { EmptyState, ErrorState, LoadingState } from "../../design/components/status/States";
import { GateModeBadge, GateOutcome } from "../../design/components/verdict/GateMode";
import { Tally } from "../../design/components/verdict/Tally";
import { tallyOfChecks } from "../../design/tally";
import type { RunLabel } from "../../words/runs";
import { CheckName } from "../common/checks";
import { baseOfKey, runSource } from "../common/runs";
import { useResult } from "../common/useResult";

export function PairedRun({
  candidates,
  labels,
  pairKey,
  pairHref,
}: {
  readonly candidates: readonly (readonly [string, RunConfig])[];
  readonly labels: ReadonlyMap<string, RunLabel>;
  readonly pairKey: string | null;
  readonly pairHref: (key: string | null) => string;
}) {
  const picked = candidates.find(([key]) => key === pairKey);
  const base = picked === undefined ? null : baseOfKey(picked[0]);
  const checks = useResult(
    base === null ? null : () => getLines(`${base}/gate-checks`, gateCheck),
    `${String(base)}/gate-checks`,
  );
  const labelOf = (key: string) =>
    labels.get(key)?.label ?? `Run ${key.split("/").slice(1).join("/")}`;
  return (
    <section
      className="pg-card pg-panel"
      aria-label="The same design, run with the gate in another mode"
    >
      <header className="pg-panel-head">
        <h2 className="pg-panel-title">The same design, run with the gate in another mode</h2>
      </header>
      <p className="pg-panel-note">
        The same brief, by its digest, and the same seed, so only the gate mode differs.
      </p>
      {candidates.length === 0 ? (
        <EmptyState title="No run to read this one against">
          A run is offered here only when another run on this machine has the same brief and the
          same seed, in a different gate mode.
        </EmptyState>
      ) : (
        <nav className="pg-runs" aria-label="Runs of the same brief and seed">
          <ul className="pg-runs-list pg-runs-column">
            {candidates.map(([key, config]) => (
              <li key={key} className="pg-runs-item">
                <a
                  className={
                    key === pairKey ? "pg-run-link pg-run-link-on pg-hit" : "pg-run-link pg-hit"
                  }
                  aria-current={key === pairKey ? "page" : undefined}
                  href={pairHref(key === pairKey ? null : key)}
                  title={labels.get(key)?.detail}
                >
                  <span className="pg-run-link-label">{labelOf(key)}</span>
                  <GateModeBadge mode={config.gateMode} />
                </a>
              </li>
            ))}
          </ul>
        </nav>
      )}
      {picked !== undefined &&
        (checks === null ? (
          <LoadingState reading="the paired run's gate checks" />
        ) : !checks.ok ? (
          <ErrorState title="The paired run's gate checks could not be read" {...checks.refusal} />
        ) : (
          <PairedBody label={labelOf(picked[0])} config={picked[1]} checks={checks.value} />
        ))}
    </section>
  );
}

/** The paired run's checks: its mode, its tally, and what failed or warned, in its own mode. */
export function PairedBody({
  label,
  config,
  checks,
}: {
  readonly label: string;
  readonly config: RunConfig;
  readonly checks: readonly GateCheck[];
}) {
  return (
    <div className="pg-paired-body" data-source={sourceAttribute(runSource(config))}>
      <div className="pg-figure-line">
        <span className="pg-run-name">{label}</span>
        <GateModeBadge mode={config.gateMode} />
      </div>
      {config.gateMode === "off" ? (
        <p className="pg-muted">The gate did not run in this run: no check result exists.</p>
      ) : (
        <>
          <Tally {...tallyOfChecks(checks)} observed={config.gateMode === "observe"} compact />
          <ul className="pg-list">
            {checks
              .filter((c) => c.outcome === "fail" || c.outcome === "warn")
              .map((c, i) => (
                <li key={String(i)} className="pg-list-row">
                  <span className="pg-list-row-main">
                    <CheckName check={c} />
                  </span>
                  <GateOutcome mode={c.mode} outcome={c.outcome} />
                </li>
              ))}
          </ul>
        </>
      )}
      {config.gateMode === "observe" && (
        <p className="pg-panel-note">
          Observe runs record what the gate would have done. Their numbers never carry a pass or
          fail of their own.
        </p>
      )}
      <SourceChip {...runSource(config)} />
    </div>
  );
}
