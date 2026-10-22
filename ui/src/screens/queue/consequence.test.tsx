// @vitest-environment happy-dom
/**
 * An item that says what each verb will do is shown with exactly that, from its own fields; an
 * item that says nothing is shown as before. A decision the run took says what the run did.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { ShapeError } from "../../api/client";
import { itemView, queueListing } from "../../api/queue";
import {
  APPROVE_RECORDS_ONLY,
  bannedIn,
  consequenceWords,
  DECISION_COPY,
  takenWords,
} from "../../words/queue";
import { attemptsWords } from "../run-records/ledgerRows";
import { Decide } from "./Decide";
import { lineToWrite } from "./model";
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

function raw(c: Record<string, unknown> | null): Record<string, unknown> {
  return {
    position: 0,
    item_sha256: DIGEST,
    open: true,
    item: {
      kind: "item",
      item_id: "run-1-s1",
      ts: "2026-10-21T09:00:00.000000Z",
      run_id: "run-1",
      subtask_id: "s1",
      source: "review_unavailable",
      decision_required: "The review of subtask s1, attempt 1, reached no verdict. Decide.",
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

const SOURCE = { id: "run run-1", commit: "abcdef1234" };

function decide(view: ReturnType<typeof itemView>): HTMLElement {
  return mount(
    <QueueItem view={view} decided={undefined} source={SOURCE} subtaskName="Control module">
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
}

describe("an item that says what each verb will do", () => {
  it("shows what approve and reject do, from the item's own fields", () => {
    const view = itemView(raw(consequence()));
    const host = decide(view);
    const words = consequenceWords(view.item.consequence ?? (null as never));
    expect(host.textContent).toContain("If you approve");
    expect(host.textContent).toContain(words.approve);
    expect(host.textContent).toContain(`attempt 1 (commit ${COMMIT.slice(0, 12)})`);
    expect(host.textContent).toContain(words.reject);
    expect(host.textContent).toContain("Approve…");
    expect(host.textContent).not.toContain(APPROVE_RECORDS_ONLY);
  });

  it("approve reads records only and names the indicator", () => {
    const view = itemView(
      raw(
        consequence({
          on_approve: "record_only",
          why_record_only: "indicator_in_history",
          confirmed_indicators: [{ attempt: 1, kind: "disabled_checks" }],
        }),
      ),
    );
    const host = decide(view);
    expect(host.textContent).toContain(APPROVE_RECORDS_ONLY);
    expect(host.textContent).toContain(
      "Approve records only: the review of attempt 1 (disabled_checks) confirmed a " +
        "reward-hacking indicator.",
    );
  });

  it("says a reject after a blocked review orders one fix by a fresh session", () => {
    const words = consequenceWords(
      itemView(raw(consequence({ on_reject: "fix" }))).item.consequence ?? (null as never),
    );
    expect(words.reject).toContain("one fix is made by a fresh session");
    expect(words.reject).toContain("last attempt");
  });

  it("says nothing of what a verb does on an item that does not say", () => {
    const view = itemView(raw(null));
    expect(view.item.consequence).toBeNull();
    const host = decide(view);
    expect(host.textContent).not.toContain("If you approve");
    expect(DECISION_COPY.then).toContain("Nothing else happens in this run");
  });

  it("refuses a consequence of another shape, whole", () => {
    expect(() => itemView(raw(consequence({ on_approve: "merge_everything" })))).toThrow(
      ShapeError,
    );
    expect(() => itemView(raw(consequence({ attempt_commit: "not-a-commit" })))).toThrow(
      ShapeError,
    );
  });

  it("holds no banned word in any sentence it can say", () => {
    const all = (["merge_attempt", "record_only"] as const).flatMap((onApprove) =>
      (["retry", "fix", "end_subtask", "record_only"] as const).flatMap((onReject) => {
        const view = itemView(
          raw(
            consequence({
              on_approve: onApprove,
              on_reject: onReject,
              why_record_only: onApprove === "record_only" ? "gate" : null,
            }),
          ),
        );
        const words = consequenceWords(view.item.consequence ?? (null as never));
        return [words.approve, words.reject];
      }),
    );
    for (const sentence of all) expect(bannedIn(sentence), sentence).toEqual([]);
  });
});

describe("the line a decision writes", () => {
  it("names the verb, the note and the digest of the view, as the queue writes them", () => {
    const view = itemView(raw(consequence()));
    expect(lineToWrite(view, "reject", "split it", "yasin")).toBe(
      '{"item_id":"run-1-s1","ts":"‹the time you confirm›","kind":"resolution",' +
        `"decision":"reject: split it","resolved_by":"yasin","verb":"reject","note":"split it",` +
        `"shown_sha256":"${DIGEST}"}`,
    );
    expect(lineToWrite(view, "approve", " ", "yasin")).toBe(
      '{"item_id":"run-1-s1","ts":"‹the time you confirm›","kind":"resolution",' +
        `"decision":"approve","resolved_by":"yasin","verb":"approve","shown_sha256":"${DIGEST}"}`,
    );
  });
});

describe("what the run did with a decision", () => {
  it("is read from the run's record and shown on the decided item", () => {
    const listing = queueListing({
      open: [],
      decided: [
        {
          item_id: "run-1-s1",
          ts: "t",
          decision: "approve",
          resolved_by: "yasin",
          flag: null,
          taken: {
            effect: "merge",
            acts: true,
            why_not: null,
            confirmed_by: null,
            order_too_long: false,
          },
        },
      ],
    });
    const [decided] = listing.decided;
    expect(decided?.taken).toEqual({
      effect: "merge",
      acts: true,
      whyNot: null,
      confirmedBy: null,
      orderTooLong: false,
    });
    const view = itemView({ ...raw(consequence()), open: false });
    const host = mount(
      <QueueItem view={view} decided={decided} source={SOURCE} subtaskName="Control module" />,
    );
    expect(host.textContent).toContain("What the run did");
    expect(host.textContent).toContain("The run took it: the attempt it names was merged.");
  });

  it("says a held decision waits for the operator, and who confirmed one", () => {
    expect(
      takenWords({
        effect: "merge",
        acts: false,
        whyNot: "held_os_layer_off",
        confirmedBy: null,
        orderTooLong: false,
      }),
    ).toContain("acts only once an operator confirms it");
    expect(
      takenWords({
        effect: "merge",
        acts: true,
        whyNot: null,
        confirmedBy: "operator",
        orderTooLong: false,
      }),
    ).toContain("Confirmed on the command line by operator.");
    expect(
      takenWords({
        effect: "none",
        acts: false,
        whyNot: "scan_hit",
        confirmedBy: null,
        orderTooLong: false,
      }),
    ).toBe("Recorded only (scan_hit).");
  });

  it("says a reject ended the subtask when the session it ordered could not be reviewed", () => {
    const words = takenWords({
      effect: "end_subtask",
      acts: true,
      whyNot: null,
      confirmedBy: null,
      orderTooLong: true,
    });
    expect(words).toContain("the subtask ended rejected, and no session was started");
    expect(words).toContain("longer than its reviewer can read whole");
  });

  it("refuses a taken decision that does not say whether its order was too long", () => {
    expect(() =>
      queueListing({
        open: [],
        decided: [
          {
            item_id: "x",
            ts: "t",
            decision: "reject: n",
            resolved_by: "y",
            flag: null,
            taken: { effect: "end_subtask", acts: true, why_not: null, confirmed_by: null },
          },
        ],
      }),
    ).toThrow();
  });

  it("a decision the run has not taken carries nothing", () => {
    const listing = queueListing({
      open: [],
      decided: [{ item_id: "x", ts: "t", decision: "approve", resolved_by: "y", flag: null }],
    });
    expect(listing.decided[0]?.taken).toBeNull();
  });
});

describe("an attempt past the budget", () => {
  it("is the one fix a person ordered, never four of three", () => {
    expect(attemptsWords({ attempts: 4, budget: 3 })).toBe(
      "3 of 3, then the one fix a person ordered",
    );
    expect(attemptsWords({ attempts: 2, budget: 3 })).toBe("2 of 3");
  });
});
