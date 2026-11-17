// @vitest-environment happy-dom
/**
 * Every decision's confirmation, whichever panel opens it, names the run's state the same way:
 * one call to ``RunStateNote`` inside the queue item, which provides where the run stands.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { decisionPendingWords, type Phase } from "../../words/standing";
import { RunPhaseContext } from "./runPhase";
import { RunStateNote } from "./RunStateNote";

const inRun = (phase: Phase | undefined) =>
  renderToStaticMarkup(
    <RunPhaseContext.Provider value={phase}>
      <RunStateNote />
    </RunPhaseContext.Provider>,
  );

describe("a confirmation's line on the run's state comes from one call", () => {
  it.each(["done", "halted", "stopped", "waiting-person", "waiting-limit", "halt-owed"] as const)(
    "a %s run: the line, in the confirmation's note style",
    (phase) => {
      const html = inRun(phase);
      expect(html).toContain('class="pg-dialog-note pg-dialog-run-state"');
      expect(html).toContain(String(decisionPendingWords(phase)));
    },
  );

  it("a going run, or one whose status is not read yet: nothing", () => {
    expect(inRun("going")).toBe("");
    expect(inRun(undefined)).toBe("");
  });

  it("an ended run says it has ended and that the decision waits for a resume", () => {
    expect(inRun("done")).toContain(
      "This run has ended. The decision is recorded now and taken up when the run is resumed.",
    );
  });
});
