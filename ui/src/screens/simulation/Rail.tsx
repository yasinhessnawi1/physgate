/**
 * The rail: the run's subtasks, each attempt with its neutral tag, and under the chosen attempt
 * its records grouped by the role's own group, then what its sessions set aside and what a later
 * session recorded again. Every row is a link, so the choice lives in the address.
 */
import type { Result } from "../../api/client";
import type { AttemptRecords, ListedAttempt, SeriesListing, Unread } from "../../api/series";
import { Id } from "../../design/components/data/Id";
import { Quantity } from "../../design/components/data/Quantity";
import { Term } from "../../design/components/help/Term";
import { ErrorState, LoadingState } from "../../design/components/status/States";
import {
  ATTEMPT_TAG_WORDS,
  axisWords,
  heldWords,
  recordsCount,
  SERIES_COPY,
  setAsideWords,
  supersededWords,
  unreadWords,
} from "../../words/series";
import { recordAddress } from "../common/addresses";
import { attemptTag, groupsOf, subtasksOf } from "./model";
import { Tag } from "./Tag";

const TAG_ICONS = {
  merged: "git-pull-request-arrow",
  "refused-before-gate": "ban",
  "not-merged": "minus",
  "in-progress": "clock",
} as const;

function RecordRows({
  records,
  run,
  attempt,
  chosen,
}: {
  readonly records: AttemptRecords;
  readonly run: string;
  readonly attempt: ListedAttempt;
  readonly chosen: string | null;
}) {
  return (
    <>
      {groupsOf(records.records).map(({ key, label, records: rows }) => (
        <section key={key} className="pg-sim-group" aria-label={label}>
          <h4 className="pg-sim-group-title">{label}</h4>
          <ul className="pg-sim-records">
            {rows.map((row, i) => {
              const id = row.recordId;
              const on = id !== null && id === chosen;
              const href =
                id === null
                  ? undefined
                  : recordAddress(run, attempt.subtaskId, attempt.attempt, id);
              return (
                <li key={id ?? `unread-${String(i)}`}>
                  <a
                    className={
                      on ? "pg-sim-record-link pg-sim-on pg-hit" : "pg-sim-record-link pg-hit"
                    }
                    aria-current={on ? "true" : undefined}
                    href={href}
                  >
                    {row.kind === "shown" ? (
                      <>
                        <span className="pg-sim-record-title">{row.title}</span>
                        <span className="pg-sim-record-meta">
                          {axisWords(row.axis)} · <Quantity value={row.x.samples} unit="samples" />
                        </span>
                      </>
                    ) : row.kind === "refused" ? (
                      <>
                        <span className="pg-sim-record-title">
                          {row.refused === "seal" ? (
                            <Tag icon="ban" kind="not-what-was-sealed">
                              {SERIES_COPY.notWhatWasSealed}
                            </Tag>
                          ) : row.refused === "format" ? (
                            heldWords(row.error)
                          ) : (
                            `${row.refused}: ${row.error}`
                          )}
                        </span>
                        <Id value={row.recordId} copy={false} />
                      </>
                    ) : (
                      <span className="pg-sim-record-title">{unreadWords(row.error)}</span>
                    )}
                  </a>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </>
  );
}

function AttemptExtras({ attempt }: { readonly attempt: ListedAttempt }) {
  return (
    <>
      {attempt.setAside.length > 0 && (
        <details className="pg-details pg-sim-fold">
          <summary>
            {SERIES_COPY.setAsideTitle} · {attempt.setAside.length}
          </summary>
          <p className="pg-panel-note">
            <Term term="set-aside" />
          </p>
          <ul className="pg-sim-notes">
            {attempt.setAside.map((entry, i) =>
              entry.kind === "unread" ? (
                <li key={`u${String(i)}`}>{unreadWords(entry.error)}</li>
              ) : (
                <li key={`${entry.sessionId}/${entry.name}/${String(i)}`}>
                  <span>{setAsideWords(entry.how, entry.reason)}</span>
                  <span className="pg-sim-file">{entry.name}</span>
                </li>
              ),
            )}
          </ul>
        </details>
      )}
      {attempt.superseded.length > 0 && (
        <details className="pg-details pg-sim-fold">
          <summary>
            {SERIES_COPY.supersededTitle} · {attempt.superseded.length}
          </summary>
          <p className="pg-panel-note">
            <Term term="superseded" />
          </p>
          <ul className="pg-sim-notes">
            {attempt.superseded.map((entry, i) => (
              <li key={`s${String(i)}`}>
                {entry.kind === "unread"
                  ? unreadWords(entry.error)
                  : supersededWords(entry.recordId)}
              </li>
            ))}
          </ul>
        </details>
      )}
    </>
  );
}

export function Rail({
  listing,
  run,
  chosen,
  record,
  records,
  recordsRoute,
  onRecordsAgain,
  names,
  going,
}: {
  readonly listing: SeriesListing;
  readonly run: string;
  readonly chosen: ListedAttempt | null;
  readonly record: string | null;
  /** The chosen attempt's records; ``null`` while read, or when it sealed none. */
  readonly records: Result<AttemptRecords> | null;
  readonly recordsRoute: string | null;
  readonly onRecordsAgain: () => void;
  readonly names: ReadonlyMap<string, string>;
  readonly going: boolean;
}) {
  const unread = listing.attempts.filter((a): a is Unread => a.kind === "unread");
  return (
    <nav className="pg-sim-rail" aria-label="Simulation records">
      <h2 className="pg-sim-rail-title">
        <Term term="simulation-record">{SERIES_COPY.railTitle}</Term>
      </h2>
      {subtasksOf(listing).map(({ subtaskId, attempts }) => {
        const open = chosen !== null && chosen.subtaskId === subtaskId ? chosen : null;
        return (
          <section
            key={subtaskId}
            className="pg-sim-subtask"
            aria-label={names.get(subtaskId) ?? `Subtask ${subtaskId}`}
          >
            <h3 className="pg-sim-subtask-title">
              <span>{names.get(subtaskId) ?? "Subtask"}</span>
              <Id value={subtaskId} copy={false} />
            </h3>
            <ul
              className="pg-sim-attempts"
              aria-label={`Attempts of ${names.get(subtaskId) ?? subtaskId}`}
            >
              {attempts.map((attempt) => {
                const on = open !== null && open.attempt === attempt.attempt;
                const tag = attemptTag(attempt, attempts, going);
                return (
                  <li key={attempt.attempt}>
                    <a
                      className={on ? "pg-sim-attempt pg-sim-on pg-hit" : "pg-sim-attempt pg-hit"}
                      aria-current={on ? "true" : undefined}
                      href={recordAddress(run, subtaskId, attempt.attempt, null)}
                    >
                      <span>Attempt {attempt.attempt}</span>
                      <Tag icon={TAG_ICONS[tag]} kind={tag}>
                        {ATTEMPT_TAG_WORDS[tag]}
                      </Tag>
                      <span className="pg-sim-count">
                        {recordsCount(
                          attempt.records.filter((r) => r.kind === "sealed").length,
                          going,
                        )}
                      </span>
                    </a>
                  </li>
                );
              })}
            </ul>
            {open !== null && (
              <div className="pg-sim-attempt-body">
                {open.records.length === 0 ? (
                  <p className="pg-panel-empty">{SERIES_COPY.noSealed}</p>
                ) : records === null ? (
                  <LoadingState reading={SERIES_COPY.readingRun} rows={1} />
                ) : !records.ok ? (
                  <ErrorState
                    title={SERIES_COPY.attemptError}
                    {...records.refusal}
                    route={recordsRoute}
                    onRetry={onRecordsAgain}
                  />
                ) : (
                  <RecordRows records={records.value} run={run} attempt={open} chosen={record} />
                )}
                <AttemptExtras attempt={open} />
              </div>
            )}
          </section>
        );
      })}
      {unread.map((entry, i) => (
        <p key={`unread-${String(i)}`} className="pg-sim-unread">
          {SERIES_COPY.unreadAttempt}: {entry.error}
        </p>
      ))}
    </nav>
  );
}
