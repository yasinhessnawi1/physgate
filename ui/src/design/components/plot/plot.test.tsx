import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { axisLabel, checkPlot, type PlotSpec, PlotSpecError, PlotTable } from "./Plot";
import { PlotFrame } from "./PlotFrame";

/** Fixture data only: no series record exists yet, so nothing here is a recorded result. */
const STEP: PlotSpec = {
  title: "Fixture step response",
  x: { label: "time", unit: "s", scale: "linear" },
  xValues: [0, 0.5, 1, 1.5],
  y: { label: "position", unit: "m", scale: "linear" },
  series: [{ label: "fixture", unit: "m", y: [0, 0.06, 0.09, 0.1] }],
  source: { id: "fixture", commit: null },
};

describe("a plot has a unit on every axis and converts nothing", () => {
  it("labels each axis with what it measures and its unit", () => {
    expect(axisLabel(STEP.x)).toBe("time [s]");
    expect(axisLabel({ label: "gain", unit: "1", scale: "log" })).toBe("gain [dimensionless]");
  });

  it("accepts a well-formed spec", () => {
    expect(checkPlot(STEP)).toBe(STEP);
  });

  it("refuses a series in another unit than its axis", () => {
    const mixed = { ...STEP, series: [{ label: "in mm", unit: "mm", y: [0, 60, 90, 100] }] };
    expect(() => checkPlot(mixed)).toThrow(PlotSpecError);
  });

  it("refuses an axis without a unit", () => {
    expect(() => checkPlot({ ...STEP, y: { ...STEP.y, unit: " " } })).toThrow(/no unit/);
  });

  it("refuses a log axis holding zero, and a series of the wrong length", () => {
    expect(() => checkPlot({ ...STEP, x: { ...STEP.x, scale: "log" } })).toThrow(/log axis/);
    expect(() => checkPlot({ ...STEP, series: [{ label: "short", unit: "m", y: [0] }] })).toThrow(
      /one value per x/,
    );
  });
});

describe("a plot carries a text summary and its data as a table", () => {
  it("the table holds every point as recorded", () => {
    const html = renderToStaticMarkup(<PlotTable spec={STEP} />);
    expect(html).toContain("time [s]");
    expect(html).toContain("fixture [m]");
    expect(html).toContain(">0.09<");
  });

  it("the frame shows the summary and the source, and refuses a frame with no summary", () => {
    const html = renderToStaticMarkup(
      <PlotFrame
        title="Step"
        summary="Rises to 0.1 m by 1.5 s."
        source={STEP.source}
        plot={null}
        data={null}
      />,
    );
    expect(html).toContain("Rises to 0.1 m by 1.5 s.");
    expect(html).toContain("no commit");
    expect(() =>
      renderToStaticMarkup(
        <PlotFrame title="Step" summary=" " source={null} plot={null} data={null} />,
      ),
    ).toThrow(/summary/);
  });
});
