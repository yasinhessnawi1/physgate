// @vitest-environment happy-dom
/**
 * The plan's review that did not pass is a queue item of its own: the app reads it, says what kind
 * it is and why a person is asked, what approve and reject do from the item's own fields, and what
 * the run did with the decision it took. Its one trajectory is the decomposition's stream.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { EFFECTS, itemView, ON_APPROVE, ON_REJECT, queueListing, SOURCES } from "../../api/queue";
import {
  bannedIn,
  consequenceWords,
  queueHeadline,
  SOURCE_WORDS,
  takenWords,
} from "../../words/queue";
import { QueueItem } from "./QueueItem";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const DIGEST = "a".repeat(64);
const LINK = "/r/decomposition/stdout.jsonl";

function raw(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    position: 0,
    item_sha256: DIGEST,
    open: true,
    item: {
      kind: "item",
      item_id: "run-1-plan",
      ts: "2026-10-31T09:00:00.000000Z",
      run_id: "run-1",
      subtask_id: "plan",
      source: "plan_review",
      decision_required: "The design reviewer did not pass the plan. Approve or reject.",
      artefact_diff: "The plan of digest d, as the run recorded it.",
      triggering_finding: "the plan leaves the bus unprotected",
      quantities: [],
      trajectories: [LINK],
      consequence: {
        attempt: null,
        attempt_commit: null,
        on_approve: "release",
        on_reject: "end_run",
        why_record_only: null,
        confirmed_indicators: [],
        scan_hits: [],
      },
      ...over,
    },
    trajectories: [{ link: LINK, session_id: "decomposition/stdout.jsonl", status: "holds" }],
  };
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

describe("the plan's review item", () => {
  it("is a source, and its verbs release the hold or end the run", () => {
    expect(SOURCES).toContain("plan_review");
    expect(ON_APPROVE).toContain("release");
    expect(ON_REJECT).toContain("end_run");
    expect(EFFECTS).toEqual(expect.arrayContaining(["release", "end_run"]));
  });

  it("is read whole, with the decomposition's stream as its trajectory", () => {
    expect(SOURCES).toContain("plan_review");
    const view = itemView(raw());
    expect(view.item.source).toBe("plan_review");
    expect(view.item.consequence?.onApprove).toBe("release");
    expect(view.item.consequence?.onReject).toBe("end_run");
    expect(view.trajectories[0]?.status).toBe("holds");
  });

  it("says what kind it is, why a person is asked, and what each verb does", () => {
    expect(Object.keys(SOURCE_WORDS)).toContain("plan_review");
    expect(SOURCE_WORDS.plan_review.kind).toBe("The plan's review did not pass");
    expect(SOURCE_WORDS.plan_review.why).toMatch(/^[A-Z].*\.$/);
    expect(SOURCE_WORDS.plan_review.why).toContain("nothing is dispatched");
    const view = itemView(raw());
    expect(queueHeadline(view.item)).toBe("The plan's review did not pass");
    const words = consequenceWords(view.item.consequence ?? (null as never));
    expect(words.approveLabel).toBe("Approve…");
    expect(words.approve).toBe("Approve: the hold is released, and the plan runs as it stands.");
    expect(words.reject).toBe(
      "Reject: the run ends with no module dispatched, and your reason is recorded. A new run " +
        "is a new decomposition.",
    );
    for (const sentence of [words.approve, words.reject, SOURCE_WORDS.plan_review.why])
      expect(bannedIn(sentence), sentence).toEqual([]);
    const host = mount(
      <QueueItem
        view={view}
        decided={undefined}
        source={{ id: "run run-1", commit: "abcdef1234" }}
        subtaskName="The whole design"
      />,
    );
    expect(host.textContent).toContain(words.approve);
    expect(host.textContent).toContain(words.reject);
  });

  it("says what the run did with the decision it took", () => {
    expect(EFFECTS).toEqual(expect.arrayContaining(["release", "end_run"]));
    const listing = queueListing({
      open: [],
      decided: (["release", "end_run"] as const).map((effect) => ({
        item_id: "run-1-plan",
        ts: "t",
        decision: effect === "release" ? "approve" : "reject: no",
        resolved_by: "yasin",
        flag: null,
        taken: { effect, acts: true, why_not: null, confirmed_by: null, order_too_long: false },
      })),
    });
    const [released, ended] = listing.decided.map((d) => takenWords(d.taken ?? (null as never)));
    expect(released).toBe(
      "The run took it: the hold was released, and the plan runs as it stands.",
    );
    expect(ended).toBe("The run took it: the run ended with no module dispatched.");
  });
});
