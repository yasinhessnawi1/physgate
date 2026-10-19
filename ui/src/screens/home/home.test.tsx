// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { RunEvent } from "../../api/events";
import { costRecord, type LedgerLine } from "../../api/records";
import { namesACommand } from "../../rules/commands";
import { EngineWords } from "../common/engine";
import { CostSoFar, StripLegend } from "./Home";
import { NoRunsYet } from "./NoRunsYet";
import { STRIP_STATES, STRIP_WORDS, strip, stripCounts } from "./strip";

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

  it("the legend as drawn reads each state as k of n, labelled a view, and never a percentage", () => {
    const html = renderToStaticMarkup(<StripLegend cells={cells} counts={stripCounts(cells)} />);
    const text = html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
    for (const state of STRIP_STATES) expect(text).toContain(`${STRIP_WORDS[state]} 1 of 5`);
    expect(text).not.toMatch(/%|percent|per cent/i);
    expect(html).toContain('aria-label="View: subtasks by state, counted from the ledger"');
  });
});

describe("the active run's cost so far", () => {
  const LINE = {
    usd: "0.25",
    nok: "2.37",
    basis: "list_price_estimate",
    prices_date: "2026-10-16",
    partial: false,
    rows: [{ model: "claude-sonnet-5", tokens: { output_tokens: 4 }, usd: "0.25" }],
    reconciliation: { unread: ["reviewer:b"], ttl_unread: ["reviewer:b", "session:a"] },
    lower_bound: true,
  };
  const SOURCE = { id: "run r-1", commit: "0123456789abcdef" };

  it("says it is a lower bound, and by how many calls, when the server could not price every call", () => {
    const html = renderToStaticMarkup(<CostSoFar cost={costRecord(LINE)} source={SOURCE} />);
    expect(html).toContain("Lower bound");
    expect(html).toContain("2 calls not priced at the rate they paid");
    expect(html).toContain("price sheet of 2026-10-16");
  });

  it("says nothing of a bound when every call was priced", () => {
    const whole = costRecord({ ...LINE, lower_bound: false, reconciliation: null });
    expect(renderToStaticMarkup(<CostSoFar cost={whole} source={SOURCE} />)).not.toContain(
      "Lower bound",
    );
  });
});

describe("the engine a run ran on", () => {
  it("is not recorded by any run today, and the cell says so rather than naming one", () => {
    const html = renderToStaticMarkup(<EngineWords auth="api_key" />);
    expect(html).toContain("not recorded by this run");
    expect(html).toContain("api_key");
    expect(html).not.toMatch(/claude|code/i);
  });
});
