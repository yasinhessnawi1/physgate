import { describe, expect, it } from "vitest";

import { ShapeError } from "../../api/client";
import { CATCHES, COMPARED, DIGEST, readRow, RUNS, SPEND, TAMPERED } from "./answers";
import {
  byKind,
  compareRoute,
  driftedOf,
  evidenceCatches,
  evidenceComparison,
  evidenceRuns,
  evidenceSpend,
  newestDate,
  spendRoute,
} from "./api";
import { driftWords, kOfN, settingLabel, unreadWords, valueWords } from "./words";

/** ``value`` without ``key``. */
function without(value: Record<string, unknown>, key: string): Record<string, unknown> {
  return Object.fromEntries(Object.entries(value).filter(([k]) => k !== key));
}

describe("the run list's guard", () => {
  it("takes each run as the server sends it: a run read, and one not read with its reason", () => {
    const rows = evidenceRuns(RUNS);
    expect(rows.map((r) => [r.name, r.read])).toEqual([
      ["ev-ablation", true],
      ["ev-development", true],
      ["ev-drifted", true],
      ["ev-reportable", true],
      ["ev-tampered", false],
      ["ev-unreadable", false],
    ]);
    const tampered = rows[4];
    expect(tampered?.read === false ? tampered.record : null).toBe("run.json");
  });

  it("orders the runs read kind by kind, reportable first and ablation last", () => {
    expect(byKind(evidenceRuns(RUNS)).map((r) => r.name)).toEqual([
      "ev-reportable",
      "ev-development",
      "ev-drifted",
      "ev-ablation",
    ]);
  });

  it("refuses a run with a field missing, a field it does not know, or an unknown kind", () => {
    const row = readRow("ev-development", "development", "2");
    for (const bad of [
      without(row, "seed"),
      without(row, "pins"),
      { ...row, extra: 1 },
      { ...row, kind: "headline" },
      without(TAMPERED, "record"),
      { ...TAMPERED, path: "/somewhere" },
    ])
      expect(() => evidenceRuns({ runs: [bad] })).toThrow(ShapeError);
    expect(() => evidenceRuns({ runs: [], more: [] })).toThrow(ShapeError);
  });

  it("refuses a run whose settings carry a held-out tier's field", () => {
    const row = readRow("ev-reportable", "reportable", "4");
    for (const key of ["held_out", "held_out_canaries", "held_out_sha256"]) {
      expect(() => evidenceRuns({ runs: [{ ...row, pins: { [key]: DIGEST } }] })).toThrow(
        ShapeError,
      );
      expect(() => evidenceRuns({ runs: [{ ...row, flags: { [key]: DIGEST } }] })).toThrow(
        ShapeError,
      );
    }
  });
});

describe("the spend's guard", () => {
  it("takes the spend whole: the line, the view, each role's sessions, the groups apart", () => {
    const spend = evidenceSpend(SPEND);
    expect(spend.source.kind).toBe("development");
    expect(spend.line.usd).toEqual({ value: "0.256912", unit: "USD" });
    expect(spend.roles.map((r) => [r.role, r.sessions.map((s) => s.sessionId)])).toEqual([
      ["control", ["s-1", "s-2"]],
    ]);
    expect(spend.roles[0]?.sum.lowerBound).toBe(true);
    expect(spend.apart.review.sum).toBeNull();
    expect(spend.reconciliation?.sealBroken).toEqual(["session:s-2"]);
  });

  it("refuses a spend with a group missing, a field it does not know, or a role with no sum", () => {
    const role = SPEND.roles[0];
    for (const bad of [
      { ...SPEND, apart: without(SPEND.apart, "routing") },
      { ...SPEND, headline: "0.1" },
      { ...SPEND, roles: [{ ...role, sum: null }] },
      { ...SPEND, source: without(SPEND.source, "kind") },
    ])
      expect(() => evidenceSpend(bad)).toThrow(ShapeError);
  });

  it("chooses the newest sheet date, and none when there is none", () => {
    expect(newestDate(["2026-10-01", "2026-11-01", "2026-09-15"])).toBe("2026-11-01");
    expect(newestDate([])).toBeNull();
  });

  it("asks for a run's spend by its place, the name and date escaped", () => {
    expect(spendRoute({ root: 1, name: "a b" }, "2026-11-01")).toBe(
      "/api/evidence/spend/1/a%20b/2026-11-01",
    );
  });
});

describe("the comparison's guard", () => {
  it("takes the side by side, and the settings that differ, by name", () => {
    const compared = evidenceComparison(COMPARED);
    expect(compared.differsIn).toEqual(["ablation", "hooks"]);
    expect(compared.candidate.hooks).toBe("off");
    expect(compared.baseline.wall_clock_s).toBe(12.5);
    expect(compareRoute({ root: 0, name: "x" }, { root: 1, name: "y" })).toBe(
      "/api/evidence/compare/0/x/1/y",
    );
  });

  it("takes the notes the comparison says beside its numbers, and none when it says none", () => {
    const note = "the tier version 0123abcd is marked exposed as the register reads now";
    const read = (value: unknown): readonly string[] | string => {
      try {
        return evidenceComparison(value).notes;
      } catch (error) {
        return error instanceof ShapeError ? `refused: ${error.message}` : "raised";
      }
    };
    expect(read({ ...COMPARED, comparison: { ...COMPARED.comparison, notes: [note] } })).toEqual([
      note,
    ]);
    expect(read(COMPARED)).toEqual([]);
  });

  it("refuses a run's numbers with a field missing or one it does not know", () => {
    const { baseline } = COMPARED.comparison;
    for (const numbers of [without(baseline, "sessions"), { ...baseline, held_out: [] }])
      expect(() =>
        evidenceComparison({
          ...COMPARED,
          comparison: { ...COMPARED.comparison, baseline: numbers },
        }),
      ).toThrow(ShapeError);
  });

  it("reads a drifted refusal's settings, and nothing from any other refusal", () => {
    const drifted = { status: 422, error: "x", context: { drifted: "effort,max_output_tokens" } };
    expect(driftedOf(drifted)).toEqual(["effort", "max_output_tokens"]);
    expect(driftedOf({ ...drifted, status: 404 })).toBeNull();
    expect(driftedOf({ status: 422, error: "x", context: {} })).toBeNull();
  });
});

describe("the catches' guard", () => {
  it("takes the three kinds in order, each with its own runs and rows", () => {
    const catches = evidenceCatches(CATCHES);
    expect(catches.kinds.map((k) => [k.kind, k.runs.length, k.rows.length])).toEqual([
      ["reportable", 1, 2],
      ["development", 2, 1],
      ["ablation", 1, 0],
    ]);
    expect(catches.unread.map((u) => u.name)).toEqual(["ev-unreadable"]);
  });

  it("refuses kinds out of order, a kind missing or added, and a row it does not know", () => {
    const [reportable, development, ablation] = CATCHES.kinds;
    for (const kinds of [
      [development, reportable, ablation],
      [reportable, development],
      [...CATCHES.kinds, { kind: "all", runs: [], rows: [] }],
      [reportable, development, { ...ablation, rows: [{ total: 3 }] }],
    ])
      expect(() => evidenceCatches({ ...CATCHES, kinds })).toThrow(ShapeError);
  });
});

describe("the words", () => {
  it("names each drifted setting in words, a role's model by its role, and the rest as written", () => {
    expect(driftWords("held_out_sha256")).toBe("the tasks each run withheld differ");
    expect(driftWords("models.roles.control")).toBe("The model the control role runs on");
    expect(driftWords("a_setting_this_screen_does_not_know")).toBe(
      "a_setting_this_screen_does_not_know",
    );
  });

  it("shows a rate only as k of n, and a value as recorded", () => {
    expect(kOfN(1, 2)).toBe("1 of 2");
    expect(valueWords("observe")).toBe("observe");
    expect(valueWords(64000)).toBe("64000");
    expect(valueWords(null)).toBe("not recorded");
    expect(settingLabel("max_output_tokens")).toBe("Max output tokens");
  });

  it("says why a run was not read, with its place in the record when the reader gave one", () => {
    expect(
      unreadWords({
        read: false,
        root: 0,
        name: "x",
        error: "a line this package does not know",
        record: "events.jsonl",
        offset: "12",
        reason: null,
      }),
    ).toBe("Its events.jsonl could not be read at offset 12: a line this package does not know.");
  });
});
