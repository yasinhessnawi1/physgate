// @vitest-environment happy-dom
/**
 * An attempt's session is named in words a person reads first (whose session, for which attempt,
 * and how long it ran), its id after that, never as its only label.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { SessionTrace } from "../../api/run";
import { SessionWords, sessionLabel } from "./AttemptInspector";

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
