import { type ReactNode, useState } from "react";

import { Segmented } from "../actions/Segmented";
import type { Source } from "../data/source";
import { SourceChip } from "../data/SourceChip";

/**
 * The one frame for every plot: its title, legend, a text summary of what it shows (required),
 * a switch between the plot and its data as a table, and its source. A frame holding a what-if
 * series is dashed in the what-if colour.
 */
export function PlotFrame({
  title,
  subtitle,
  legend,
  summary,
  source,
  plot,
  data,
  whatIf = false,
}: {
  readonly title: string;
  readonly subtitle?: string;
  readonly legend?: ReactNode;
  /** What the plot shows, in words: read by everyone, and all a screen reader gets of the chart. */
  readonly summary: string;
  readonly source: Source | null;
  readonly plot: ReactNode;
  /** The same points as a table. */
  readonly data: ReactNode;
  readonly whatIf?: boolean;
}) {
  const [view, setView] = useState<"plot" | "data">("plot");
  if (summary.trim() === "") throw new Error("a plot carries a text summary of what it shows");
  return (
    <figure
      className={whatIf ? "pg-plot pg-plot-whatif" : "pg-plot"}
      {...(source === null
        ? {}
        : { "data-source": `${source.id}@${source.commit ?? "no commit"}` })}
    >
      <div className="pg-plot-head">
        <div>
          <h3 className="pg-plot-title">{title}</h3>
          {subtitle !== undefined && <div className="pg-plot-sub">{subtitle}</div>}
        </div>
        <Segmented
          label={`${title}: plot or data`}
          value={view}
          onChange={setView}
          options={[
            { value: "plot", label: "Plot" },
            { value: "data", label: "Data" },
          ]}
        />
      </div>
      {legend !== undefined && <div className="pg-plot-legend">{legend}</div>}
      <div className="pg-plot-area">{view === "plot" ? plot : data}</div>
      <figcaption className="pg-plot-foot">
        <p className="pg-plot-summary">{summary}</p>
        <SourceChip id={source?.id ?? null} commit={source?.commit ?? null} />
      </figcaption>
    </figure>
  );
}
