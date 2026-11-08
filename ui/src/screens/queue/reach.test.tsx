// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { itemView } from "../../api/queue";
import { Decide } from "./Decide";
import { QueueItem } from "./QueueItem";

/**
 * Where a person finds the way to decide, on both kinds of item a recorded run raised: the
 * controls come before the long finding, and a page that cannot decide says so first, naming the
 * run's ui.out, where the address that can is.
 */

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;

afterEach(() => {
  act(() => {
    root?.unmount();
  });
  root = null;
  document.body.innerHTML = "";
});

function view(source: "contract" | "review_unavailable") {
  return itemView({
    position: 0,
    item_sha256: "a".repeat(64),
    open: true,
    item: {
      kind: "item",
      item_id: `run-1-${source}`,
      ts: "2026-11-08T12:00:00.000000Z",
      run_id: "run-1",
      subtask_id: source === "contract" ? "contract" : "s1",
      source,
      decision_required: "Decide.",
      artefact_diff: "",
      // As long as a recorded contract item's: one clause per quantity, 23 of them.
      triggering_finding: Array.from(
        { length: 23 },
        (_, i) => `Interface "iface", quantity "q${String(i)}": the consumer is not joined to it.`,
      ).join("\n"),
      quantities: [],
      trajectories: ["/r/sessions/s-1/stdout.jsonl"],
    },
    trajectories: [{ link: "/r/sessions/s-1/stdout.jsonl", session_id: "s-1", status: "holds" }],
  });
}

function mount(source: "contract" | "review_unavailable", holdsToken: boolean): HTMLElement {
  const host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const shown = view(source);
  act(() => {
    root?.render(
      <QueueItem
        view={shown}
        decided={undefined}
        source={{ id: "run run-1", commit: "abcdef1234" }}
        subtaskName="The whole design"
      >
        <Decide
          view={shown}
          runId="run-1"
          operator="yasin"
          holdsToken={holdsToken}
          send={() => new Promise(() => undefined)}
          onDecided={() => undefined}
        />
      </QueueItem>,
    );
  });
  return host;
}

/** Whether ``first`` comes before ``second`` in the page's order. */
function before(host: HTMLElement, first: string, second: string): boolean {
  const a = host.querySelector(first);
  const b = host.querySelector(second);
  expect(a, first).not.toBeNull();
  expect(b, second).not.toBeNull();
  return a !== null && b !== null && (a.compareDocumentPosition(b) & 4) !== 0;
}

describe.each(["contract", "review_unavailable"] as const)("a %s item", (source) => {
  it("puts the decision controls before the finding", () => {
    const host = mount(source, true);
    expect(before(host, ".pg-queue-actions", ".pg-queue-finding")).toBe(true);
    expect(host.querySelector(".pg-queue-why-not")).toBeNull();
  });

  it("says first, on a page that cannot decide, that the address is in the run's ui.out", () => {
    const host = mount(source, false);
    const notice = host.querySelector(".pg-queue-why-not");
    expect(notice?.textContent).toContain("operator address from the run's ui.out");
    expect(before(host, ".pg-queue-why-not", ".pg-queue-actions")).toBe(true);
    expect(before(host, ".pg-queue-why-not", ".pg-queue-finding")).toBe(true);
  });
});
