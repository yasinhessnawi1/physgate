/**
 * The library: what the next run from this checkout reads. Five sections, from the address:
 * standards, skills, the reviewers' rubrics (their promotion record only), what is waiting for
 * promotion, and the data-sheet ratings the gate checks values against. A row opens its record
 * in the inspector, and focus moves there.
 *
 * Everything here is read-only. Promotion is a person's act at a terminal; the page says so in
 * words, shows no command and has no control that acts.
 *
 * One read per section: the listing for the counts and the first three sections, the staged
 * list for the proposed changes (and one candidate when opened), the ratings for the last.
 */
import { useEffect } from "react";

import {
  type LibraryDocument,
  type LibraryListing,
  LIBRARY_ROUTE,
  libraryListing,
  PROMOTIONS_PATH,
  RATINGS_ROUTE,
  ratings as ratingsGuard,
} from "../../api/library";
import { Segmented } from "../../design/components/actions/Segmented";
import { Id } from "../../design/components/data/Id";
import { EmptyState, ErrorState, LoadingState } from "../../design/components/status/States";
import type { ViewProps } from "../../shell/header";
import { InspectorPortal } from "../../shell/inspector";
import { LIBRARY_COPY, libraryErrorTitle, promotionsCount, proposedTab } from "../../words/library";
import { useJson } from "../common/read";
import { CandidateInspector } from "./CandidateInspector";
import { DocumentInspector } from "./DocumentInspector";
import { DocumentsTable } from "./Documents";
import { type Open, openValue, parseOpen, parseTab, type Tab } from "./model";
import { go, withQuery } from "./parts";
import { Proposed } from "./Proposed";
import { RatingInspector } from "./RatingInspector";
import { RatingsSection } from "./Ratings";
import { RubricsTable } from "./Rubrics";

/** The server's answer when it was started with no library. */
const NO_LIBRARY = "this server reads no library";

function isRating(open: Open | null): open is Open & { kind: "range" | "envelope" | "store" } {
  return open?.kind === "range" || open?.kind === "envelope" || open?.kind === "store";
}

function Sections({
  listing,
  tab,
  open,
  query,
}: {
  readonly listing: LibraryListing;
  readonly tab: Tab;
  readonly open: Open | null;
  readonly query: URLSearchParams;
}) {
  const href = (next: Open) => withQuery(query, { open: openValue(next) });
  const fileHref = (d: LibraryDocument) => href({ kind: "file", file: d.kind, role: d.role });
  const selectedFile = open?.kind === "file" ? `${open.file}/${open.role}` : null;
  const ratings = useJson(tab === "ratings" || isRating(open) ? RATINGS_ROUTE : null, ratingsGuard);
  const ofKind = (kind: string) => listing.documents.filter((d) => d.kind === kind);
  const body =
    tab === "standards" ? (
      <DocumentsTable
        label="Standards"
        documents={ofKind("standards")}
        empty={LIBRARY_COPY.noStandards}
        hrefOpen={fileHref}
        selected={selectedFile}
      />
    ) : tab === "skills" ? (
      <DocumentsTable
        label="Skills"
        documents={ofKind("skill")}
        empty={LIBRARY_COPY.noSkills}
        hrefOpen={fileHref}
        selected={selectedFile}
      />
    ) : tab === "rubrics" ? (
      <RubricsTable rubrics={listing.rubrics} />
    ) : tab === "proposed" ? (
      <Proposed
        hrefOpen={(id) => href({ kind: "candidate", id })}
        selected={open?.kind === "candidate" ? open.id : null}
      />
    ) : ratings.result === null ? (
      <LoadingState reading={LIBRARY_COPY.reading} />
    ) : !ratings.result.ok ? (
      <ErrorState
        title={LIBRARY_COPY.ratingsError}
        {...ratings.result.refusal}
        route={ratings.route}
        onRetry={ratings.again}
      />
    ) : (
      <RatingsSection ratings={ratings.result.value} hrefOpen={href} />
    );
  const inspector =
    open === null ? null : open.kind === "file" ? (
      <DocumentInspector key={`${open.file}/${open.role}`} kind={open.file} role={open.role} />
    ) : open.kind === "candidate" ? (
      <CandidateInspector key={open.id} id={open.id} />
    ) : ratings.result?.ok === true ? (
      <RatingInspector
        open={open}
        ratings={ratings.result.value}
        hrefFile={(role) => href({ kind: "file", file: "bounds", role })}
      />
    ) : null;
  return (
    <>
      <Segmented
        label="Library sections"
        value={tab}
        onChange={(next) => {
          go(withQuery(query, { tab: next === "standards" ? null : next, open: null }));
        }}
        options={[
          { value: "standards", label: "Standards" },
          { value: "skills", label: "Skills" },
          { value: "rubrics", label: "Reviewer rubrics" },
          { value: "proposed", label: proposedTab(listing.staged) },
          { value: "ratings", label: "Data-sheet ratings" },
        ]}
      />
      {body}
      {inspector !== null && <InspectorPortal>{inspector}</InspectorPortal>}
    </>
  );
}

export default function Library({ setHeader, query }: ViewProps) {
  useEffect(() => {
    setHeader({ title: "Library" });
  }, [setHeader]);
  const read = useJson(LIBRARY_ROUTE, libraryListing);
  const tab = parseTab(query.get("tab"));
  const open = parseOpen(query.get("open"));
  const lede = <p className="pg-screen-lead">{LIBRARY_COPY.lede}</p>;
  if (read.result === null)
    return (
      <div className="pg-screen pg-library">
        {lede}
        <LoadingState reading={LIBRARY_COPY.reading} />
      </div>
    );
  if (!read.result.ok) {
    const { refusal } = read.result;
    return (
      <div className="pg-screen pg-library">
        {lede}
        {refusal.status === 404 && refusal.error === NO_LIBRARY ? (
          <EmptyState title={LIBRARY_COPY.noLibraryTitle} icon="library">
            {LIBRARY_COPY.noLibrary}
          </EmptyState>
        ) : (
          <ErrorState
            title={libraryErrorTitle(refusal.error)}
            {...refusal}
            route={read.route}
            onRetry={read.again}
          />
        )}
      </div>
    );
  }
  return (
    <div className="pg-screen pg-library">
      <header className="pg-screen-head">
        {lede}
        <span className="pg-lib-count">
          {promotionsCount(read.result.value.promotions)}
          <Id value={PROMOTIONS_PATH} copy={false} />
        </span>
      </header>
      <Sections listing={read.result.value} tab={tab} open={open} query={query} />
    </div>
  );
}
