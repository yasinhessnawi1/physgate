/**
 * One staged candidate in the inspector: what promoting it would do, from promotion's own code on
 * the server; the destination's size and digest now and after; the changed lines, added ones in
 * the accent and removed ones struck through; and, in words, that promotion is a person's act at
 * a terminal. Nothing here acts: no control promotes or discards, and no command is shown.
 */
import {
  type CandidateDetail,
  candidateDetail,
  candidateRoute,
  type Fingerprint,
} from "../../api/library";
import { Id } from "../../design/components/data/Id";
import { Quantity } from "../../design/components/data/Quantity";
import { sourceAttribute } from "../../design/components/data/source";
import { Inspector, InspectorSection } from "../../design/components/layout/Inspector";
import { ErrorState, LoadingState } from "../../design/components/status/States";
import { candidateLabel, EFFECT_WORDS, LIBRARY_COPY, writtenWords } from "../../words/library";
import { useJson } from "../common/read";
import { diffRows } from "./model";
import { RoleTag, useFocusOnOpen } from "./parts";

function Print({ what, print }: { readonly what: string; readonly print: Fingerprint | null }) {
  return (
    <dd data-fact={what}>
      {print === null ? (
        <span className="pg-muted">{LIBRARY_COPY.noFileYet}</span>
      ) : (
        <span className="pg-lib-print">
          <Quantity value={print.size} unit="B" />
          <Id value={print.sha256} />
        </span>
      )}
    </dd>
  );
}

function ChangedLines({ lines }: { readonly lines: readonly string[] }) {
  const rows = diffRows(lines);
  if (rows.length === 0) return <p className="pg-muted">{LIBRARY_COPY.noChange}</p>;
  return (
    <div className="pg-lib-diff" role="group" aria-label="Changed lines">
      {rows.map((row, i) =>
        row.kind === "added" ? (
          <ins key={i} className="pg-lib-diff-line">
            {row.text}
          </ins>
        ) : row.kind === "removed" ? (
          <del key={i} className="pg-lib-diff-line">
            {row.text}
          </del>
        ) : (
          <span
            key={i}
            className={`pg-lib-diff-line${row.kind === "hunk" ? " pg-lib-diff-hunk" : ""}`}
          >
            {row.text}
          </span>
        ),
      )}
    </div>
  );
}

function Detail({ detail }: { readonly detail: CandidateDetail }) {
  return (
    <div data-source={sourceAttribute({ id: detail.destination, commit: null })}>
      <InspectorSection label="What promoting it would do">
        <p className="pg-lib-effect">{EFFECT_WORDS[detail.effect]}</p>
        <Id value={detail.destination} />
        <dl className="pg-facts">
          <dt>Now</dt>
          <Print what="now" print={detail.now} />
          <dt>After</dt>
          <Print what="after" print={detail.after} />
        </dl>
      </InspectorSection>
      <InspectorSection label={LIBRARY_COPY.changedLines}>
        <ChangedLines lines={detail.lines} />
      </InspectorSection>
      <InspectorSection label="Promotion">
        <div className="pg-lib-promotion">
          <p>{LIBRARY_COPY.promotionBlock}</p>
          <dl className="pg-facts">
            <dt>{LIBRARY_COPY.candidate}</dt>
            <dd>
              <Id value={detail.candidate.candidateId} />
            </dd>
            <dt>Episode</dt>
            <dd>
              <Id value={detail.candidate.episodeId} copy={false} />
            </dd>
            <dt>Written</dt>
            <dd>{writtenWords(detail.candidate.written)}</dd>
          </dl>
        </div>
      </InspectorSection>
    </div>
  );
}

export function CandidateInspector({ id }: { readonly id: string }) {
  const read = useJson(candidateRoute(id), candidateDetail);
  const focus = useFocusOnOpen(id);
  const detail = read.result?.ok === true ? read.result.value : null;
  return (
    <Inspector
      label="Proposed change"
      crumbs={["Library", "Proposed"]}
      title={
        <span ref={focus} tabIndex={-1} className="pg-lib-focus">
          {detail === null
            ? "Proposed change"
            : candidateLabel(detail.kind, detail.candidate.replaces, detail.candidate.domain)}
        </span>
      }
      badges={detail === null ? undefined : <RoleTag role={detail.candidate.domain} />}
    >
      {read.result === null ? (
        <LoadingState reading={LIBRARY_COPY.reading} rows={3} />
      ) : !read.result.ok ? (
        <ErrorState
          title={LIBRARY_COPY.candidateError}
          {...read.result.refusal}
          route={read.route}
          onRetry={read.again}
        />
      ) : (
        <Detail detail={read.result.value} />
      )}
    </Inspector>
  );
}
