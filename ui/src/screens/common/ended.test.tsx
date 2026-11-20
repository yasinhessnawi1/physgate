// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { RunStatus } from "../../api/run";
import { RunStanding } from "../../design/components/status/RunStanding";
import { standingOf } from "../../words/standing";
import type { RunRead } from "../home/data";
import { statusWords } from "../home/Home";
import { type RunEnd, recordedEnd, runEnd, runEndWords, unsignedEnd } from "../home/runEnd";

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
  recorded: null,
  unsigned: null,
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

  it("a run that records decisions and ended escalated waits on no one, and names each sign-off owed", () => {
    const control = {
      subtask: "control-c2599c",
      sizing: false,
      state: "sign_off_owed" as const,
      open: [{ name: "sign_off", reason: "its stability margin owes a person's sign-off" }],
    };
    const status: RunStatus = {
      ...BASE,
      kind: "escalated",
      acts: false,
      signOffsOwed: ["control-c2599c"],
      completion: { owner: true, modules: [control] },
    };
    // The sign-off item is open in the queue, and no decision on it acts.
    const end = runEnd([], 1, status.completion, recordedEnd(status));
    const s = standingOf(status, end);
    expect(s.phase).toBe("done");
    expect(s.word).toBe("Ended");
    expect(s.sentence).toBe(
      "Ended: this run recorded its decisions and acted on none, so nothing waits for you. " +
        "The control module still owes a person's sign-off.",
    );
    expect(runEndWords(end)).toBe(
      "Ended · decisions recorded, none acted on · sign-off owed: control-c2599c",
    );
    for (const said of [s.sentence ?? "", s.detail ?? "", runEndWords(end)]) {
      expect(said).not.toMatch(/waiting for (you|a person)/i);
      expect(said).not.toContain("Waiting for a person's decision");
    }
    // Before its log and queue are read, the status alone says the same.
    expect(standingOf(status, null).sentence).toBe(s.sentence);
  });

  it("two sign-offs owed are named together; none owed says only that nothing acted", () => {
    const status: RunStatus = {
      ...BASE,
      kind: "escalated",
      acts: false,
      signOffsOwed: ["control-c2599c", "chassis-0a1b2c"],
    };
    expect(standingOf(status, null).sentence).toContain(
      "The control and chassis modules still owe a person's sign-off.",
    );
    const none: RunStatus = { ...status, signOffsOwed: [] };
    expect(standingOf(none, null).sentence).toBe(
      "Ended: this run recorded its decisions and acted on none, so nothing waits for you.",
    );
  });

  it("a run that acts and ended escalated still waits for a person", () => {
    const status: RunStatus = { ...BASE, kind: "escalated", acts: true, signOffsOwed: ["c1"] };
    expect(standingOf(status, null).phase).toBe("waiting-person");
    expect(recordedEnd(status)).toBeNull();
    // A server that does not say whether decisions act is read as before.
    expect(standingOf({ ...BASE, kind: "escalated" }, null).phase).toBe("waiting-person");
  });

  it("a run that acts and ended owing a sign-off whose item was decided waits on no one", () => {
    // The person rejected the module's latest item: it records only, and no later item asks.
    const control = {
      subtask: "control-c2599c",
      sizing: false,
      state: "sign_off_owed" as const,
      open: [{ name: "sign_off", reason: "its stability margin owes a person's sign-off" }],
    };
    const status: RunStatus = {
      ...BASE,
      kind: "escalated",
      acts: true,
      signOffsOwed: ["control-c2599c"],
      signOffsOpenToDecide: [],
      completion: { owner: true, modules: [control] },
    };
    expect(unsignedEnd(status)).toEqual(["control-c2599c"]);
    expect(recordedEnd(status)).toBeNull();
    const end = runEnd([], 0, status.completion, recordedEnd(status), unsignedEnd(status));
    const s = standingOf(status, end);
    expect(s.phase).toBe("done");
    expect(s.word).toBe("Ended");
    expect(s.sentence).toBe(
      "Ended: the control module's sign-off was not given, and no decision left in this run " +
        "can give it. A new run is needed to complete it.",
    );
    expect(runEndWords(end)).toBe("Ended · sign-off not given: control-c2599c");
    for (const said of [s.sentence ?? "", runEndWords(end)]) {
      expect(said).not.toMatch(/waiting for (you|a person)/i);
      expect(said).not.toMatch(/\bcomplete\b(?! it)/);
    }
    // Another item still open to a person is said first: the run ended with it waiting.
    const waiting = runEnd([], 1, status.completion, null, unsignedEnd(status));
    expect(standingOf(status, waiting).sentence).toBe(
      "Ended with 1 decision still waiting for a person.",
    );
  });

  it("a run that acts and ended owing a sign-off a person can still decide waits for them", () => {
    const status: RunStatus = {
      ...BASE,
      kind: "escalated",
      acts: true,
      signOffsOwed: ["c1", "c2"],
      signOffsOpenToDecide: ["c2"],
    };
    expect(unsignedEnd(status)).toBeNull();
    expect(standingOf(status, null).phase).toBe("waiting-person");
    // A server that does not say which are open to decide is read as before.
    const unsaid: RunStatus = { ...status, signOffsOpenToDecide: [] };
    expect(unsignedEnd({ ...unsaid, acts: true, signOffsOwed: [] })).toBeNull();
    const notSaid: RunStatus = {
      ...BASE,
      kind: "escalated",
      acts: true,
      signOffsOwed: ["c1"],
    };
    expect(unsignedEnd(notSaid)).toBeNull();
  });

  it("a module whose sign-off is owed is never read as complete, and says the sign-off is owed", () => {
    const control = {
      subtask: "control-c2599c",
      sizing: false,
      state: "sign_off_owed" as const,
      open: [],
    };
    const end = runEnd([], 0, { owner: true, modules: [control] });
    expect(end.kind).toBe("ended");
    expect(end.kind === "ended" ? end.withheld : null).toEqual({
      module: "control-c2599c",
      reasons: ["a person's sign-off is owed"],
    });
  });

  it("two sign-offs not given are named together", () => {
    const status: RunStatus = {
      ...BASE,
      kind: "escalated",
      acts: true,
      signOffsOwed: ["control-c2599c", "chassis-0a1b2c"],
      signOffsOpenToDecide: [],
    };
    const end = runEnd([], 0, status.completion, null, unsignedEnd(status));
    expect(standingOf(status, end).sentence).toContain(
      "the control and chassis modules' sign-offs were not given",
    );
  });

  it("Home's list says the run ended with its decisions recorded, never that it waits for you", () => {
    const status: RunStatus = {
      ...BASE,
      kind: "escalated",
      acts: false,
      signOffsOwed: ["control-c2599c"],
    };
    const read = {
      run: { root: 0, name: "r", runId: "r", error: null },
      status: { ok: true, value: status },
      config: { ok: false, refusal: { error: "x" } },
      events: { ok: true, value: [] },
      queue: { ok: true, value: { open: [], decided: [] } },
    } as unknown as RunRead;
    const html = renderToStaticMarkup(<>{statusWords(read)}</>);
    expect(html).toContain("recorded its decisions and acted on none");
    expect(html).toContain("still owes a person&#x27;s sign-off");
    expect(html).not.toContain("Waiting for you");
    expect(html).not.toContain("waiting for you");
  });
});
