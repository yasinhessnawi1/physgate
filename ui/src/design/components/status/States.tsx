import type { ReactNode } from "react";

import { Icon, type IconName } from "../icons/Icon";

/** Nothing to show yet, said plainly, with where it will come from. Dashed: nothing recorded. */
export function EmptyState({
  title,
  children,
  icon = "inbox",
  action,
}: {
  readonly title: string;
  readonly children?: ReactNode;
  readonly icon?: IconName;
  readonly action?: ReactNode;
}) {
  return (
    <section className="pg-state pg-state-empty" aria-label={title}>
      <h2 className="pg-state-title">
        <Icon name={icon} />
        {title}
      </h2>
      {children !== undefined && <div className="pg-state-body">{children}</div>}
      {action}
    </section>
  );
}

/** What a refusal carried: the server's message and its context, shown as they are. */
export interface Refusal {
  readonly status: number;
  readonly error: string;
  readonly context: Readonly<Record<string, string>>;
}

/**
 * A refusal opens with a sentence naming what was refused, then the server's reason, its status
 * and its context under "Details". It shows nothing partial in place of the record: a view whose
 * record was refused renders this and none of the record.
 */
export function ErrorState({
  title,
  error,
  status,
  context = {},
}: {
  /** The sentence that leads: what could not be shown, in plain words. */
  readonly title: string;
  /** The server's reason, as it came. */
  readonly error: string;
  readonly status?: number;
  readonly context?: Readonly<Record<string, string>>;
}) {
  return (
    <section className="pg-state pg-state-error" role="alert" aria-label={title}>
      <h2 className="pg-state-title">
        <Icon name="octagon-x" />
        {title}
      </h2>
      <p className="pg-state-body">{error}</p>
      <details className="pg-details" open>
        <summary>Details</summary>
        <dl className="pg-state-context">
          <dt>reason</dt>
          <dd>{error}</dd>
          {status !== undefined && (
            <>
              <dt>status</dt>
              <dd>{status}</dd>
            </>
          )}
          {Object.entries(context).map(([key, value]) => (
            <div key={key} className="pg-state-context-row">
              <dt>{key}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      </details>
    </section>
  );
}

/** Reading a record: skeletons keep the layout, and no number appears until it is read whole. */
export function LoadingState({
  reading,
  rows = 2,
}: {
  readonly reading: string;
  readonly rows?: number;
}) {
  return (
    <section
      className="pg-state pg-state-loading"
      aria-busy="true"
      aria-label={`Reading ${reading}`}
    >
      <p className="pg-state-body">
        Reading <span className="mono">{reading}</span>…
      </p>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className={i === rows - 1 ? "pg-skeleton pg-skeleton-short" : "pg-skeleton"} />
      ))}
    </section>
  );
}
