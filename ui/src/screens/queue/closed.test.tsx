// @vitest-environment happy-dom
/**
 * A decision is offered on every open item, whatever the run's state. On a run that has ended,
 * halted or stopped, or that waits for a person, the loop takes a queued decision up at its next
 * boundary once the run is resumed, so the decision is valid: the page says so in one line beside
 * the buttons, and the confirmation names the run's state. Nothing a decision does changes.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { itemView } from "../../api/queue";
import { decisionPendingWords, type Phase } from "../../words/standing";
import { Decide } from "./Decide";
import { QueueItem } from "./QueueItem";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

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
    trajectories: ["/r/sessions/s-1/stdout.jsonl"],
  },
  trajectories: [{ link: "/r/sessions/s-1/stdout.jsonl", session_id: "s-1", status: "holds" }],
});

const RESUMED = "The decision is recorded now and taken up when the run is resumed.";

const NOT_GOING: readonly (readonly [Phase, string])[] = [
  ["done", "This run has ended."],
  ["stopped", "This run appears to have stopped."],
  ["halted", "This run is halted."],
  ["halt-owed", "This run is halted."],
  ["waiting-limit", "This run is halted until the usage limit resets."],
  ["waiting-person", "This run is waiting for a person's decision."],
];

function item(phase: Phase | undefined) {
  return (
    <QueueItem
      view={VIEW}
      decided={undefined}
      source={{ id: "run run-1", commit: "abcdef1234" }}
      subtaskName="Control module"
      phase={phase}
    >
      <Decide
        view={VIEW}
        runId="run-1"
        operator="yasin"
        holdsToken
        send={vi.fn()}
        onDecided={vi.fn()}
      />
    </QueueItem>
  );
}

let root: Root | null = null;
function mount(node: React.ReactNode): HTMLElement {
  const host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  act(() => {
    root?.render(node);
  });
  return host;
}

afterEach(() => {
  act(() => {
    root?.unmount();
  });
  root = null;
  document.body.innerHTML = "";
});

const approve = (host: HTMLElement) =>
  [...host.querySelectorAll<HTMLButtonElement>("button")].find((b) =>
    b.textContent.includes("Approve"),
  );

describe("a decision is offered on an open item in every run state", () => {
  it.each(NOT_GOING)("a %s run: one line says so beside the buttons", (phase, state) => {
    expect(decisionPendingWords(phase)).toBe(`${state} ${RESUMED}`);
  });

  it("a run that is going needs no such line", () => {
    expect(decisionPendingWords("going")).toBeNull();
  });

  it.each(NOT_GOING)("a %s run keeps its decision buttons, enabled", (phase, state) => {
    const host = mount(item(phase));
    const button = approve(host);
    expect(button).toBeDefined();
    expect(button?.disabled).toBe(false);
    const line = host.querySelector(".pg-queue-pending");
    expect(line?.textContent).toBe(`${state} ${RESUMED}`);
    // The line sits beside the buttons, in the same part of the item.
    expect(line?.parentElement?.querySelector(".pg-queue-decide")).not.toBeNull();
  });

  it("a going run shows the buttons and no line", () => {
    const html = renderToStaticMarkup(item("going"));
    expect(html).toContain("Approve");
    expect(html).not.toContain("pg-queue-pending");
    expect(html).not.toContain(RESUMED);
  });

  it("the confirmation names the run's state before anything is recorded", () => {
    const host = mount(item("done"));
    act(() => {
      approve(host)?.click();
    });
    const dialog = [...host.querySelectorAll("dialog")].find((d) => d.open);
    expect(dialog?.textContent).toContain(`This run has ended. ${RESUMED}`);
  });

  it("a going run's confirmation adds nothing about a resume", () => {
    const host = mount(item("going"));
    act(() => {
      approve(host)?.click();
    });
    const dialog = [...host.querySelectorAll("dialog")].find((d) => d.open);
    expect(dialog?.textContent).toContain("Approve this item?");
    expect(dialog?.textContent).not.toContain(RESUMED);
  });

  it("no line says a decision is not offered, in any state", () => {
    for (const [phase] of NOT_GOING)
      expect(renderToStaticMarkup(item(phase))).not.toContain("no decision is offered");
  });
});
