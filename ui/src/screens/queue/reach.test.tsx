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

/** The sentence a recorded contract item carries in place of a diff. */
const ARTEFACT =
  `The run branch from ${"e".repeat(40)} to ${"f".repeat(40)}: see ` +
  `\`git diff ${"e".repeat(40)} ${"f".repeat(40)}\` in the target repository.`;

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
      artefact_diff: ARTEFACT,
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
  it("shows no terminal command, its diff's commits named instead", async () => {
    const { namesACommand } = await import("../../rules/commands");
    const host = mount(source, true);
    expect(namesACommand(host.textContent)).toBe(false);
    expect(host.textContent).toContain("f".repeat(40));
  });

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

describe("an item whose diff is the run branch between two commits", () => {
  it("names the two commits and shows no terminal command", async () => {
    const { diffWords } = await import("../../words/queue");
    const { namesACommand } = await import("../../rules/commands");
    const [a, b] = ["e".repeat(40), "3540db9765c4a3576d79fbd0a9c2a33e407ef89e"];
    const said = diffWords(
      `The run branch from ${a} to ${b}: see \`git diff ${a} ${b}\` in the target repository.`,
    );
    expect(said).toContain(a);
    expect(said).toContain(b);
    expect(namesACommand(said)).toBe(false);
    // Any other diff is shown as the item recorded it.
    expect(diffWords("--- a/x\n+++ b/x\n")).toBe("--- a/x\n+++ b/x\n");
  });

  it("names the two commits of a sha256 repository and shows no terminal command", async () => {
    const { diffWords } = await import("../../words/queue");
    const { namesACommand } = await import("../../rules/commands");
    // A target repository in git's sha256 object format records 64-character commit ids.
    const [a, b] = ["c".repeat(64), "0f".repeat(32)];
    const said = diffWords(
      `The run branch from ${a} to ${b}: see \`git diff ${a} ${b}\` in the target repository.`,
    );
    expect(said).toContain(a);
    expect(said).toContain(b);
    expect(namesACommand(said)).toBe(false);
  });
});
