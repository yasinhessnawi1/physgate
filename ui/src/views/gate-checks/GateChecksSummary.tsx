import type { ReactNode } from "react";

import type { GateCheck } from "../../api/run";
import { type GateMode, GateModeBadge } from "../../design/components/GateMode";
import { type Source, SourceChip, sourceAttribute } from "../../design/components/SourceChip";
import { EmptyState } from "../../design/components/States";
import { Tally } from "../../design/components/VerdictBadge";
import { tallyOfChecks } from "../../design/tally";

/**
 * The gate's records counted by the one tally: pass, fail and warn as evaluated, unchecked after
 * the separator. Under observe the counts read as would-be outcomes, not enforced, and the mode
 * badge says the run was not gated.
 */
export function GateChecksSummary({
  checks,
  mode,
  source,
  manifestId,
  children,
}: {
  checks: readonly GateCheck[];
  mode: GateMode;
  source: Source;
  manifestId: string;
  children?: ReactNode;
}) {
  return (
    <section className="card" aria-label="Gate checks" data-source={sourceAttribute(source)}>
      <div className="card-head">
        <div className="title-with-badge">
          <h2 className="card-title">Gate checks</h2>
          <GateModeBadge mode={mode} />
        </div>
        {checks.length > 0 && (
          <Tally counts={tallyOfChecks(checks)} observed={mode === "observe"} />
        )}
      </div>
      {mode === "off" ? (
        <EmptyState title="The gate did not run">
          This run's gate mode is off: every gate stage was skipped and recorded as skipped. No
          check result exists, so none is shown.
        </EmptyState>
      ) : checks.length === 0 ? (
        <EmptyState title="No gate checks recorded">The gate has not run in this run.</EmptyState>
      ) : (
        <>
          <p className="view-note">
            View: counted from <span className="mono">{checks.length}</span> gate records, one per
            check and scope that passed and one per failing, warning or unchecked instance.
          </p>
          {children}
        </>
      )}
      <p className="label">
        Source: gate events of {source.id}, manifest{" "}
        <span className="mono">{manifestId.slice(0, 8)}</span>
      </p>
      <SourceChip source={source} />
    </section>
  );
}
