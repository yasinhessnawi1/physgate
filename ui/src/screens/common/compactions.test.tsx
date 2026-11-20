/**
 * A review that compacted says so where its verdict is shown: on its timeline row and in the
 * attempt's inspector, and on the row of a review that compacted and still reached no verdict.
 * A line without the count shows nothing of it, and a count that is not one is refused.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { runEvent } from "../../api/events";
import { Reviews } from "../run-timeline/AttemptInspector";
import { rowsOf } from "./rows";

const MODELS = { roleModels: {}, decompositionModel: null, reviewerModels: {} };

function reviewRan(extra: Record<string, unknown>) {
  return {
    seq: 3,
    ts: "2026-11-15T12:00:00.000000Z",
    run_id: "run-1",
    gate_mode: "on",
    kind: "review_ran",
    subtask_id: "s1",
    attempt: 1,
    result: {
      verdict: "pass",
      finding: "Every item holds.",
      reviewer_model: "claude-sonnet-5",
      session_id: "rev-1",
      usage: [],
      ...extra,
    },
  };
}

function reviewUnavailable(extra: Record<string, unknown>) {
  return {
    seq: 4,
    ts: "2026-11-15T12:00:01.000000Z",
    run_id: "run-1",
    gate_mode: "on",
    kind: "review_unavailable",
    subtask_id: "s1",
    attempt: 1,
    cause: "context_exceeded",
    detail: "the review outgrew the model's context window (after 1 compaction)",
    retry: false,
    session_id: "rev-1",
    reviewer_model: "claude-sonnet-5",
    ...extra,
  };
}

function metaOf(line: Record<string, unknown>): string {
  const rows = rowsOf([runEvent(line)], MODELS);
  expect(rows).toHaveLength(1);
  return rows[0]?.meta ?? "";
}

describe("a review that compacted", () => {
  it("says how many compactions came before its verdict", () => {
    expect(metaOf(reviewRan({ compactions: 2 }))).toContain("after 2 compactions");
    expect(metaOf(reviewRan({ compactions: 1 }))).toContain("after 1 compaction");
    expect(metaOf(reviewRan({ compactions: 1 }))).not.toContain("compactions");
  });

  it("says so on a review that still reached no verdict", () => {
    expect(metaOf(reviewUnavailable({ compactions: 1 }))).toContain("after 1 compaction");
  });

  it("shows nothing of it on a line without the count", () => {
    expect(metaOf(reviewRan({}))).not.toContain("compaction");
    expect(metaOf(reviewUnavailable({ detail: "the review outgrew it" }))).not.toContain(
      "compaction",
    );
  });

  it("refuses a count that is not one", () => {
    for (const bad of ["2", -1, 1.5, 0]) {
      expect(() => runEvent(reviewRan({ compactions: bad }))).toThrow();
      expect(() => runEvent(reviewUnavailable({ compactions: bad }))).toThrow();
    }
  });

  it("is shown in the attempt's inspector", () => {
    const line = runEvent(reviewRan({ compactions: 2 }));
    if (line.kind !== "review_ran") throw new Error("not a review line");
    expect(renderToStaticMarkup(<Reviews reviews={[line]} />)).toContain("after 2 compactions");
    const plain = runEvent(reviewRan({}));
    if (plain.kind !== "review_ran") throw new Error("not a review line");
    expect(renderToStaticMarkup(<Reviews reviews={[plain]} />)).not.toContain("compaction");
  });
});
