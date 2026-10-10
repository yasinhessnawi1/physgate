import { getLines } from "../../api/client";
import type { RunConfig } from "../../api/records";
import { gateCheck } from "../../api/run";
import { GateModeBadge, GateOutcome } from "../../design/components/GateMode";
import { SourceChip, sourceAttribute } from "../../design/components/SourceChip";
import { EmptyState, ErrorState, LoadingState } from "../../design/components/States";
import { Tally } from "../../design/components/VerdictBadge";
import { tallyOf } from "../../design/tally";
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
          <div className="paired-body" data-source={sourceAttribute(runSource(picked[1]))}>
            <div className="title-with-badge">
              <span className="mono">{picked[1].runId}</span>
              <GateModeBadge mode={picked[1].gateMode} />
            </div>
            {picked[1].gateMode === "off" ? (
              <p className="view-note">The gate did not run in this run: no check result exists.</p>
            ) : (
              <>
                <Tally
                  counts={tallyOf(checks.value.map((c) => c.outcome))}
                  observed={picked[1].gateMode === "observe"}
                />
                <ul className="paired-list">
                  {checks.value
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
            {picked[1].gateMode === "observe" && (
              <p className="label">
                Observe runs record what the gate would have done. Their numbers never carry a pass
                or fail of their own.
              </p>
            )}
            <SourceChip source={runSource(picked[1])} />
          </div>
        ))}
    </section>
  );
}
