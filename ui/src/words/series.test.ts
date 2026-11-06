import { describe, expect, it } from "vitest";

import { type ColumnSummary, EXTRACTORS } from "../api/series";
import {
  agreementWords,
  againstWords,
  asSentence,
  axisWords,
  EXTRACTOR_WORDS,
  extractorWords,
  GATE_WORDS,
  gateWords,
  groupLabel,
  heldWords,
  joinedLabels,
  recordsCount,
  SERIES_COPY,
  setAsideWords,
  summarySentence,
  supersededWords,
  titledBy,
  toleranceWords,
  traceLabel,
} from "./series";

const col = (name: string, unit: string, extra: Partial<ColumnSummary> = {}): ColumnSummary => ({
  name,
  unit,
  samples: 501,
  first: 0,
  last: 1.0000064,
  smallest: 0,
  largest: 1.3912345678901,
  ...extra,
});

describe("the extractors in words", () => {
  it("names every extractor the schema has, and no other", () => {
    expect(Object.keys(EXTRACTOR_WORDS)).toEqual([...EXTRACTORS]);
  });

  it("follows a time extractor with the trace it reads, and a frequency extractor with nothing", () => {
    expect(extractorWords("final", "position")).toBe("Final value of position");
    expect(extractorWords("max_abs", "motor_current")).toBe("Largest magnitude of motor current");
    expect(extractorWords("max", "x")).toBe("Largest value of x");
    expect(extractorWords("min", "x")).toBe("Smallest value of x");
    expect(extractorWords("phase_margin", null)).toBe("Phase margin");
    expect(extractorWords("delay_margin", null)).toBe("Delay margin");
  });

  it("shows an extractor it has no words for as written", () => {
    expect(extractorWords("settling_index", null)).toBe("settling_index");
    expect(extractorWords("settling_index", "position")).toBe("settling_index position");
  });
});

describe("a record's labels come from its own names, never more", () => {
  it("writes a trace's name in sentence case, and an unknown token as written", () => {
    expect(traceLabel("loop_magnitude")).toBe("Loop magnitude");
    expect(traceLabel("angular_frequency")).toBe("Angular frequency");
    expect(traceLabel("qx7_flux")).toBe("Qx7 flux");
  });

  it("names a group the role gave, and says when it gave none", () => {
    expect(groupLabel("edge_runs")).toBe("Edge runs");
    expect(groupLabel(null)).toBe("Not grouped");
  });

  it("says which axis a record has, and which role titled it", () => {
    expect(axisWords("time")).toBe("Time record");
    expect(axisWords("frequency")).toBe("Frequency record");
    expect(titledBy("control")).toBe("titled by the control role");
  });

  it("joins a plot's trace labels for its title and says what it draws against", () => {
    expect(joinedLabels(["position"])).toBe("Position");
    expect(joinedLabels(["position", "error"])).toBe("Position and error");
    expect(joinedLabels(["a_b", "c", "d"])).toBe("A b, c and d");
    expect(againstWords(["position", "error"], "time")).toBe("Position and error against time");
  });
});

describe("the summary says only what the server's summary holds", () => {
  it("states the samples, the x range and the trace's smallest, largest and last, unrounded", () => {
    expect(summarySentence(col("position", "m"), col("time", "s", { last: 10 }))).toBe(
      "Position against time: 501 samples from 0 s to 10 s. Smallest 0 m, largest 1.3912345678901 m, last 1.0000064 m.",
    );
  });

  it("keeps a negative zero's sign and spells a dimensionless unit", () => {
    expect(
      summarySentence(
        col("loop_magnitude", "1", { smallest: -0, largest: 1e-5, last: "12345678901234567890" }),
        col("angular_frequency", "rad/s", { first: 0.01, last: 100 }),
      ),
    ).toBe(
      "Loop magnitude against angular frequency: 501 samples from 0.01 rad/s to 100 rad/s. Smallest -0 dimensionless, largest 0.00001 dimensionless, last 12345678901234567890 dimensionless.",
    );
  });

  it("names no settling time, overshoot, rise time, peak frequency or rating", () => {
    const sentence = summarySentence(col("position", "m"), col("time", "s"));
    expect(sentence).not.toMatch(/settl|overshoot|rise time|peak|rating|within/i);
  });
});

describe("agreement, the gate column and the states, in words", () => {
  it("names the tolerance in words from the harness's own spelling of it", () => {
    expect(toleranceWords("0.005").full).toBe("three significant figures (0.5 % relative)");
    expect(agreementWords("agrees", "0.005")).toBe("Agrees within three significant figures");
    expect(agreementWords("agrees", "0.01")).toBe("Agrees within a relative tolerance of 0.01");
  });

  it("says why a quantity did not agree, and shows an unknown outcome as written", () => {
    expect(agreementWords("differs", "0.005")).toBe(
      "Differs: the attempt was refused before the gate",
    );
    expect(agreementWords("unreadable", "0.005")).toBe("Could not be read off the record");
    expect(agreementWords("partly", "0.005")).toBe("partly");
  });

  it("has a sentence for each way no gate record is shown, and an unknown one as written", () => {
    expect(gateWords("not_named")).toBe("No gate record of this attempt names this quantity.");
    expect(gateWords("unmatched")).toBe(
      "Named by the gate's finding, but it cannot be matched to one gate record.",
    );
    expect(gateWords("gate_off")).toBe("The gate did not run.");
    expect(gateWords("refused_before_gate")).toBe(
      "The gate did not run: the attempt was refused before it.",
    );
    expect(gateWords("gate_not_run")).toBe("The gate has not run on this attempt.");
    expect(gateWords("a_new_state")).toBe("a_new_state");
    expect(Object.keys(GATE_WORDS)).toHaveLength(5);
  });

  it("writes a recorded reason as a sentence, and a set-aside file with the collector's reason", () => {
    expect(asSentence("names the record x, which this attempt did not seal")).toBe(
      "Names the record x, which this attempt did not seal.",
    );
    expect(setAsideWords("refused", "not a regular file")).toBe("Not sealed: not a regular file.");
    expect(setAsideWords("discarded", "left in the outbox before this session began")).toBe(
      "Discarded, not sealed: left in the outbox before this session began.",
    );
    expect(setAsideWords("quarantined", "why")).toBe("quarantined: why.");
  });

  it("says a superseded record, a held record and a count of records as they are", () => {
    expect(supersededWords("step_nominal")).toBe(
      "A later session of this attempt recorded step_nominal again; the later one is shown.",
    );
    expect(heldWords("a column's unit is not one the gate knows")).toBe(
      "This record is sealed, but this version cannot read it: a column's unit is not one the gate knows.",
    );
    expect(recordsCount(6, false)).toBe("6 records");
    expect(recordsCount(1, true)).toBe("1 record so far");
  });

  it("says what a record does not prove, and never that it was verified", () => {
    expect(SERIES_COPY.provenance).toBe(
      "This record names the committed code that wrote it. The harness did not re-run that code to confirm the curve.",
    );
    expect(SERIES_COPY.broken).toBe(
      "This record changed after its session ended, so it is not shown.",
    );
    const all = Object.entries(SERIES_COPY)
      .filter(([key]) => key !== "provenance")
      .map(([, text]) => text)
      .join(" ");
    expect(all).not.toMatch(/verified|re-run|overshoot|settl|rise time|within rating/i);
  });
});
