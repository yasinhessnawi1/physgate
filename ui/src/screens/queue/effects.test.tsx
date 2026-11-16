// @vitest-environment happy-dom
/**
 * Beside the buttons, before a person decides, every item says in plain words what each decision
 * will do, from its own consequence record and nothing else: an approve that only records says so
 * and why; an item that states no consequence says nothing extra.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { itemView } from "../../api/queue";
import { bannedIn } from "../../words/queue";
import { Decide } from "./Decide";
import { QueueItem } from "./QueueItem";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const DIGEST = "a".repeat(64);
const COMMIT = "c".repeat(40);

function consequence(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    attempt: 1,
    attempt_commit: COMMIT,
    on_approve: "merge_attempt",
    on_reject: "retry",
    why_record_only: null,
    confirmed_indicators: [],
    scan_hits: [],
    ...over,
  };
}

function raw(
  c: Record<string, unknown> | null,
  source = "review_unavailable",
): Record<string, unknown> {
  return {
    position: 0,
    item_sha256: DIGEST,
    open: true,
    item: {
      kind: "item",
      item_id: "run-1-s1",
      ts: "2026-11-16T09:00:00.000000Z",
      run_id: "run-1",
      subtask_id: "s1",
      source,
      decision_required: "Decide.",
      artefact_diff: "--- a/x\n+++ b/x\n",
      triggering_finding: "no verdict",
      quantities: [],
      trajectories: ["/r/sessions/s-1/stdout.jsonl"],
      ...(c === null ? {} : { consequence: c }),
    },
    trajectories: [{ link: "/r/sessions/s-1/stdout.jsonl", session_id: "s-1", status: "holds" }],
  };
}

let root: Root | null = null;
afterEach(() => {
  act(() => {
    root?.unmount();
  });
  root = null;
  document.body.innerHTML = "";
});

function decide(c: Record<string, unknown> | null, source?: string): HTMLElement {
  const view = itemView(raw(c, source));
  const host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  act(() => {
    root?.render(
      <QueueItem
        view={view}
        decided={undefined}
        source={{ id: "run run-1", commit: "abcdef1234" }}
        subtaskName="Control module"
      >
        <Decide
          view={view}
          runId="run-1"
          operator="yasin"
          holdsToken
          send={() => new Promise(() => undefined)}
          onDecided={() => undefined}
        />
      </QueueItem>,
    );
  });
  return host;
}

function beside(host: HTMLElement, verb: string): string {
  return host.querySelector(`.pg-queue-effects [data-verb="${verb}"]`)?.textContent ?? "";
}

describe("what each decision will do, beside the buttons", () => {
  it("says an approve that only records will not merge, and why", () => {
    const host = decide(
      consequence({ on_approve: "record_only", why_record_only: "gate", on_reject: "fix" }),
    );
    expect(beside(host, "approve")).toBe(
      "Approving records your decision. It will not merge this attempt, because the physics " +
        "gate refused the attempt, and a person overrides the reviewer alone.",
    );
    expect(beside(host, "reject")).toBe(
      "Rejecting orders one fix by a fresh session, the subtask's last attempt. If it is not " +
        "accepted, the subtask ends rejected.",
    );
  });

  it("says nothing is merged or changed on an item whose kind only records", () => {
    const host = decide(
      consequence({
        attempt: null,
        attempt_commit: null,
        on_approve: "record_only",
        on_reject: "record_only",
        why_record_only: "source",
      }),
    );
    expect(beside(host, "approve")).toBe(
      "Approving records your decision. It will not merge or change anything, because for an " +
        "item of this kind a decision is recorded and changes nothing in the run.",
    );
    expect(beside(host, "reject")).toBe(
      "Rejecting records your decision. It will not change anything in the run, because for an " +
        "item of this kind a decision is recorded and changes nothing in the run.",
    );
  });

  it("names a confirmed indicator as the reason", () => {
    const host = decide(
      consequence({
        on_approve: "record_only",
        why_record_only: "indicator_in_history",
        confirmed_indicators: [{ attempt: 2, kind: "disabled_checks" }],
      }),
    );
    expect(beside(host, "approve")).toBe(
      "Approving records your decision. It will not merge this attempt, because the review of " +
        "attempt 2 (disabled_checks) confirmed a reward-hacking indicator.",
    );
  });

  it("says what an approve that acts does", () => {
    const host = decide(consequence({ attempt: 3 }));
    expect(beside(host, "approve")).toBe(
      `Approving puts attempt 3 (commit ${COMMIT.slice(0, 12)}) into the run, merged exactly as shown.`,
    );
    expect(beside(host, "reject")).toBe(
      "Rejecting spends this attempt, and the next attempt starts from your note.",
    );
  });

  it("says what each choice of a choice item does", () => {
    const host = decide(
      consequence({
        attempt: null,
        attempt_commit: null,
        on_approve: "record_only",
        on_reject: "record_only",
        why_record_only: "source",
        on_choose: { sizing: "fix", domain: "resize" },
      }),
      "arbitration",
    );
    expect(beside(host, "sizing")).toMatch(
      /^Choosing sizing's value: one fix is made by a fresh session/,
    );
    expect(beside(host, "domain")).toMatch(
      /^Choosing the domain's value: the subtask waits while sizing's closing pass/,
    );
  });

  it("says nothing extra when the item states no consequence", () => {
    const host = decide(null);
    expect(host.querySelector(".pg-queue-effects")).toBeNull();
  });

  it("holds no banned word in any sentence", () => {
    const host = decide(
      consequence({ on_approve: "record_only", why_record_only: "gate", on_reject: "fix" }),
    );
    for (const verb of ["approve", "reject"])
      expect(bannedIn(beside(host, verb)), verb).toEqual([]);
  });
});
