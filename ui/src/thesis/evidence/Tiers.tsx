/**
 * The tier versions, at the head of the Gaps tab: per role, the version of its tasks a person last
 * published from the tier store, one card each. A card says the version (short, the whole id one
 * copy away), how many tasks each tier holds, what the blind check of the held-out tasks found,
 * whether anything has seen them, the version's state, whether a measured run names it (one word,
 * never a number), and when the copy was read, warned of once it is more than a week old.
 *
 * These are the tiers' sizes and properties, fixed before any result: no result of any run, no
 * chart and no link to a task is shown here. Nothing is computed but the copy's age.
 */
import { useState } from "react";

import { EmptyState, ErrorState, LoadingState } from "../../design/components/status/States";
import { useJson } from "../../screens/common/read";
import { type BlindCheck, evidenceTiers, type RoleTiers, TIERS_ROUTE } from "./api";
import { ageWords, STALE_AFTER } from "./Gaps";
import { ShortId } from "./parts";
import { EVIDENCE_COPY } from "./words";

/** When the copy was read, in words: its day, its time to the minute, its zone and its age. */
export function tiersReadAtWords(readAt: string, now: number): string {
  const found = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(?::\d{2}(?:\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/.exec(
    readAt,
  );
  if (found === null) return EVIDENCE_COPY.tiersReadAtAsSent(readAt);
  const zone = found[3] === "Z" || found[3] === "+00:00" ? "UTC" : `UTC${found[3] ?? ""}`;
  return EVIDENCE_COPY.tiersReadAt(found[1] ?? "", found[2] ?? "", zone, ageWords(readAt, now));
}

function checkWords(check: BlindCheck): string {
  if (check.state === "none") return EVIDENCE_COPY.noBlindCheck;
  if (check.state === "refused") return EVIDENCE_COPY.checkRefused(check.refused);
  return `${EVIDENCE_COPY.checkCounts(check.allYes, check.tasks, check.leftOut)} (${EVIDENCE_COPY.checkSource[check.source]})`;
}

function CardBody({ tiers, now }: { readonly tiers: RoleTiers; readonly now: number }) {
  if (tiers.state === "none") return <p className="evidence-note">{EVIDENCE_COPY.noTiers}</p>;
  if (tiers.state === "refused")
    return (
      <div className="pg-state pg-state-error evidence-tiers-refused">
        <h4 className="pg-state-title">{EVIDENCE_COPY.tiersNotShown(tiers.role)}</h4>
        <p className="pg-state-body">{tiers.error}</p>
        {tiers.readAt !== null && (
          <p className="evidence-note" data-note="read-at">
            {tiersReadAtWords(tiers.readAt, now)}
          </p>
        )}
      </div>
    );
  const at = Date.parse(tiers.readAt);
  const old = !Number.isNaN(at) && now - at > STALE_AFTER;
  return (
    <>
      <dl className="evidence-tier-facts">
        <dt>{EVIDENCE_COPY.tiersVersion}</dt>
        <dd data-fact="version">
          <ShortId value={tiers.version} />
        </dd>
        <dt>{EVIDENCE_COPY.tiersTasks}</dt>
        <dd data-fact="counts">
          {EVIDENCE_COPY.tierCounts(
            tiers.counts.visible,
            tiers.counts.validation,
            tiers.counts.heldOut,
          )}
        </dd>
        <dt>{EVIDENCE_COPY.blindCheck}</dt>
        <dd data-fact="check">{checkWords(tiers.check)}</dd>
        <dt>{EVIDENCE_COPY.exposureLabel}</dt>
        <dd data-fact="exposure">{EVIDENCE_COPY.exposureWords[tiers.exposure]}</dd>
        <dt>{EVIDENCE_COPY.stateLabel}</dt>
        <dd data-fact="state">{EVIDENCE_COPY.stateWords[tiers.versionState]}</dd>
      </dl>
      <p className="evidence-note" data-fact="measured">
        {tiers.measured ? EVIDENCE_COPY.measured : EVIDENCE_COPY.notMeasuredYet}
      </p>
      <p className="evidence-note" data-note="read-at">
        {tiersReadAtWords(tiers.readAt, now)}
      </p>
      {old && (
        <p className="evidence-note evidence-warn" data-note="stale" role="status">
          {EVIDENCE_COPY.tiersStale}
        </p>
      )}
    </>
  );
}

/** The tier versions as read from their own route: a failure here never hides the gap trend. */
export function TierPanel() {
  const tiers = useJson(TIERS_ROUTE, evidenceTiers);
  // The one clock reading the cards' ages are told against, taken when the panel is first shown.
  const [now] = useState(() => Date.now());
  if (tiers.result === null) return <LoadingState reading={EVIDENCE_COPY.readingTiers} />;
  if (!tiers.result.ok)
    return (
      <ErrorState
        title={EVIDENCE_COPY.tiersRefused}
        {...tiers.result.refusal}
        route={tiers.route}
        onRetry={tiers.again}
      />
    );
  const { roles } = tiers.result.value;
  return (
    <section
      className="pg-card pg-panel evidence-tiers"
      aria-label={EVIDENCE_COPY.tierPanelTitle}
      data-panel="tiers"
    >
      <h2 className="pg-panel-title">{EVIDENCE_COPY.tierPanelTitle}</h2>
      <p className="evidence-note">{EVIDENCE_COPY.tierPanelLead}</p>
      {roles.length === 0 ? (
        <EmptyState title={EVIDENCE_COPY.noTiers} icon="microscope" />
      ) : (
        <div className="evidence-tier-cards">
          {roles.map((role) => (
            <article
              key={role.role}
              className="evidence-tier-card"
              aria-label={EVIDENCE_COPY.roleTitle(role.role)}
              data-tier-role={role.role}
              data-source={`tier status · ${role.role}`}
            >
              <h3>{EVIDENCE_COPY.roleTitle(role.role)}</h3>
              <CardBody tiers={role} now={now} />
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
