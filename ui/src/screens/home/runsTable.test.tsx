// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { RunListing } from "../../api/records";
import type { RunRead } from "./data";
import { Runs } from "./Home";

const listing = (name: string, started: string): RunListing => ({
  root: 0,
  name,
  runId: name,
  manifestId: "m",
  gateMode: "on",
  osLayer: null,
  error: null,
  started,
});
const read = (run: RunListing, brief: string): RunRead =>
  ({
    run,
    config: { ok: true, value: { briefSha256: brief } },
    status: {
      ok: true,
      value: {
        kind: "halted",
        subtask: null,
        halted: { reason: "incident", detail: "d" },
        owedHalt: null,
        completion: { owner: false, modules: [] },
        waiting: [],
        superseded: {},
      },
    },
    events: { ok: true, value: [] },
    queue: { ok: true, value: { open: [], decided: [] } },
  }) as unknown as RunRead;

describe("Home's run list reads in one order, newest first, never grouped so dates jump", () => {
  it("lists the runs as given, one table body, the brief as a plain column", () => {
    const newer = listing("bench-12", "2026-11-16T19:52:00Z");
    const older = listing("bench-4", "2026-11-03T17:17:00Z");
    const html = renderToStaticMarkup(
      <Runs
        runs={[newer, older]}
        reads={
          new Map([
            ["0/bench-12", read(newer, "b".repeat(64))],
            ["0/bench-4", read(older, "a".repeat(64))],
          ])
        }
        labels={new Map()}
      />,
    );
    expect(html).not.toContain("Runs of one brief");
    expect(html.match(/<tbody/g)?.length).toBe(1);
    expect(html.indexOf("bench-12")).toBeLessThan(html.indexOf("bench-4"));
    expect(html).toContain(">Brief<");
    expect(html.match(/data-phase="halted"/g)?.length).toBe(2);
  });
});
