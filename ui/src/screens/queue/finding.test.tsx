// @vitest-environment happy-dom
/**
 * A long reviewer finding on a queue item reads short first: its opening sentence and the
 * standards it cites, with the whole finding one click away, word for word. A short finding is
 * shown whole, with nothing to open.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { itemView } from "../../api/queue";
import { citedStandards } from "./Finding";
import { QueueItem } from "./QueueItem";

const LONG =
  "The firmware module satisfies all nine numbered acceptance criteria through host unit tests " +
  "and a cycle-accurate simulator, which the specification's scope line allows. " +
  "However, the work itself documents two admitted domain-standard violations: (1) DS-21, no " +
  "static analyser was ever run over the firmware; and (2) DS-17, the firmware carries zero " +
  "runtime assertions. Reading Balance.cpp shows two further confirmed issues: DS-10 and AP-7, " +
  "the application reads and writes registers directly. ".repeat(6) +
  "Do not supply the missing input yourself.";

const SHORT = "The gate found the motor's stall torque below the load.";

function shown(finding: string, source = "repair_budget_exhausted"): HTMLElement {
  const view = itemView({
    position: 0,
    item_sha256: "a".repeat(64),
    open: true,
    item: {
      kind: "item",
      item_id: "run-1-s1",
      ts: "2026-11-08T12:00:00.000000Z",
      run_id: "run-1",
      subtask_id: "s1",
      source,
      decision_required: "Decide.",
      artefact_diff: "",
      triggering_finding: finding,
      quantities: [],
      trajectories: [],
    },
    trajectories: [],
  });
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(
    <QueueItem
      view={view}
      decided={undefined}
      source={{ id: "run run-1", commit: "abcdef1234" }}
      subtaskName="Firmware"
    />,
  );
  return host;
}

/** The text a person reads without opening anything. */
function visible(el: Element): string {
  const copy = el.cloneNode(true) as Element;
  for (const folded of copy.querySelectorAll("details")) folded.remove();
  return copy.textContent;
}

describe("a long reviewer finding reads short first, the whole of it on demand", () => {
  it("shows the opening sentence and the standards cited, a few lines at most", () => {
    const finding = shown(LONG).querySelector(".pg-queue-finding");
    expect(finding).not.toBeNull();
    const text = visible(finding as Element);
    expect(text).toContain("The firmware module satisfies all nine numbered acceptance criteria");
    expect(text).toContain(
      "It names 4 items of the reviewer's rubric, met or not: DS-21, DS-17, DS-10, AP-7.",
    );
    expect(text.length).toBeLessThan(400);
  });

  it("keeps the whole finding, word for word, behind one control a keyboard reaches", () => {
    const finding = shown(LONG).querySelector(".pg-queue-finding");
    const more = finding?.querySelector("details");
    expect(more?.querySelector("summary")?.textContent ?? "").toMatch(
      /^Read the whole finding \(\d+ words\)$/,
    );
    expect(more?.textContent).toContain(LONG.trim());
  });

  it("a short finding is shown whole, with nothing to open", () => {
    const finding = shown(SHORT).querySelector(".pg-queue-finding");
    expect(finding?.querySelector(".pg-queue-finding-text")?.textContent).toBe(SHORT);
    expect(finding?.querySelector("details")).toBeNull();
  });
});

describe("a finding's verdict is in view beside its opening, whatever the opening says", () => {
  it("a rejecting finding that opens with praise reads as rejected before its first word", () => {
    const finding = shown(LONG).querySelector(".pg-queue-finding");
    const text = visible(finding as Element);
    const verdict = "Did not pass: this finding rejected the attempt.";
    expect(text.startsWith(verdict)).toBe(true);
    expect(text.indexOf(verdict)).toBeLessThan(text.indexOf("The firmware module satisfies"));
    expect(finding?.querySelector(".pg-queue-finding-verdict")?.textContent).toBe(verdict);
  });

  it("a short finding carries its verdict too", () => {
    const finding = shown(SHORT, "gate_escalation").querySelector(".pg-queue-finding");
    expect(finding?.querySelector(".pg-queue-finding-verdict")?.textContent).toBe(
      "Did not pass: the gate failed the finished design.",
    );
  });

  it("a blocked review that says every criterion is met still reads as not passed", () => {
    const praise = `All seven acceptance criteria are met. ${"The evidence is sealed. ".repeat(20)}`;
    const finding = shown(praise, "review_blocked").querySelector(".pg-queue-finding");
    expect(visible(finding as Element)).toMatch(
      /^Did not pass: the review was blocked on a safety-critical check, whatever the finding says is met\. All seven/,
    );
  });

  it("a review with no verdict says so, and a parts question claims no verdict at all", () => {
    expect(
      shown("the session ended with api_error", "review_unavailable").querySelector(
        ".pg-queue-finding-verdict",
      )?.textContent,
    ).toBe("No verdict: the review neither passed nor rejected the attempt.");
    expect(
      shown("Which parts do you have?", "parts").querySelector(".pg-queue-finding-verdict"),
    ).toBeNull();
  });
});

describe("only the rubric's own item ids count as items cited", () => {
  it("counts a rubric's ids, a control item's unhyphened one too, and no look-alike", () => {
    const cited = citedStandards(
      "Checked with SHA-256 and AES-128 over USB-3; DRV8838 on ICR1 with E402 and C1. " +
        "DS-21 unmet, DS-10c partly, D33 and D21 unmet, SS-6 met, AP-7 met, PS-12 met.",
    );
    expect(cited).toEqual(["DS-21", "DS-10c", "D33", "D21", "SS-6", "AP-7", "PS-12"]);
  });
});
