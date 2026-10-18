/** A timeline row drawn: its time, its actor, its sentence (with any value it names) and its end. */
import { Quantity } from "../../design/components/data/Quantity";
import { TimelineRow } from "../../design/components/timeline/TimelineRow";
import { GateModeBadge, GateOutcome } from "../../design/components/verdict/GateMode";
import { VerdictBadge } from "../../design/components/verdict/VerdictBadge";
import { clockTime, utc } from "../../words/runs";
import type { Row, RowEnd } from "./rows";

function End({ end }: { readonly end: RowEnd | null }) {
  if (end === null) return null;
  if (end.kind === "gate") return <GateOutcome mode={end.mode} outcome={end.outcome} />;
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
  return (
    <TimelineRow
      time={clockTime(row.ts)}
      actor={row.actor}
      depth={row.depth}
      kind={row.end?.kind ?? "event"}
      what={
        <>
          {row.sentence}
          {row.value !== null && (
            <span className="pg-row-value">
              {" · recorded "}
              <Quantity {...row.value} />
            </span>
          )}
        </>
      }
      meta={
        <>
          <span title={utc(row.ts)}>{row.meta}</span>
        </>
      }
      end={<End end={row.end} />}
      {...(selected === undefined ? {} : { selected })}
      {...(onSelect === undefined ? {} : { onSelect })}
    />
  );
}
