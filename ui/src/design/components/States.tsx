import type { ReactNode } from "react";

/** Nothing to show yet, said plainly, with where it will come from. */
export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <section className="state state-empty" aria-label={title}>
      <h2 className="state-title">{title}</h2>
      {children !== undefined && <div className="state-body">{children}</div>}
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
 * A refusal names what was refused and why, and shows nothing partial in its place: a view
 * whose record was refused renders this and none of the record.
 */
export function ErrorState({ title, refusal }: { title: string; refusal: Refusal }) {
  return (
    <section className="state state-error" role="alert" aria-label={title}>
      <h2 className="state-title">{title}</h2>
      <p className="state-body">{refusal.error}</p>
      <dl className="state-context">
        <dt>status</dt>
        <dd className="mono">{refusal.status}</dd>
        {Object.entries(refusal.context).map(([key, value]) => (
          <div key={key} className="state-context-row">
            <dt>{key}</dt>
            <dd className="mono">{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

/** Reading a record: skeletons keep the layout, and no number appears until it is read whole. */
export function LoadingState({ reading }: { reading: string }) {
  return (
    <section className="state state-loading" aria-busy="true" aria-label={`Reading ${reading}`}>
      <p className="state-body">
        Reading <span className="mono">{reading}</span>…
      </p>
      <div className="skeleton" />
      <div className="skeleton skeleton-short" />
    </section>
  );
}
