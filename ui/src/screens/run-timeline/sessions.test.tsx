// @vitest-environment happy-dom
/**
 * An attempt's session is named in words a person reads first (whose session, for which attempt,
 * and how long it ran), its id after that, never as its only label.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { SessionTrace, StepTiming } from "../../api/run";
import { durationWords } from "../../words/standing";
import { clockTime } from "../../words/runs";
import { SessionWords, sessionLabel, unendedWords } from "./AttemptInspector";

const SESSION: SessionTrace = {
  sessionId: "0f4df4e9-dd0f-40d1-bd97-4cf7ce4f4600",
  subtask: "balance-control-dba29f",
  attempt: 2,
  outcome: "completed",
  cause: null,
  wallClockS: 1322.073562,
  tokens: {} as SessionTrace["tokens"],
  partial: false,
};

describe("a session is named in words before its id", () => {
  it("whose session, for which attempt", () => {
    expect(sessionLabel("control", 2, 0, 1)).toBe("The control agent's session for attempt 2");
    expect(sessionLabel("control", 2, 1, 3)).toBe(
      "The control agent's session 2 of 3 for attempt 2",
    );
    expect(sessionLabel(undefined, 1, 0, 1)).toBe("An agent's session for attempt 1");
  });

  it("the line leads with the words and how long it ran, the id after them", () => {
    const html = renderToStaticMarkup(
      <SessionWords session={SESSION} role="control" index={0} count={1} />,
    );
    const host = document.createElement("div");
    host.innerHTML = html;
    const text = host.textContent;
    expect(text.indexOf("The control agent's session for attempt 2")).toBe(0);
    expect(text).toContain("ended after 22 min");
    expect(text.indexOf("22 min")).toBeLessThan(text.indexOf(SESSION.sessionId));
  });
});

describe("a session shorter than a minute reads in seconds, never as 0 min", () => {
  it("in words", () => {
    expect(durationWords(20)).toBe("20 s");
    expect(durationWords(59.4)).toBe("59 s");
    expect(durationWords(0.4)).toBe("under a second");
    expect(durationWords(90)).toBe("2 min");
  });

  it("on the session's line", () => {
    const html = renderToStaticMarkup(
      <SessionWords
        session={{ ...SESSION, wallClockS: 20.004 }}
        role="control"
        index={0}
        count={1}
      />,
    );
    const host = document.createElement("div");
    host.innerHTML = html;
    expect(host.textContent).toContain("ended after 20 s");
    expect(host.textContent).not.toContain("0 min");
  });
});

const spawn = (seq: number, entered: string, attempt = 1): StepTiming => ({
  seq,
  subtask: SESSION.subtask ?? "",
  attempt,
  stage: "spawn",
  entered,
  seconds: 1,
});

describe("a session started with no end recorded is listed as such", () => {
  const first = "2026-11-03T18:08:28.054947Z";
  const second = "2026-11-03T18:12:46.727238Z";
  const steps = [spawn(295, first, 2), spawn(319, second, 2), spawn(400, second, 3)];

  it("says how many started, how many ended, and what a missing end means", () => {
    expect(unendedWords(steps, [SESSION], SESSION.subtask ?? "", 2)).toBe(
      `1 session of attempt 2 recorded no end: the log enters the spawn stage 2 times for it ` +
        `(at ${clockTime(first)}, ${clockTime(second)}) and records 1 session end. A session ` +
        "with no end is still running, or was stopped before it could record one, as a halted " +
        "or killed run leaves it.",
    );
  });

  it("an attempt with no session ended at all says so in the same words", () => {
    expect(unendedWords(steps, [], SESSION.subtask ?? "", 3)).toBe(
      `1 session of attempt 3 recorded no end: the log enters the spawn stage once for it ` +
        `(at ${clockTime(second)}) and records 0 session ends. A session with no end is still ` +
        "running, or was stopped before it could record one, as a halted or killed run leaves it.",
    );
  });

  it("says nothing when every start has its end", () => {
    expect(unendedWords([spawn(319, second, 2)], [SESSION], SESSION.subtask ?? "", 2)).toBeNull();
  });
});
