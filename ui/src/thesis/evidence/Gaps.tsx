/**
 * The two gaps, each time they were measured: each role's trend as a person published it from
 * the trend's one reader. Per role, a small chart and the table it is drawn from: every ISO week
 * from the first measurement to the day the trend was read, a week with none said so; each
 * measurement's two gaps in percentage points with their intervals, the tiers' rates as the
 * reader wrote them, the task version, how often that version was measured, and what the reader
 * says beside the line (a version seen since, or why its numbers are withheld).
 *
 * The chart draws one point per gap and never a line through them: the reader computes no trend,
 * so none is drawn and no direction is claimed, whatever the number of points. Only the gaps'
 * own values are drawn, scaled to the chart; nothing else is computed here.
 */
import { EmptyState } from "../../design/components/status/States";
import type { Gap, GapLine, GapTrend, GapWeek, RoleTrend, TierCount } from "./api";
import { ShortId } from "./parts";
import { EVIDENCE_COPY } from "./words";

/** The two gaps, in the order the table and the chart show them. */
const GAPS = ["reward_hacking", "optimiser_overfit"] as const;
type GapKind = (typeof GAPS)[number];

function gapOf(line: GapLine, kind: GapKind): Gap | null {
  if (line.numbers === null) return null;
  return kind === "reward_hacking" ? line.numbers.rewardHacking : line.numbers.optimiserOverfit;
}

/** A fraction of a rate in percentage points, signed, one decimal: "+50.0", "−12.5", "0.0". */
export function points(fraction: number): string {
  const shown = (Math.abs(fraction) * 100).toFixed(1);
  if (shown === "0.0") return shown;
  return `${fraction < 0 ? "−" : "+"}${shown}`;
}

/** An ISO week in words: "2026-W45" reads "Week 45, 2026". */
export function weekWords(week: string): string {
  const found = /^(\d{4})-W(\d{2})$/.exec(week);
  if (found === null) return week;
  return `${EVIDENCE_COPY.week} ${String(Number(found[2]))}, ${found[1] ?? ""}`;
}

/** When the trend was read, in words: its day, its time to the minute and its zone. */
export function readAtWords(readAt: string): string {
  const found = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(?::\d{2}(?:\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/.exec(
    readAt,
  );
  if (found === null) return EVIDENCE_COPY.readAtAsSent(readAt);
  const zone = found[3] === "Z" || found[3] === "+00:00" ? "UTC" : `UTC${found[3] ?? ""}`;
  return EVIDENCE_COPY.readAt(found[1] ?? "", found[2] ?? "", zone);
}

// -- the chart -----------------------------------------------------------------------------------

const WIDTH = 640;
const HEIGHT = 240;
const LEFT = 56;
const RIGHT = 16;
const TOP = 16;
const BOTTOM = 40;
/** The tick steps tried, in points, smallest first: the first that gives five steps or fewer. */
const STEPS = [1, 2, 5, 10, 20, 25, 50, 100];

interface Point {
  readonly key: string;
  readonly slot: number;
  readonly kind: GapKind;
  readonly offset: number;
  readonly gap: Gap;
}

function pointsOf(weeks: readonly GapWeek[]): Point[] {
  return weeks.flatMap((week, slot) =>
    week.lines.flatMap((line, i) =>
      GAPS.flatMap((kind, k) => {
        const gap = gapOf(line, kind);
        if (gap === null) return [];
        const offset = (k === 0 ? -7 : 7) + i * 3;
        const key = i === 0 ? `${week.week}:${kind}` : `${week.week}:${kind}:${String(i)}`;
        return [{ key, slot, kind, offset, gap }];
      }),
    ),
  );
}

function stepOf(low: number, high: number): number {
  return STEPS.find((s) => (high - low) / s <= 5) ?? 100;
}

/** The y range in points: every value drawn and zero, widened to at least ten points. */
function range(drawn: readonly Point[]): [number, number] {
  const values = [0, ...drawn.flatMap((p) => [p.gap.gap, ...(p.gap.interval ?? [])])].map(
    (v) => v * 100,
  );
  let low = Math.min(...values);
  let high = Math.max(...values);
  if (high - low < 10) {
    const middle = (high + low) / 2;
    low = middle - 5;
    high = middle + 5;
  }
  const step = stepOf(low, high);
  return [Math.floor(low / step) * step, Math.ceil(high / step) * step];
}

function ticksOf(low: number, high: number): number[] {
  const step = stepOf(low, high);
  const found: number[] = [];
  for (let v = low; v <= high + 1e-9; v += step) found.push(Math.round(v * 100) / 100);
  return found;
}

function Whisker({
  cx,
  low,
  high,
}: {
  readonly cx: number;
  readonly low: number;
  readonly high: number;
}) {
  return (
    <>
      <line data-part="whisker" x1={cx} x2={cx} y1={low} y2={high} />
      <line data-part="whisker" x1={cx - 3} x2={cx + 3} y1={low} y2={low} />
      <line data-part="whisker" x1={cx - 3} x2={cx + 3} y1={high} y2={high} />
    </>
  );
}

function Chart({
  weeks,
  drawn,
}: {
  readonly weeks: readonly GapWeek[];
  readonly drawn: readonly Point[];
}) {
  const [low, high] = range(drawn);
  const y = (pts: number) => TOP + ((high - pts) / (high - low)) * (HEIGHT - TOP - BOTTOM);
  const band = (WIDTH - LEFT - RIGHT) / weeks.length;
  const x = (slot: number) => LEFT + band * (slot + 0.5);
  return (
    <svg
      className="evidence-chart"
      viewBox={`0 0 ${String(WIDTH)} ${String(HEIGHT)}`}
      role="img"
      aria-label={EVIDENCE_COPY.chartLabel}
    >
      <line data-part="axis" x1={LEFT} x2={LEFT} y1={TOP} y2={HEIGHT - BOTTOM} />
      <line
        data-part="axis"
        x1={LEFT}
        x2={WIDTH - RIGHT}
        y1={HEIGHT - BOTTOM}
        y2={HEIGHT - BOTTOM}
      />
      {ticksOf(low, high).map((tick) => (
        <g key={tick}>
          <line data-part="tick" x1={LEFT - 4} x2={LEFT} y1={y(tick)} y2={y(tick)} />
          <text className="evidence-chart-label" x={LEFT - 8} y={y(tick) + 4} textAnchor="end">
            {points(tick / 100)}
          </text>
        </g>
      ))}
      <line data-part="zero" x1={LEFT} x2={WIDTH - RIGHT} y1={y(0)} y2={y(0)} />
      {weeks.map((week, slot) => (
        <text
          key={week.week}
          className="evidence-chart-label"
          data-missing={week.missing ? "true" : undefined}
          x={x(slot)}
          y={HEIGHT - BOTTOM + 18}
          textAnchor="middle"
        >
          {`W${week.week.slice(6)}`}
        </text>
      ))}
      {drawn.map((p) => {
        const cx = x(p.slot) + p.offset;
        const cy = y(p.gap.gap * 100);
        return (
          <g key={p.key} className="evidence-gap-mark" data-kind={p.kind}>
            {p.gap.interval !== null && (
              <Whisker cx={cx} low={y(p.gap.interval[0] * 100)} high={y(p.gap.interval[1] * 100)} />
            )}
            {p.kind === "reward_hacking" ? (
              <circle data-point={p.key} cx={cx} cy={cy} r={4.5} />
            ) : (
              <rect data-point={p.key} x={cx - 4} y={cy - 4} width={8} height={8} />
            )}
          </g>
        );
      })}
    </svg>
  );
}

/** What the points are, said plainly: one point is no trend, and none is ever claimed. */
function honesty(measured: number): string {
  if (measured === 0) return EVIDENCE_COPY.noNumbers;
  if (measured === 1) return EVIDENCE_COPY.onePoint;
  return EVIDENCE_COPY.pointsAlone(measured);
}

// -- the table -----------------------------------------------------------------------------------

function GapCell({ gap, kind }: { readonly gap: Gap | null; readonly kind: GapKind }) {
  if (gap === null)
    return (
      <td data-gap={kind} data-measured="false">
        <span className="evidence-reason">{EVIDENCE_COPY.notMeasured}</span>
      </td>
    );
  return (
    <td data-gap={kind}>
      <span className="evidence-label">
        {points(gap.gap)} {EVIDENCE_COPY.pointsUnit}
      </span>
      <span className="evidence-reason">
        {gap.interval === null
          ? gap.words
          : EVIDENCE_COPY.interval(points(gap.interval[0]), points(gap.interval[1]))}
      </span>
      {gap.interval !== null && <span className="evidence-reason">{gap.words}</span>}
      {gap.label !== null && <span className="evidence-reason">{gap.label}</span>}
    </td>
  );
}

function RateCell({ count }: { readonly count: TierCount | null }) {
  if (count === null)
    return (
      <td>
        <span className="evidence-reason">{EVIDENCE_COPY.notMeasuredTier}</span>
      </td>
    );
  return (
    <td>
      <span className="evidence-value">{count.rate}</span>
      {(count.unscored > 0 || count.flaky > 0) && (
        <span className="evidence-reason">
          {EVIDENCE_COPY.failsCounted(count.unscored, count.flaky)}
        </span>
      )}
    </td>
  );
}

function LineRow({ line, week }: { readonly line: GapLine; readonly week: string }) {
  return (
    <tr data-week={week}>
      <th scope="row">{weekWords(week)}</th>
      <td data-version="">
        <ShortId value={line.version} />
      </td>
      {line.numbers === null ? (
        <td colSpan={5}>
          <span className="evidence-reason">
            {EVIDENCE_COPY.numbersWithheld} {line.unverified}
          </span>
        </td>
      ) : (
        <>
          <GapCell gap={line.numbers.rewardHacking} kind="reward_hacking" />
          <GapCell gap={line.numbers.optimiserOverfit} kind="optimiser_overfit" />
          <RateCell count={line.numbers.visible} />
          <RateCell count={line.numbers.validation} />
          <RateCell count={line.numbers.heldOut} />
        </>
      )}
      <td className="evidence-value">{String(line.measurements)}</td>
      <td>
        {line.exposedSince !== null && (
          <p className="evidence-note evidence-warn" data-note="exposed">
            {line.exposedSince}
          </p>
        )}
      </td>
    </tr>
  );
}

function Table({ role, weeks }: { readonly role: string; readonly weeks: readonly GapWeek[] }) {
  return (
    <div
      className="pg-table-wrap"
      role="region"
      aria-label={EVIDENCE_COPY.tableLabel(role)}
      tabIndex={0}
    >
      <table className="pg-table evidence-gaps">
        <thead>
          <tr>
            <th scope="col">{EVIDENCE_COPY.week}</th>
            <th scope="col">{EVIDENCE_COPY.version}</th>
            <th scope="col">
              {EVIDENCE_COPY.rewardHacking}
              <span className="evidence-view">{EVIDENCE_COPY.rewardHackingSays}</span>
            </th>
            <th scope="col">
              {EVIDENCE_COPY.optimiserOverfit}
              <span className="evidence-view">{EVIDENCE_COPY.optimiserOverfitSays}</span>
            </th>
            <th scope="col">{EVIDENCE_COPY.visibleRate}</th>
            <th scope="col">{EVIDENCE_COPY.validationRate}</th>
            <th scope="col">{EVIDENCE_COPY.heldOutRate}</th>
            <th scope="col">{EVIDENCE_COPY.measurements}</th>
            <th scope="col">{EVIDENCE_COPY.noteColumn}</th>
          </tr>
        </thead>
        <tbody>
          {weeks.flatMap((week) =>
            week.missing
              ? [
                  <tr key={week.week} data-week={week.week} data-missing="true">
                    <th scope="row">{weekWords(week.week)}</th>
                    <td colSpan={8}>
                      <span className="evidence-reason">{EVIDENCE_COPY.noMeasurement}</span>
                    </td>
                  </tr>,
                ]
              : week.lines.map((line, i) => (
                  <LineRow key={`${week.week}:${String(i)}`} line={line} week={week.week} />
                )),
          )}
        </tbody>
      </table>
    </div>
  );
}

// -- a role --------------------------------------------------------------------------------------

function Legend() {
  return (
    <p className="evidence-legend">
      <span className="evidence-legend-item" data-kind="reward_hacking">
        <span className="evidence-swatch" aria-hidden="true" />
        {EVIDENCE_COPY.rewardHacking}: {EVIDENCE_COPY.rewardHackingSays}
      </span>
      <span className="evidence-legend-item" data-kind="optimiser_overfit">
        <span className="evidence-swatch" aria-hidden="true" />
        {EVIDENCE_COPY.optimiserOverfit}: {EVIDENCE_COPY.optimiserOverfitSays}
      </span>
    </p>
  );
}

function RoleBody({ trend }: { readonly trend: RoleTrend }) {
  if (trend.state === "none")
    return (
      <EmptyState title={EVIDENCE_COPY.noTrend} icon="microscope">
        {EVIDENCE_COPY.firstPoint}
      </EmptyState>
    );
  if (trend.state === "refused")
    return (
      <div className="pg-state pg-state-error evidence-trend-refused">
        <h3 className="pg-state-title">{EVIDENCE_COPY.trendRefused(trend.role)}</h3>
        <p className="pg-state-body">
          {EVIDENCE_COPY.readerWords} {trend.error}
        </p>
        <p className="evidence-note">{EVIDENCE_COPY.noNumberOfIt}</p>
        {trend.readAt !== null && <p className="evidence-note">{readAtWords(trend.readAt)}</p>}
      </div>
    );
  if (trend.weeks.length === 0)
    return (
      <EmptyState title={EVIDENCE_COPY.noPoint} icon="microscope">
        {EVIDENCE_COPY.firstPoint} {readAtWords(trend.readAt)}
      </EmptyState>
    );
  const drawn = pointsOf(trend.weeks);
  const measured = trend.weeks.reduce(
    (n, week) => n + week.lines.filter((line) => line.numbers !== null).length,
    0,
  );
  return (
    <>
      <p className="evidence-note">
        {readAtWords(trend.readAt)} {EVIDENCE_COPY.asRead}
      </p>
      {drawn.length > 0 ? (
        <figure className="evidence-figure">
          <Legend />
          <Chart weeks={trend.weeks} drawn={drawn} />
          <figcaption className="evidence-note">{honesty(measured)}</figcaption>
        </figure>
      ) : (
        <p className="evidence-note">{honesty(measured)}</p>
      )}
      <Table role={trend.role} weeks={trend.weeks} />
    </>
  );
}

export function GapsTab({ trend }: { readonly trend: GapTrend }) {
  return (
    <>
      <p className="evidence-note">{EVIDENCE_COPY.gapsLead}</p>
      {trend.roles.map((role) => (
        <section
          key={role.role}
          className="pg-card pg-panel evidence-kind"
          aria-label={EVIDENCE_COPY.roleTitle(role.role)}
          data-role={role.role}
          data-source={`gap trend · ${role.role}`}
        >
          <h2 className="pg-panel-title">{EVIDENCE_COPY.roleTitle(role.role)}</h2>
          <RoleBody trend={role} />
        </section>
      ))}
    </>
  );
}
