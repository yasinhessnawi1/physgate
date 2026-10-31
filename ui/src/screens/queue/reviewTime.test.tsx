// @vitest-environment happy-dom
/**
 * A decision's review time is the server's: the page reads the chosen item's view again when it is
 * chosen, sends back the id the server stamped it under and never a time, and shows how long the
 * decision took from what the queue's listing says. An item a reopen superseded says so before
 * anyone decides, and what the run did with a decision on it says so after.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { forgetToken, takeTokenFromAddress } from "../../api/client";
import { decisionRequest, type Decided, itemView, queueListing } from "../../api/queue";
import { runStatus } from "../../api/run";
import { bannedIn, reviewTimeWords, supersededWords, takenWords } from "../../words/queue";
import Queue from "./Queue";
import { QueueItem } from "./QueueItem";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const DIGEST = "a".repeat(64);
const FIRST = "A".repeat(22);
const CHOSEN = "B".repeat(22);

function rawItem(): Record<string, unknown> {
  return {
    kind: "item",
    item_id: "run-esc-s1",
    ts: "2026-10-11T09:00:00.000000Z",
    run_id: "run-esc",
    subtask_id: "s1",
    source: "repair_budget_exhausted",
    decision_required: "Subtask s1 was rejected on all 3 attempts. Decide.",
    artefact_diff: "",
    triggering_finding: "the stall current is too high",
    quantities: [],
    trajectories: ["/r/sessions/s-1/stdout.jsonl"],
  };
}

function rawView(viewId?: string, open = true): Record<string, unknown> {
  return {
    position: 0,
    item_sha256: DIGEST,
    open,
    item: rawItem(),
    trajectories: [{ link: "/r/sessions/s-1/stdout.jsonl", session_id: "s-1", status: "holds" }],
    ...(viewId === undefined ? {} : { view_id: viewId }),
  };
}

function decided(over: Partial<Decided> = {}): Decided {
  return {
    itemId: "run-esc-s1",
    ts: "2026-10-11T10:00:00.000000Z",
    decision: "approve",
    resolvedBy: "yasin",
    flag: null,
    taken: null,
    reviewTime: null,
    decompositionDefect: false,
    ...over,
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
  document.head.innerHTML = "";
  vi.restoreAllMocks();
  forgetToken();
});

describe("the view's id goes back with the decision, and no time does", () => {
  it("is read from the view, and is null on a view without one", () => {
    expect(itemView(rawView(CHOSEN)).viewId).toBe(CHOSEN);
    expect(itemView(rawView()).viewId).toBeNull();
  });

  it("the request carries the view's id, and nothing that is a time", () => {
    const sent = JSON.parse(decisionRequest(itemView(rawView(CHOSEN)), "approve", "")) as Record<
      string,
      unknown
    >;
    expect(sent.view_id).toBe(CHOSEN);
    expect(Object.keys(sent).sort()).toEqual(["item_id", "note", "shown", "verb", "view_id"]);
    const without = JSON.parse(decisionRequest(itemView(rawView()), "approve", "")) as object;
    expect(Object.keys(without)).not.toContain("view_id");
  });
});

describe("the time to decide is the listing's", () => {
  function listed(entry: Record<string, unknown>): Decided | undefined {
    return queueListing({
      open: [],
      decided: [
        {
          item_id: "run-esc-s1",
          ts: "t",
          decision: "approve",
          resolved_by: "yasin",
          flag: null,
          ...entry,
        },
      ],
    }).decided[0];
  }

  it("reads the review time in seconds and the defect mark, and none where none is recorded", () => {
    const late = listed({
      review_time: { value: 67.000001, unit: "s" },
      shown_at: "x",
      decomposition_defect: true,
    });
    expect([late?.reviewTime, late?.decompositionDefect]).toEqual([
      { value: 67.000001, unit: "s" },
      true,
    ]);
    const none = listed({ review_time: null });
    expect([none?.reviewTime, none?.decompositionDefect]).toEqual([null, false]);
  });

  it("refuses a review time in another unit, negative, or with no number", () => {
    for (const bad of [{ value: 3, unit: "ms" }, { value: -1, unit: "s" }, { unit: "s" }, 4])
      expect(() => listed({ review_time: bad })).toThrow();
  });

  it("says each case in its own sentence", () => {
    expect(reviewTimeWords(decided({ reviewTime: { value: 42.4, unit: "s" } }))).toBe(
      "42 s, from when this server showed the item to when the decision was written.",
    );
    expect(
      reviewTimeWords(
        decided({ reviewTime: { value: 67.2, unit: "s" }, decompositionDefect: true }),
      ),
    ).toBe(
      "1 min 7 s, from when this server showed the item to when the decision was written. " +
        "Over one minute: the record marks the item a decomposition defect, a sign the design " +
        "was split too coarsely to decide in a minute.",
    );
    expect(reviewTimeWords(decided())).toBe(
      "None recorded: the decision was not made on a view this server showed and still held " +
        "(it was made on the command line, or the server had started again).",
    );
  });

  it("a decided item shows its time to decide, in words no screen may not use", () => {
    const host = mount(
      <QueueItem
        view={itemView(rawView(undefined, false))}
        decided={decided({ reviewTime: { value: 42, unit: "s" } })}
        source={{ id: "run run-esc", commit: "abcdef1234" }}
        subtaskName="Subtask 1"
      />,
    );
    const dd = host.querySelector(".pg-queue-review-time");
    expect(dd?.previousElementSibling?.textContent).toBe("Time to decide");
    expect(dd?.textContent).toBe(
      "42 s, from when this server showed the item to when the decision was written.",
    );
    expect(bannedIn(host.textContent)).toEqual([]);
  });
});

describe("a superseded item says so", () => {
  it("before anyone decides, naming the item whose choice reopened its module", () => {
    const host = mount(
      <QueueItem
        view={itemView(rawView())}
        decided={undefined}
        source={{ id: "run run-esc", commit: "abcdef1234" }}
        subtaskName="Subtask 1"
        supersededBy="run-1-contract-1"
      >
        <p>buttons</p>
      </QueueItem>,
    );
    const note = host.querySelector(".pg-queue-superseded");
    expect(note?.textContent).toBe(
      "A choice on run-1-contract-1 reopened a module this item is about, so what it says is no " +
        "longer true. A decision on it is recorded only. The run lists the contract again if it " +
        "still fails once that module is merged again.",
    );
    expect(note?.textContent).toBe(supersededWords("run-1-contract-1"));
    expect(bannedIn(host.textContent)).toEqual([]);
    const plain = mount(
      <QueueItem
        view={itemView(rawView())}
        decided={undefined}
        source={{ id: "run run-esc", commit: "abcdef1234" }}
        subtaskName="Subtask 1"
      />,
    );
    expect(plain.querySelector(".pg-queue-superseded")).toBeNull();
  });

  it("after, in what the run did with the decision", () => {
    const words = takenWords({
      effect: "none",
      acts: false,
      whyNot: "superseded",
      confirmedBy: null,
      orderTooLong: false,
    });
    expect(words).toBe(
      "Recorded only: a choice on another item reopened a module this item is about, so what it " +
        "said was no longer true.",
    );
    expect(bannedIn(words)).toEqual([]);
  });

  it("the status names each superseded item and each subtask that waits", () => {
    const status = runStatus({
      next_step: { kind: "wait", subtask_id: null },
      halted: null,
      owed_halt: null,
      completion: { owner: false, modules: [] },
      waiting: ["s1"],
      superseded: { "run-1-contract-2": "run-1-contract-1" },
    });
    expect([status.waiting, status.superseded]).toEqual([
      ["s1"],
      { "run-1-contract-2": "run-1-contract-1" },
    ]);
    expect(() =>
      runStatus({
        next_step: { kind: "wait", subtask_id: null },
        halted: null,
        owed_halt: null,
        completion: { owner: false, modules: [] },
        waiting: [1],
        superseded: {},
      }),
    ).toThrow();
  });
});

describe("the queue page reads the chosen item's view again when it is chosen", () => {
  const BASE = "/api/runs/0/r";
  const ANSWERS: Record<string, unknown> = {
    "/api/runs": {
      runs: [{ root: 0, name: "r", run_id: "run-esc", manifest_id: "m", gate_mode: "on" }],
    },
    [`${BASE}/config`]: {
      manifest_id: "m",
      config: {
        run_id: "run-esc",
        gate_mode: "on",
        harness: { commit: null },
        auth: "subscription",
        brief_sha256: "b",
        seed: 1,
        models: { roles: {}, decomposition: null },
      },
    },
    [`${BASE}/status`]: {
      next_step: { kind: "done", subtask_id: null },
      halted: null,
      owed_halt: null,
      completion: { owner: false, modules: [] },
      waiting: [],
      superseded: {},
    },
    [`${BASE}/queue`]: { open: [rawItem()], decided: [] },
  };

  async function mounted(status: Record<string, unknown> = {}): Promise<{
    host: HTMLElement;
    views: string[];
    posted: string[];
  }> {
    window.history.replaceState(null, "", "/#act=tok");
    takeTokenFromAddress();
    const meta = document.createElement("meta");
    meta.name = "physgate-operator";
    meta.content = "yasin";
    document.head.append(meta);
    const views = [FIRST, CHOSEN];
    const posted: string[] = [];
    const answers: Record<string, unknown> = {
      ...ANSWERS,
      [`${BASE}/status`]: { ...(ANSWERS[`${BASE}/status`] as object), ...status },
    };
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      let body: unknown;
      if (init?.method === "POST") {
        posted.push(typeof init.body === "string" ? init.body : "");
        body = {
          resolved: { item_id: "run-esc-s1", ts: "t", decision: "approve", resolved_by: "yasin" },
        };
      } else if (url === `${BASE}/queue/items/0`) body = rawView(views.shift() ?? "C".repeat(22));
      else if (url === `${BASE}/events`) return Promise.resolve(new Response(""));
      else body = answers[url];
      return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
    });
    const host = mount(<Queue setHeader={vi.fn()} query={new URLSearchParams()} />);
    for (let i = 0; i < 12; i += 1)
      await act(async () => {
        await Promise.resolve();
      });
    return { host, views, posted };
  }

  it("says so on an item the status names superseded, and on no other", async () => {
    const { host } = await mounted({ superseded: { "run-esc-s1": "run-1-contract-1" } });
    expect(host.querySelector(".pg-queue-superseded")?.textContent).toBe(
      supersededWords("run-1-contract-1"),
    );
  });

  it("and the decision sends the id of that view", async () => {
    const { host, views, posted } = await mounted();
    // Read once for the list, and once more because it is the item chosen.
    expect(views).toEqual([]);
    const approve = [...host.querySelectorAll("button")].find((b) =>
      b.textContent.startsWith("Approve"),
    );
    act(() => {
      approve?.click();
    });
    const dialog = [...host.querySelectorAll("dialog")].find((d) => d.open);
    const confirm = [...(dialog?.querySelectorAll("button") ?? [])].find(
      (b) => b.textContent === "Approve",
    );
    await act(async () => {
      confirm?.click();
      await Promise.resolve();
    });
    expect(posted).toHaveLength(1);
    const sent = JSON.parse(posted[0] ?? "{}") as Record<string, unknown>;
    expect(sent.view_id).toBe(CHOSEN);
  });
});
