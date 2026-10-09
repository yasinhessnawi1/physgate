import "uplot/dist/uPlot.min.css";

import { useEffect, useRef } from "react";
import uPlot from "uplot";

import { unitLabel, valueLabel } from "../quantity";
import { type Source, SourceChip, sourceAttribute } from "./SourceChip";

/** An axis: what it measures and its unit. There is no unitless axis. */
export interface Axis {
  readonly label: string;
  readonly unit: string;
  readonly scale: "linear" | "log";
}

/** One series of points, in the y axis's unit. A what-if series is drawn dashed. */
export interface Series {
  readonly label: string;
  readonly unit: string;
  readonly y: readonly number[];
  readonly whatIf?: boolean;
}

/**
 * A time-series or frequency plot (a step response, one half of a Bode plot). Every series
 * shares the x values and must be in the y axis's unit: a mismatch is refused, never converted.
 */
export interface PlotSpec {
  readonly title: string;
  readonly x: Axis;
  readonly xValues: readonly number[];
  readonly y: Axis;
  readonly series: readonly Series[];
  readonly source: Source;
}

export class PlotSpecError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PlotSpecError";
  }
}

/** The label an axis is drawn with: what it measures and its unit, always both. */
export function axisLabel(axis: Axis): string {
  return `${axis.label} [${unitLabel(axis.unit)}]`;
}

/** ``spec`` if it is drawable as specified; otherwise refuse it with the reason. */
export function checkPlot(spec: PlotSpec): PlotSpec {
  for (const axis of [spec.x, spec.y]) {
    if (axis.unit.trim() === "") throw new PlotSpecError(`the axis "${axis.label}" has no unit`);
  }
  if (spec.series.length === 0) throw new PlotSpecError("a plot with no series shows nothing");
  for (const series of spec.series) {
    if (series.unit !== spec.y.unit) {
      throw new PlotSpecError(
        `the series "${series.label}" is in ${series.unit}, its axis in ${spec.y.unit}; nothing is converted`,
      );
    }
    if (series.y.length !== spec.xValues.length) {
      throw new PlotSpecError(`the series "${series.label}" does not have one value per x`);
    }
  }
  const all = [...spec.xValues, ...spec.series.flatMap((s) => s.y)];
  if (!all.every(Number.isFinite))
    throw new PlotSpecError("a plotted value is not a finite number");
  if (spec.x.scale === "log" && !spec.xValues.every((v) => v > 0)) {
    throw new PlotSpecError("a log axis cannot hold zero or a negative value");
  }
  return spec;
}

function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(`--color-${name}`).trim();
}

/** uPlot's options for a checked spec. Colours come from the theme's tokens. */
export function plotOptions(spec: PlotSpec, width: number, height: number): uPlot.Options {
  // uPlot's scale distribution: 1 linear, 3 logarithmic. Its enum is an ambient const enum,
  // which isolated modules cannot read, so its two documented values are written here.
  const distribution = (axis: Axis) =>
    // eslint-disable-next-line @typescript-eslint/no-unsafe-enum-assignment -- see above
    (axis.scale === "log" ? 3 : 1) as uPlot.Scale.Distr;
  return {
    title: spec.title,
    width,
    height,
    scales: {
      x: { time: false, distr: distribution(spec.x) },
      y: { distr: distribution(spec.y) },
    },
    axes: [
      { label: axisLabel(spec.x), stroke: token("text-2"), grid: { stroke: token("border") } },
      { label: axisLabel(spec.y), stroke: token("text-2"), grid: { stroke: token("border") } },
    ],
    series: [
      { label: axisLabel(spec.x) },
      ...spec.series.map((s) => ({
        label: `${s.label} [${unitLabel(s.unit)}]`,
        stroke: s.whatIf === true ? token("whatif") : token("accent"),
        width: 2,
        ...(s.whatIf === true ? { dash: [6, 4] } : {}),
      })),
    ],
  };
}

/**
 * The plot, with a text summary and a table of the same values beneath it: a picture alone is
 * not readable by everyone, and the table is the record the picture was drawn from.
 */
export function Plot({ spec }: { spec: PlotSpec }) {
  const checked = checkPlot(spec);
  const holder = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = holder.current;
    if (node === null) return;
    const data: uPlot.AlignedData = [
      Float64Array.from(checked.xValues),
      ...checked.series.map((s) => Float64Array.from(s.y)),
    ];
    const chart = new uPlot(plotOptions(checked, node.clientWidth || 640, 320), data, node);
    return () => {
      chart.destroy();
    };
  }, [checked]);
  return (
    <figure className="plot" data-source={sourceAttribute(checked.source)}>
      <div ref={holder} className="plot-canvas" aria-hidden="true" />
      <figcaption className="plot-summary">
        {checked.title}: {checked.series.length} series against {axisLabel(checked.x)},{" "}
        {checked.xValues.length} points each. <SourceChip source={checked.source} />
      </figcaption>
      <table className="table plot-table">
        <thead>
          <tr>
            <th scope="col">{axisLabel(checked.x)}</th>
            {checked.series.map((s) => (
              <th key={s.label} scope="col">
                {s.label} [{unitLabel(s.unit)}]
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {checked.xValues.map((x, row) => (
            <tr key={String(row)}>
              <td className="mono">{valueLabel(x)}</td>
              {checked.series.map((s) => (
                <td key={s.label} className="mono">
                  {valueLabel(s.y[row] ?? Number.NaN)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
