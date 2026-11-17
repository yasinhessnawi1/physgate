/** A timeline row drawn: its time, its actor, its sentence (with any value it names) and its end. */
import { createContext, useContext } from "react";

import { Quantity } from "../../design/components/data/Quantity";
import { TimelineRow } from "../../design/components/timeline/TimelineRow";
import { GateModeBadge, GateOutcome } from "../../design/components/verdict/GateMode";
import { VerdictBadge } from "../../design/components/verdict/VerdictBadge";
import { clockTime, utc } from "../../words/runs";
import type { Row, RowEnd } from "./rows";

/** Whether rows show their internal ids: off unless a screen's toggle turns it on. */
export const IdsShownContext = createContext(false);

/** A session's id as recorded: a UUID, alone or after the word "session". */
const SESSION_ID = /^(session )?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/**
 * A row's meta line, its internal ids dropped unless ``ids``: the row's own subtask id (its name
 * leads the row), a session's id and the run's id (the header names the run). What is not an id,
 * a node, a quantity, a count or a cause, stays.
 */
export function metaShown(row: Row, ids: boolean): string {
  if (ids) return row.meta;
  return row.meta
    .split(" · ")
    .filter(
      (part) =>
        part !== row.subtask &&
        !SESSION_ID.test(part) &&
        !(row.subtask === null && /^run \S+$/.test(part)),
    )
    .join(" · ");
}

function End({ end }: { readonly end: RowEnd | null }) {
  if (end === null) return null;
  if (end.kind === "gate") return <GateOutcome mode={end.mode} outcome={end.outcome} />;
  // A mode the interface does not know is shown as written, with no verdict colour: whether the
  // outcome was enforced is not known, so it is neither a filled verdict nor a would-be one.
  if (end.kind === "gate-unknown-mode")
    return (
      <span className="pg-badge pg-gate-unknown">
        {end.outcome} · gate mode <span className="mono">{end.mode}</span>
      </span>
    );
  if (end.kind === "gate-off") return <GateModeBadge mode="off" />;
  if (end.kind === "no-verdict")
    return <span className="pg-badge pg-no-verdict">No verdict recorded</span>;
  if (end.verdict === "pass" || end.verdict === "fail")
    return <VerdictBadge verdict={end.verdict} />;
  return <span className="pg-status">Review: {end.verdict}</span>;
}

export function RowView({
  row,
  selected,
  onSelect,
}: {
  readonly row: Row;
  readonly selected?: boolean;
  readonly onSelect?: () => void;
}) {
  const ids = useContext(IdsShownContext);
  const shown = (
    <TimelineRow
      time={clockTime(row.ts)}
      {...(row.actor === null ? {} : { actor: row.actor })}
      depth={row.depth}
      kind={row.end?.kind ?? "event"}
      what={
        <>
          {row.sentence}
          {row.value !== null && (
            <span className="pg-row-value">
              {row.valueInline === true ? " " : " · recorded "}
              <Quantity {...row.value} />
            </span>
          )}
        </>
      }
      meta={
        <>
          <span title={utc(row.ts)}>{metaShown(row, ids)}</span>
        </>
      }
      end={<End end={row.end} />}
      {...(selected === undefined ? {} : { selected })}
      {...(onSelect === undefined ? {} : { onSelect })}
    />
  );
  if (row.more === null) return shown;
  // The rest of a long finding folds under the row, beside its button and not inside it: a
  // control inside a button is neither valid nor reachable.
  return (
    <>
      {shown}
      <details className={`pg-trow-more pg-trow-more-${String(row.depth)}`}>
        <summary>{row.moreLabel ?? "Show the rest"}</summary>
        <p className="pg-trow-more-text">{row.more}</p>
      </details>
    </>
  );
}
