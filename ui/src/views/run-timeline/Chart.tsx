import { ScrollTable } from "../../design/components/ScrollTable";
import { useLayoutEffect, useRef } from "react";

import type { StepTiming } from "../../api/run";
import { Quantity } from "../../design/components/Quantity";
import { type Source, sourceAttribute } from "../../design/components/SourceChip";
import type { GateMode } from "../../design/components/GateMode";
import { at, type Lane, position } from "./model";

/** A log timestamp as a clock time, to the millisecond, in UTC. */
export function clock(ts: string): string {
  const found = /T(\d{2}:\d{2}:\d{2})(\.\d{3})?/.exec(ts);
  return found === null ? ts : `${found[1] ?? ""}${found[2] ?? ""}`;
}

function percent(share: number): string {
  return `${(share * 100).toFixed(3)}%`;
}

/**
 * The run drawn on its own clock: one lane per attempt, decomposition first and integration
 * last, each segment where the log's timestamps put it. The lanes are in the order the records
 * gave them. A stage's or a session's width is its recorded duration.
 */
export function TimelineChart({
  lanes,
  mode,
  started,
  last,
  source,
}: {
  lanes: readonly Lane[];
  mode: GateMode;
  started: string;
  last: string;
  source: Source;
}) {
  const span = at(last) - at(started);
  // A short stage is drawn at a minimum width so its label can be read; the caption says so,
  // and its recorded duration is in the stage table and the segment's title.
  const width = (kind: string, seconds: number | null) => {
    const least = kind === "gate" || kind === "review" ? 0.03 : 0.01;
    return seconds === null || span <= 0 ? least : Math.max((seconds * 1000) / span, least);
  };
  // Segments are laid in the order of their start; one that would overlap the one before it
  // (two short stages a few milliseconds apart, each at its minimum width) starts where the
  // other ends. The caption says so; the times themselves are in each title and the table.
  const placed = (lane: Lane) => {
    let end = 0;
    return [...lane.segments]
      .sort((a, b) => at(a.start) - at(b.start))
      .map((segment) => {
        const share = width(segment.kind, segment.seconds);
        const left = Math.max(position(segment.start, started, last), end);
        end = left + share;
        return { segment, left, share };
      });
  };
  // A label is drawn only when it fits its segment whole: a clipped word reads as another word.
  // Measured after layout, and again whenever the widths can have changed.
  const timeline = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const fit = () => {
      for (const segment of timeline.current?.querySelectorAll<HTMLElement>(".track .segment") ??
        []) {
        const label = segment.querySelector<HTMLElement>(".segment-label");
        if (label === null) continue;
        label.hidden = false;
        const style = getComputedStyle(segment);
        const room =
          segment.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
        label.hidden = label.getBoundingClientRect().width > room + 0.5;
      }
    };
    fit();
    // Widths change when the fonts arrive and when the timeline is resized, not only the window.
    window.addEventListener("resize", fit);
    document.fonts.addEventListener("loadingdone", fit);
    void document.fonts.ready.then(fit);
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(fit);
    if (timeline.current !== null) observer?.observe(timeline.current);
    return () => {
      window.removeEventListener("resize", fit);
      document.fonts.removeEventListener("loadingdone", fit);
      observer?.disconnect();
    };
  });
  return (
    <section className="card" aria-label="Timeline" data-source={sourceAttribute(source)}>
      <div className="card-head">
        <h2 className="card-title">Timeline</h2>
        <div className="legend" aria-label="Legend">
          <span className="segment segment-session legend-item">session</span>
          {/* The gate's chip is drawn as this run's gate segments are: its mode decides. */}
          <span className={`segment segment-gate-${mode} legend-item`}>
            {mode === "observe" ? "gate · observed" : mode === "off" ? "gate · skipped" : "gate"}
          </span>
          <span className="segment segment-gate-none legend-item">gate · no verdict</span>
          <span className="segment segment-review-pass legend-item">review pass</span>
          <span className="segment segment-review-fail legend-item">review fail</span>
          <span className="segment segment-infrastructure legend-item">infrastructure</span>
        </div>
      </div>
      <p className="label">
        Positions are the log&apos;s own timestamps, from its first line at{" "}
        <span className="mono">{clock(started)}</span> to its last at{" "}
        <span className="mono">{clock(last)}</span> UTC. A short stage is drawn at a minimum width,
        and a segment that would overlap the one before it starts where that one ends; each
        segment&apos;s recorded time and duration are in its title and in the stage table.
      </p>
      <div className="timeline-frame">
        <div className="timeline" ref={timeline}>
          {lanes.map((lane) => (
            <div key={lane.key} className="lane" data-lane={lane.key}>
              <div className="lane-name">
                <span className="lane-title mono">{lane.title}</span>
                <span className="label">{lane.subtitle}</span>
              </div>
              <div className="track">
                {placed(lane).map(({ segment, left, share }, i) => (
                  <span
                    key={`${segment.kind}-${String(i)}`}
                    className={`segment ${segment.tone}`}
                    data-kind={segment.kind}
                    style={{ left: percent(left), width: percent(share) }}
                    title={`${segment.label}${segment.title === undefined ? "" : ` · ${segment.title}`} · from ${clock(segment.start)}${segment.seconds === null ? "" : ` for ${String(segment.seconds)} s`}`}
                  >
                    <span className="segment-label">{segment.label}</span>
                  </span>
                ))}
                {lane.markers.map((marker, i) => (
                  <span
                    key={`marker-${String(i)}`}
                    className={`marker ${marker.tone}`}
                    style={{ left: percent(position(marker.at, started, last)) }}
                    title={`${marker.label} at ${clock(marker.at)}`}
                  >
                    {marker.label}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/** The stages in the log's order: the timeline's data as a table, read by the same records. */
export function StagesTable({ steps, source }: { steps: readonly StepTiming[]; source: Source }) {
  return (
    <section className="card" aria-label="Stages" data-source={sourceAttribute(source)}>
      <h2 className="card-title">Stages, in the log&apos;s order</h2>
      <ScrollTable label="Stages">
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Line</th>
              <th scope="col">Subtask</th>
              <th scope="col">Attempt</th>
              <th scope="col">Stage</th>
              <th scope="col">Entered (UTC)</th>
              <th scope="col" className="numeric">
                Duration
              </th>
            </tr>
          </thead>
          <tbody>
            {steps.map((step) => (
              <tr key={step.seq}>
                <td className="mono">{step.seq}</td>
                <td className="mono">{step.subtask}</td>
                <td className="mono">{step.attempt}</td>
                <td>{step.stage}</td>
                <td className="mono">{clock(step.entered)}</td>
                <td className="numeric">
                  <Quantity q={{ value: step.seconds, unit: "s" }} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollTable>
    </section>
  );
}
