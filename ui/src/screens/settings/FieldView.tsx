/**
 * How one recorded field is drawn: its value, the words for its absence, or the sentence saying it
 * could not be read, in its own row. Nothing here fills a value in.
 */
import type { ReactNode } from "react";

import type { Field } from "../../api/fields";
import { refusedValue, SETTINGS_COPY, type Worded } from "../../words/settings";

/** A field the record does not hold: "not recorded by this run", or the harness's own "none". */
export function Absent({
  missing,
  none,
}: {
  readonly missing: boolean;
  readonly none?: string | undefined;
}) {
  return (
    <span className="pg-muted" data-absent="">
      {missing ? SETTINGS_COPY.notRecorded : (none ?? SETTINGS_COPY.notRecorded)}
    </span>
  );
}

export function Refused({ reason }: { readonly reason: string }) {
  return <span className="pg-refused">{refusedValue(reason)}</span>;
}

/** ``field``'s value drawn by ``children``, or its absence, or its refusal. */
export function Shown<T>({
  field,
  none,
  children,
}: {
  readonly field: Field<T>;
  /** The words for the harness's own "none recorded"; a missing key always reads not recorded. */
  readonly none?: string | undefined;
  readonly children: (value: T) => ReactNode;
}) {
  if (field.kind === "read") return <>{children(field.value)}</>;
  if (field.kind === "absent") return <Absent missing={field.missing} none={none} />;
  return <Refused reason={field.reason} />;
}

/** Known words as words; a value these words do not know as written, in mono and neutral ink. */
export function Words({ worded }: { readonly worded: Worded }) {
  return worded.kind === "known" ? (
    <>{worded.words}</>
  ) : (
    <span className="mono pg-as-written">{worded.value}</span>
  );
}

/** One row of a facts list, named for the field it draws. */
export function Fact({
  field,
  label,
  children,
}: {
  readonly field: string;
  readonly label: ReactNode;
  readonly children: ReactNode;
}) {
  return (
    <div className="pg-fact" data-field={field}>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}
