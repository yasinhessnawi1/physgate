// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { RunStatus } from "../../api/run";
import { RunStanding } from "../../design/components/status/RunStanding";
import { standingOf } from "../../words/standing";
import type { RunRead } from "../home/data";
import { statusWords } from "../home/Home";
import type { RunEnd } from "../home/runEnd";

const BASE: RunStatus = {
  kind: "done",
  subtask: null,
  halted: null,
  owedHalt: null,
  completion: { owner: true, modules: [] },
  waiting: [],
  superseded: {},
};
const halted = (reason: string, detail = "plan_refused: the plan was refused"): RunStatus => ({
  ...BASE,
  kind: "halted",
  halted: { reason, detail },
});
const LONG =
  "not every subtask planned in modules/control merged: control-c2599c; the call was skipped: " +
  "not_all_merged; firmware to control: no contract result";
const WITHHELD: RunEnd = {
  kind: "ended",
  withheld: { module: "control-c2599c", reasons: [LONG] },
  waiting: 0,
  merged: 3,
  planned: 5,
  announced: 5,
  gate: "not-run",
  setAside: 1,
};

describe("every ended or halted run says why, in one short plain sentence", () => {
  it("a run halted at decomposition says the brief could not be split", () => {
    const s = standingOf(halted("decomposition_failed"), null);
    expect(s.phase).toBe("halted");
    expect(s.sentence).toBe("Halted: the brief could not be split into subtasks.");
    expect(s.detail).toContain("decomposition_failed");
    expect(s.detail).toContain("plan_refused: the plan was refused");
  });

  it("an incident, the retries used up, and a reason not known here each read plainly", () => {
    expect(standingOf(halted("incident"), null).sentence).toBe(
      "Halted: the harness recorded an incident and stopped the run.",
    );
    expect(standingOf(halted("infrastructure_exhausted"), null).sentence).toBe(
      "Halted: an agent's session would not run, and every retry was used.",
    );
    expect(standingOf(halted("something_new"), null).sentence).toBe("Halted: something new.");
  });

  it("an ended run with a module withheld names the module, short; the full text is the detail", () => {
    const s = standingOf(BASE, WITHHELD);
    expect(s.phase).toBe("done");
    expect(s.word).toBe("Ended");
    expect(s.sentence).toBe("Ended: the control module was not completed.");
    expect(s.detail).toContain(LONG);
  });

  it("a complete run and one that ended with a decision waiting each say so", () => {
    expect(standingOf(BASE, { kind: "complete" }).word).toBe("Complete");
    expect(standingOf(BASE, { ...WITHHELD, waiting: 1 }).sentence).toBe(
      "Ended with 1 decision still waiting for a person.",
    );
  });

  it("the run's own screen shows the badge, the sentence and the full text on demand", () => {
    const html = renderToStaticMarkup(<RunStanding standing={standingOf(BASE, WITHHELD)} />);
    expect(html).toContain("Ended: the control module was not completed.");
    expect(html).toMatch(/<details[^>]*>\s*<summary[^>]*>[^<]*Details/);
    expect(html).toContain(LONG);
    expect(html).toContain('data-phase="done"');
  });

  it("Home's list shows the same short sentence, the record's words folded behind it", () => {
    const read = {
      run: { root: 0, name: "r", runId: "r", error: null },
      status: { ok: true, value: halted("infrastructure_exhausted", "attempt 2: retries ran out") },
      config: { ok: false, refusal: { error: "x" } },
      events: { ok: true, value: [] },
      queue: { ok: true, value: { open: [], decided: [] } },
    } as unknown as RunRead;
    const html = renderToStaticMarkup(<>{statusWords(read)}</>);
    expect(html).toContain("every retry was used");
    expect(html).toContain("<details");
    expect(html).toContain("attempt 2: retries ran out");
  });
});
