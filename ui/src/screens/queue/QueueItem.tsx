/**
 * One queue item as a person decides it: the decision it asks for, why a person is asked (with
 * the queue's own source under it), what triggered it, up to three quantities with their source,
 * the artefact diff as recorded, and the transcripts' seals folded into one line. Where the run
 * that listed it acts on decisions, what each verb and each position will do, from the item's own
 * fields. A decided item shows its decision, the queue's own mark word for word, what the run did
 * with it once it took it, and no way to decide again.
 */
import { Fragment, type ReactNode } from "react";

import { type Decided, type ItemView, offeredPositions } from "../../api/queue";
import { Id } from "../../design/components/data/Id";
import { Quantity } from "../../design/components/data/Quantity";
import { SourceChip } from "../../design/components/data/SourceChip";
import { type Source, sourceAttribute } from "../../design/components/data/source";
import { Term } from "../../design/components/help/Term";
import { StatusTag } from "../../design/components/status/StatusTag";
import { nodeLabel, quantityLabel } from "../../words/humanise";
import {
  chooseWords,
  consequenceWords,
  POSITION_WORDS,
  queueHeadline,
  reviewTimeWords,
  SOURCE_WORDS,
  supersededWords,
  takenWords,
} from "../../words/queue";
import { clockTime, utc } from "../../words/runs";
import { ActorTag } from "../common/ActorTag";
import { SEAL_TAG, sealLine } from "./model";

export function QueueItem({
  view,
  decided,
  source,
  subtaskName,
  supersededBy,
  children,
}: {
  readonly view: ItemView;
  readonly decided: Decided | undefined;
  readonly source: Source;
  readonly subtaskName: string;
  /** The item whose choice reopened a module this one is about, when a reopen superseded it. */
  readonly supersededBy?: string | undefined;
  readonly children?: ReactNode;
}) {
  const { item } = view;
  const { consequence } = item;
  const words = SOURCE_WORDS[item.source];
  return (
    <section
      className="pg-queue-item"
      aria-labelledby="pg-queue-decision"
      data-source={sourceAttribute(source)}
    >
      {/* No actor is named here: the queue's record of an item says when it was raised and from
          which source, not by whom, and the interface shows only what a record says. */}
      <div className="pg-queue-over">
        <span className="pg-panel-over">{words.kind}</span>
        <span className="pg-panel-note" title={utc(item.ts)}>
          {clockTime(item.ts)}
        </span>
        <Id value={item.itemId} />
      </div>
      <h2 className="pg-queue-decision" id="pg-queue-decision">
        {queueHeadline(item)}
      </h2>
      <details className="pg-details pg-queue-raw">
        <summary>Details</summary>
        <p className="pg-panel-note">The item's text, as the queue recorded it.</p>
        <pre className="pg-pre" tabIndex={0} aria-label="The item's text as recorded">
          {item.decisionRequired}
        </pre>
      </details>
      <section className="pg-card pg-panel" aria-label="What you are deciding on">
        <h3 className="pg-section-label">What you are deciding on</h3>
        <dl className="pg-facts">
          <dt>Why you are asked</dt>
          <dd>
            {words.why}{" "}
            <span className="pg-block">
              <Id value={item.source} copy={false} />
            </span>
          </dd>
          <dt>What it is about</dt>
          <dd>
            {subtaskName} <Id value={item.subtaskId} copy={false} />
          </dd>
          <dt>What triggered it</dt>
          <dd className="pg-queue-finding">{item.triggeringFinding}</dd>
          {consequence !== null && (
            <>
              <dt>If you approve</dt>
              <dd className="pg-queue-on-approve">{consequenceWords(consequence).approve}</dd>
              <dt>If you reject</dt>
              <dd className="pg-queue-on-reject">{consequenceWords(consequence).reject}</dd>
              {offeredPositions(item.source).map((position) => {
                const effect = consequence.onChoose?.[position];
                return (
                  effect !== undefined && (
                    <Fragment key={position}>
                      <dt>If you choose {POSITION_WORDS[position].toLowerCase()}</dt>
                      <dd className="pg-queue-on-choose">{chooseWords(consequence, effect)}</dd>
                    </Fragment>
                  )
                );
              })}
            </>
          )}
        </dl>
        <details className="pg-details pg-seals">
          <summary>{sealLine(view)}</summary>
          <p className="pg-panel-note">
            Item digest <Id value={view.itemSha256} />
          </p>
          <ul className="pg-list">
            {view.trajectories.map((t, i) => (
              <li key={`${String(i)}-${t.link}`} className="pg-list-row" data-status={t.status}>
                <span className="pg-transcript-session">{t.sessionId ?? t.link}</span>
                <StatusTag status={SEAL_TAG[t.status]} />
              </li>
            ))}
          </ul>
        </details>
        <p className="pg-panel-note">
          Your decision is checked against exactly this view: if the item or a{" "}
          <Term term="sealed">seal</Term> changes before you confirm, the server refuses it.
        </p>
      </section>
      <section className="pg-card pg-panel" aria-label="Evidence">
        <h3 className="pg-section-label">Evidence</h3>
        {item.quantities.length === 0 ? (
          <p className="pg-muted">The item cites no quantities.</p>
        ) : (
          <ul className="pg-list">
            {item.quantities.slice(0, 3).map((cited) => (
              <li key={`${cited.nodeId}/${cited.name}`} className="pg-list-row">
                <span className="pg-list-row-main">
                  <span>
                    {quantityLabel(cited.name)} · {nodeLabel(cited.nodeId)}
                  </span>
                  <Id value={`${cited.nodeId} · ${cited.name}`} copy={false} />
                </span>
                <Quantity {...cited.q} />
                <SourceChip {...source} compact />
              </li>
            ))}
          </ul>
        )}
        <details className="pg-details">
          <summary>The artefact diff, as recorded</summary>
          {item.artefactDiff === "" ? (
            <p className="pg-muted">The item records no diff.</p>
          ) : (
            <pre
              className="pg-pre pg-queue-diff"
              tabIndex={0}
              aria-label="The artefact diff as recorded"
            >
              {item.artefactDiff}
            </pre>
          )}
        </details>
      </section>
      {decided !== undefined ? (
        <section className="pg-card pg-panel" aria-label="Decision">
          <h3 className="pg-section-label">
            <span>Decision</span>
            <StatusTag status="resolved" />
          </h3>
          <dl className="pg-facts">
            <dt>Recorded</dt>
            <dd className="mono pg-queue-decided-text">{decided.decision}</dd>
            <dt>By</dt>
            <dd>
              <ActorTag actor={{ kind: "human", name: decided.resolvedBy }} size="sm" />
            </dd>
            <dt>At</dt>
            <dd className="mono">{decided.ts}</dd>
            {decided.taken !== null && (
              <>
                <dt>What the run did</dt>
                <dd className="pg-queue-taken">{takenWords(decided.taken)}</dd>
              </>
            )}
            <dt>Time to decide</dt>
            <dd className="pg-queue-review-time">{reviewTimeWords(decided)}</dd>
          </dl>
          {decided.flag !== null && (
            <p className="pg-queue-flag" role="note">
              Marked by the queue: {decided.flag}
            </p>
          )}
        </section>
      ) : (
        <>
          {supersededBy !== undefined && (
            <p className="pg-queue-superseded" role="note">
              {supersededWords(supersededBy)}
            </p>
          )}
          {children}
        </>
      )}
    </section>
  );
}
