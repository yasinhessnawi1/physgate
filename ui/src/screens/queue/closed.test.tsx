// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { itemView } from "../../api/queue";
import { decisionClosedWords } from "../../words/standing";
import { QueueItem } from "./QueueItem";

const VIEW = itemView({
  position: 0,
  item_sha256: "a".repeat(64),
  open: true,
  item: {
    kind: "item",
    item_id: "run-1-s1",
    ts: "2026-11-08T12:00:00.000000Z",
    run_id: "run-1",
    subtask_id: "s1",
    source: "review_unavailable",
    decision_required: "Decide.",
    artefact_diff: "",
    triggering_finding: "f",
    quantities: [],
    trajectories: [],
  },
  trajectories: [],
});

function shown(closed: string | null): string {
  return renderToStaticMarkup(
    <QueueItem
      view={VIEW}
      decided={undefined}
      source={{ id: "run run-1", commit: "abcdef1234" }}
      subtaskName="Control module"
      closed={closed}
    >
      <button type="button">Approve</button>
    </QueueItem>,
  );
}

describe("no decision can be written into a run that has ended by accident", () => {
  it("offers a decision while the run is going or waits on a person, and on no other", () => {
    expect(decisionClosedWords("going")).toBeNull();
    expect(decisionClosedWords("waiting-person")).toBeNull();
    for (const phase of ["done", "stopped", "halted", "halt-owed", "waiting-limit"] as const)
      expect(decisionClosedWords(phase)).toMatch(/no decision is offered here/);
    expect(decisionClosedWords("done")).toMatch(/^This run has ended/);
    expect(decisionClosedWords("stopped")).toMatch(/^This run stopped with no end recorded/);
  });

  it("an open item on an ended run shows why in one line, and no decision button", () => {
    const html = shown(decisionClosedWords("done"));
    expect(html).toContain("This run has ended");
    expect(html).not.toContain(">Approve<");
  });

  it("an open item on a run still going keeps its decision", () => {
    expect(shown(null)).toContain(">Approve<");
  });
});
