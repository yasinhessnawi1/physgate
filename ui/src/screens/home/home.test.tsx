// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { RunEvent } from "../../api/events";
import type { LedgerLine } from "../../api/records";
import { namesACommand } from "../../rules/commands";
import { NoRunsYet } from "./NoRunsYet";
import { STRIP_WORDS, strip, stripCounts } from "./strip";

const line = (id: string, attempts: number, mergeCommit: string | null = null): LedgerLine => ({
  id,
  role: "electrical",
  attempts,
  gate: null,
  review: null,
  mergeCommit,
});

describe("Home with no run yet", () => {
  it("leads with starting a project, drawn disabled and said to be coming", () => {
    const html = renderToStaticMarkup(<NoRunsYet />);
    expect(html).toContain("No runs yet");
    expect(html.indexOf("Start a project")).toBeLessThan(html.indexOf("Coming soon"));
    expect(html).toMatch(/<button[^>]*disabled/);
  });

  it("names no terminal command", () => {
    expect(namesACommand(renderToStaticMarkup(<NoRunsYet />))).toBe(false);
  });
});

describe("the active run's subtask strip reads each subtask's state from the records", () => {
  const events: RunEvent[] = [{ seq: 9, ts: "t", kind: "escalated", subtask: "s2", itemId: "q" }];
  const lines = [
    line("s1", 0),
    line("s2", 0),
    line("s3", 0),
    line("s1", 1),
    line("s1", 1, "abc1234"),
    line("s2", 3),
    line("s3", 1),
    line("s4", 0),
    line("s5", 2),
  ];
  const cells = strip(lines, events, { kind: "attempt", subtask: "s3", halted: null });

  it("one cell per subtask, in the order they first appear, each in one state", () => {
    expect(cells.map((c) => [c.subtask, c.state])).toEqual([
      ["s1", "merged"],
      ["s2", "set-aside"],
      ["s3", "running"],
      ["s4", "not-started"],
      ["s5", "tried"],
    ]);
  });

  it("counts every state as k of n, never as a percentage", () => {
    expect(stripCounts(cells)).toEqual({
      merged: 1,
      "set-aside": 1,
      running: 1,
      tried: 1,
      "not-started": 1,
    });
    expect(STRIP_WORDS["set-aside"]).toBe("set aside for a decision");
  });
});
