/**
 * One item as a person decides it: the five things the queue records with it (the decision
 * required, the artefact diff, the triggering finding, up to three quantities, every trajectory),
 * each trajectory with its seal status as the server found it, and the gate's checks one link
 * away. A decided item shows its decision and the queue's own mark, word for word.
 */
import type { ReactNode } from "react";

import type { Decided, ItemView } from "../../api/queue";
import { Quantity } from "../../design/components/Quantity";
import { type Source, SourceChip, sourceAttribute } from "../../design/components/SourceChip";
import { hrefFor } from "../../shell/route";
import { SOURCE_LABEL, STATUS_SHOWN } from "./model";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="queue-section" aria-label={title}>
      <h3 className="queue-section-title">{title}</h3>
      {children}
    </section>
  );
}

export function ItemDetail({
  view,
  decided,
  source,
  runKey,
  children,
}: {
  view: ItemView;
  decided: Decided | undefined;
  source: Source;
  runKey: string;
  children?: ReactNode;
}) {
  const { item } = view;
  return (
    <section
      className="card queue-detail"
      aria-labelledby="queue-decision"
      data-source={sourceAttribute(source)}
    >
      <div className="queue-detail-head">
        <span className="label">Decision required</span>
        <h2 className="queue-decision" id="queue-decision">
          {item.decisionRequired}
        </h2>
        <div className="queue-chips">
          <span className="chip mono">{item.subtaskId}</span>
          <span className="chip">{SOURCE_LABEL[item.source]}</span>
          <SourceChip source={source} />
        </div>
      </div>
      <Section title="Key quantities">
        {item.quantities.length === 0 ? (
          <p className="view-note">This item cites no quantities.</p>
        ) : (
          <div className="queue-quantities">
            {item.quantities.map((cited) => (
              <div key={`${cited.nodeId}/${cited.name}`} className="queue-quantity">
                <span className="label">{cited.name}</span>
                <Quantity q={cited.q} />
                <span className="muted mono">{cited.nodeId}</span>
              </div>
            ))}
          </div>
        )}
      </Section>
      <Section title="Triggering finding">
        <p className="queue-text">{item.triggeringFinding}</p>
      </Section>
      <Section title="Artefact diff">
        {item.artefactDiff === "" ? (
          <p className="view-note">The item records no diff.</p>
        ) : (
          <pre className="queue-diff" tabIndex={0} aria-label="The artefact diff as recorded">
            {item.artefactDiff}
          </pre>
        )}
      </Section>
      <Section title="Trajectories">
        <ul className="queue-trajectories">
          {view.trajectories.map((t, i) => {
            const [verdict, glyph, words] = STATUS_SHOWN[t.status];
            return (
              <li key={`${String(i)}-${t.link}`} className="queue-trajectory">
                <span className="mono">{t.sessionId ?? t.link}</span>
                <span className={`badge verdict verdict-${verdict}`} data-status={t.status}>
                  <span aria-hidden="true">{glyph}</span> {words}
                </span>
              </li>
            );
          })}
        </ul>
      </Section>
      <Section title="Gate output">
        <a
          className="queue-link"
          href={hrefFor("orchestration", "gate-checks", new URLSearchParams({ run: runKey }))}
        >
          This run's gate checks, with each check's bound and verdict
        </a>
      </Section>
      {decided !== undefined ? (
        <Section title="Decision">
          <dl className="facts">
            <dt>Decided</dt>
            <dd className="mono queue-decided-text">{decided.decision}</dd>
            <dt>By</dt>
            <dd className="mono">{decided.resolvedBy}</dd>
            <dt>At</dt>
            <dd className="mono">{decided.ts}</dd>
          </dl>
          {decided.flag !== null && (
            <p className="queue-flag" role="note">
              <span aria-hidden="true">!</span> {decided.flag}
            </p>
          )}
        </Section>
      ) : (
        children
      )}
    </section>
  );
}
