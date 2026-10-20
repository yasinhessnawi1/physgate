// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  actToken,
  forgetToken,
  pageOperator,
  postAction,
  ShapeError,
  takeTokenFromAddress,
} from "../../api/client";
import {
  decisionRequest,
  decisionText,
  isBlank,
  type ItemView,
  itemView,
  queueListing,
  type Resolved,
  STATUSES,
} from "../../api/queue";
import { DECISION_COPY, bannedIn, queueHeadline } from "../../words/queue";
import { Decide } from "./Decide";
import { chosenItem, lineToWrite, SEAL_TAG, sealLine, whyNot } from "./model";
import { QueueItem } from "./QueueItem";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const DIGEST = "a".repeat(64);

function rawView(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    position: 0,
    item_sha256: DIGEST,
    open: true,
    item: {
      kind: "item",
      item_id: "run-esc-s1",
      ts: "2026-10-11T09:00:00.000000Z",
      run_id: "run-esc",
      subtask_id: "s1",
      source: "repair_budget_exhausted",
      decision_required: "Subtask s1 was rejected on all 3 attempts. Decide.",
      artefact_diff: "--- a/x\n+++ b/x\n",
      triggering_finding: "the stall current is too high",
      quantities: [{ node_id: "electrical.motor", name: "stall_current", value: 3.4, unit: "A" }],
      trajectories: ["/r/sessions/s-1/stdout.jsonl", "/r/sessions/s-2/stdout.jsonl"],
    },
    trajectories: [
      { link: "/r/sessions/s-1/stdout.jsonl", session_id: "s-1", status: "holds" },
      { link: "/r/sessions/s-2/stdout.jsonl", session_id: "s-2", status: "tampered" },
    ],
    ...overrides,
  };
}

const VIEW: ItemView = itemView(rawView());
const SOURCE = { id: "run run-esc", commit: "abcdef1234" };

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
});

/** Type into a field as a person would: React sees the native setter, then the input event. */
function type(field: HTMLTextAreaElement, value: string) {
  // The native setter is applied to the field explicitly; React only notices a value set this way.
  // eslint-disable-next-line @typescript-eslint/unbound-method
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
  act(() => {
    setter?.call(field, value);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function buttons(host: HTMLElement, label: string): HTMLButtonElement[] {
  return [...host.querySelectorAll<HTMLButtonElement>("button")].filter((b) =>
    b.textContent.includes(label),
  );
}

describe("the decision text is the queue's own", () => {
  it("is the verb, and the note after a colon; a rejection needs its note", () => {
    expect(decisionText("approve", "")).toBe("approve");
    expect(decisionText("approve", "  ")).toBe("approve");
    expect(decisionText("approve", "fine as it is")).toBe("approve: fine as it is");
    expect(decisionText("reject", "split it")).toBe("reject: split it");
    expect(decisionText("reject", " \n")).toBeNull();
  });

  it("the confirmation shows the line as the queue writes it, keys in its order", () => {
    expect(lineToWrite(VIEW, "reject", "split it", "yasin")).toBe(
      '{"item_id":"run-esc-s1","ts":"‹the time you confirm›","kind":"resolution",' +
        '"decision":"reject: split it","resolved_by":"yasin"}',
    );
    expect(lineToWrite(VIEW, "reject", "", "yasin")).toBeNull();
  });

  it("the request carries the item, the verb, the note and what was shown", () => {
    expect(JSON.parse(decisionRequest(VIEW, "approve", "ok"))).toEqual({
      item_id: "run-esc-s1",
      verb: "approve",
      note: "ok",
      shown: { item_sha256: DIGEST, trajectories: ["holds", "tampered"] },
    });
  });
});

describe("a blank note is blank exactly as the server judges it", () => {
  it("U+FEFF is a note, though JavaScript's trim would call it blank", () => {
    expect("\ufeff".trim()).toBe("");
    expect(isBlank("\ufeff")).toBe(false);
    expect(decisionText("approve", "\ufeff")).toBe("approve: \ufeff");
    expect(lineToWrite(VIEW, "approve", "\ufeff", "yasin")).toContain(
      '"decision":"approve: \ufeff"',
    );
  });

  it("U+001C to U+001F and U+0085 are blank, though JavaScript's trim keeps them", () => {
    for (const char of ["\u001c", "\u001d", "\u001e", "\u001f", "\u0085"]) {
      expect(char.trim()).toBe(char);
      expect(isBlank(char)).toBe(true);
      expect(decisionText("reject", char)).toBeNull();
      expect(decisionText("approve", ` ${char}\n`)).toBe("approve");
    }
  });

  it("the common blanks are blank and a word is not", () => {
    expect(isBlank("")).toBe(true);
    expect(isBlank(" \t\n\u00a0\u3000")).toBe(true);
    expect(isBlank(" x ")).toBe(false);
  });
});

describe("the records are held to their shapes", () => {
  it("an item view with a bad digest or an unknown status is refused whole", () => {
    expect(() => itemView(rawView({ item_sha256: "xyz" }))).toThrow(ShapeError);
    expect(() =>
      itemView(rawView({ trajectories: [{ link: "l", session_id: null, status: "clean" }] })),
    ).toThrow(ShapeError);
  });

  it("a cited quantity without its unit is refused, never shown bare", () => {
    const bare = rawView();
    (bare.item as { quantities: unknown[] }).quantities = [
      { node_id: "n", name: "x", value: 3.4, unit: "" },
    ];
    expect(() => itemView(bare)).toThrow();
  });

  it("a listing keeps the queue's own mark word for word", () => {
    const listing = queueListing({
      open: [],
      decided: [
        {
          item_id: "i",
          ts: "t",
          kind: "resolution",
          decision: "approve",
          resolved_by: "yasin",
          flag: "made while session sess-7 ran; confirm",
        },
      ],
    });
    expect(listing.decided[0]?.flag).toBe("made while session sess-7 ran; confirm");
  });

  it("the item chosen is the one named, else the first open one", () => {
    const decided = itemView(rawView({ position: 0, open: false }));
    const open = itemView(rawView({ position: 1 }));
    expect(chosenItem([decided, open], null)).toBe(open);
    expect(chosenItem([decided, open], "0")).toBe(decided);
  });
});

describe("the action token comes only from the operator's address, and lives in memory", () => {
  afterEach(() => {
    forgetToken();
  });

  it("is taken from the address's fragment once, and cleared from the address bar", () => {
    window.history.replaceState(null, "", "/?theme=dark#act=tok%2D123");
    expect(actToken()).toBeNull();
    takeTokenFromAddress();
    expect(actToken()).toBe("tok-123");
    expect(window.location.hash).toBe("");
    expect(window.location.search).toBe("?theme=dark");
    // Taken once: a later address without it changes nothing.
    window.history.replaceState(null, "", "/#/collaboration/approval-queue");
    takeTokenFromAddress();
    expect(actToken()).toBe("tok-123");
    expect(window.location.hash).toBe("#/collaboration/approval-queue");
  });

  it("a page opened at any other address holds no token", () => {
    window.history.replaceState(null, "", "/#/collaboration/approval-queue");
    takeTokenFromAddress();
    expect(actToken()).toBeNull();
    window.history.replaceState(null, "", "/#act=");
    takeTokenFromAddress();
    expect(actToken()).toBeNull();
  });

  it("the operator is read from the page too, and a page naming no one names no one", () => {
    expect(pageOperator()).toBeNull();
    const meta = document.createElement("meta");
    meta.name = "physgate-operator";
    meta.content = "Yasin H.";
    document.head.append(meta);
    expect(pageOperator()).toBe("Yasin H.");
  });

  it("a page without one sends nothing", async () => {
    const fetched = vi.spyOn(globalThis, "fetch");
    const answer = await postAction("/x", "{}", () => 1, null);
    expect(answer.ok).toBe(false);
    expect(fetched).not.toHaveBeenCalled();
    fetched.mockRestore();
  });

  it("an action carries the token, as JSON, and nothing the browser would add for another site", async () => {
    const fetched = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response('{"ok": 1}', { status: 201 }));
    await postAction("/x", '{"a":1}', () => 1, "tok");
    const init = fetched.mock.calls[0]?.[1];
    expect(init?.method).toBe("POST");
    expect(init?.credentials).toBe("omit");
    expect(init?.headers).toEqual({
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-Physgate-Act-Token": "tok",
    });
    fetched.mockRestore();
  });
});

describe("the item shows the five things, and every seal status apart", () => {
  it("shows the decision required, the quantity with its unit, the finding, the diff and the transcripts", () => {
    const host = mount(
      <QueueItem view={VIEW} decided={undefined} source={SOURCE} subtaskName="Subtask 1" />,
    );
    const text = host.textContent;
    expect(text).toContain("Subtask s1 was rejected on all 3 attempts. Decide.");
    expect(host.querySelector(".pg-quantity")?.textContent).toBe("3.4A");
    expect(text).toContain("the stall current is too high");
    expect(host.querySelector(".pg-queue-diff")?.textContent).toBe("--- a/x\n+++ b/x\n");
    const statuses = [...host.querySelectorAll("[data-status]")].map((b) =>
      b.getAttribute("data-status"),
    );
    expect(statuses).toEqual(["holds", "tampered"]);
    expect(host.querySelector("[data-source]")).not.toBeNull();
  });

  it("says why a person is asked in a sentence, with the queue's source under it", () => {
    const host = mount(
      <QueueItem view={VIEW} decided={undefined} source={SOURCE} subtaskName="Subtask 1" />,
    );
    expect(host.textContent).toContain(
      "The subtask was sent back on every attempt it was allowed, so no repair is left.",
    );
    expect(host.textContent).toContain("repair_budget_exhausted");
  });

  it("folds the seals into one line, which says when one does not hold", () => {
    expect(sealLine(VIEW)).toBe(
      "1 of 2 agent transcripts are not as they were sealed, or cannot be read.",
    );
    const all = itemView(
      rawView({
        trajectories: [
          { link: "/a", session_id: "a", status: "holds" },
          { link: "/b", session_id: "b", status: "holds" },
          { link: "/c", session_id: "c", status: "holds" },
        ],
      }),
    );
    expect(sealLine(all)).toBe("All 3 agent transcripts are intact (sealed).");
  });

  it("names no one as having raised the item: the record holds no such field", () => {
    const host = mount(
      <QueueItem view={VIEW} decided={undefined} source={SOURCE} subtaskName="Subtask 1" />,
    );
    expect(host.textContent).not.toContain("raised by");
    expect(host.querySelector(".pg-queue-over .pg-actor")).toBeNull();
    expect(host.textContent).not.toContain("Orchestrator");
  });

  it("every seal status has its own neutral tag, never a verdict", () => {
    expect(new Set(STATUSES.map((s) => SEAL_TAG[s])).size).toBe(STATUSES.length);
    const host = mount(
      <QueueItem view={VIEW} decided={undefined} source={SOURCE} subtaskName="Subtask 1" />,
    );
    expect(host.querySelector(".pg-seals .pg-verdict-pass, .pg-seals .pg-verdict-fail")).toBeNull();
    expect(host.querySelectorAll(".pg-seals .pg-status")).toHaveLength(2);
  });

  it("a decided item shows its decision and the queue's mark, and no way to decide again", () => {
    const host = mount(
      <QueueItem
        view={itemView(rawView({ open: false }))}
        decided={{
          itemId: "run-esc-s1",
          ts: "2026-10-11T10:00:00.000000Z",
          decision: "approve",
          resolvedBy: "yasin",
          flag: "made while session still running or not yet resumed ran; confirm",
        }}
        source={SOURCE}
        subtaskName="Subtask 1"
      >
        <p>the panel</p>
      </QueueItem>,
    );
    expect(host.textContent).toContain(
      "made while session still running or not yet resumed ran; confirm",
    );
    expect(host.textContent).not.toContain("the panel");
  });
});

describe("deciding goes through a confirmation naming the line it writes", () => {
  function panel(operator: string | null, send = vi.fn(), holdsToken = true) {
    const host = mount(
      <Decide
        view={VIEW}
        runId="run-esc"
        operator={operator}
        holdsToken={holdsToken}
        send={send}
        onDecided={vi.fn()}
      />,
    );
    return { host, send };
  }

  function open(host: HTMLElement, label: string): HTMLDialogElement {
    const [button] = buttons(host, label);
    act(() => {
      button?.click();
    });
    const dialogs = [...host.querySelectorAll("dialog")].filter((d) => d.open);
    expect(dialogs).toHaveLength(1);
    const dialog = dialogs[0];
    if (dialog === undefined) throw new Error("no dialog opened");
    return dialog;
  }

  function confirmIn(dialog: HTMLDialogElement, label: string): HTMLButtonElement | undefined {
    return [...dialog.querySelectorAll("button")].find((b) => b.textContent === label);
  }

  it("a rejection cannot be confirmed blank; an approval can, with or without a note", () => {
    const { host } = panel("yasin");
    expect(buttons(host, "Approve")[0]?.disabled).toBe(false);
    expect(buttons(host, "Reject")[0]?.disabled).toBe(false);
    const reject = open(host, "Reject");
    expect(confirmIn(reject, "Reject")?.disabled).toBe(true);
    const reason = reject.querySelector("textarea");
    if (reason === null) throw new Error("no reason field");
    type(reason, " \u3000 ");
    expect(confirmIn(reject, "Reject")?.disabled).toBe(true);
    type(reason, "split it");
    expect(confirmIn(reject, "Reject")?.disabled).toBe(false);
  });

  it("the confirmation says first what it records, then the exact line, echoing the note", () => {
    const { host } = panel("Yasin K.");
    const dialog = open(host, "Reject");
    const reason = dialog.querySelector("textarea");
    if (reason === null) throw new Error("no reason field");
    type(reason, "Margin must hold at 36 V");
    expect(dialog.querySelector(".pg-dialog-summary")?.textContent).toBe(
      "This records: Yasin K. rejected 'Subtask s1 was rejected on all 3 attempts. Decide.', with the note 'Margin must hold at 36 V'.",
    );
    expect(dialog.querySelector(".pg-writes-line")?.textContent).toBe(
      lineToWrite(VIEW, "reject", "Margin must hold at 36 V", "Yasin K."),
    );
    expect(dialog.textContent).toContain("Checked first, not written");
    expect(dialog.textContent).toContain(DIGEST);
    expect(dialog.textContent).toContain(
      "One line appended to queue_decisions.jsonl in run run-esc",
    );
  });

  it("the Then is option (a)'s sentence for both verbs, and says nothing the harness does not do", () => {
    for (const verb of ["Approve", "Reject"]) {
      const { host } = panel("yasin");
      const dialog = open(host, verb);
      expect(dialog.textContent).toContain(DECISION_COPY.then);
      expect(bannedIn(dialog.textContent)).toEqual([]);
      expect(bannedIn(host.textContent)).toEqual([]);
      act(() => {
        root?.unmount();
      });
      root = null;
      document.body.innerHTML = "";
    }
  });

  it("only confirming sends the decision, once, with its note", async () => {
    const send = vi.fn().mockResolvedValue({
      ok: true,
      value: {
        itemId: "run-esc-s1",
        ts: "t",
        decision: "reject: split it",
        resolvedBy: "yasin",
      } satisfies Resolved,
    });
    const { host } = panel("yasin", send);
    const dialog = open(host, "Reject");
    const reason = dialog.querySelector("textarea");
    if (reason === null) throw new Error("no reason field");
    type(reason, "split it");
    expect(send).not.toHaveBeenCalled();
    await act(async () => {
      confirmIn(dialog, "Reject")?.click();
      await Promise.resolve();
    });
    expect(send).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenCalledWith("reject", "split it");
  });

  it("a refusal is shown with the server's reason", async () => {
    const send = vi.fn().mockResolvedValue({
      ok: false,
      refusal: {
        status: 409,
        error: "a trajectory of the item is no longer as it was shown",
        context: {},
      },
    });
    const { host } = panel("yasin", send);
    const dialog = open(host, "Approve");
    await act(async () => {
      confirmIn(dialog, "Approve")?.click();
      await Promise.resolve();
    });
    expect(host.querySelector('[role="alert"]')?.textContent).toContain(
      "a trajectory of the item is no longer as it was shown",
    );
  });

  it("a page opened without the operator's address can only read, and says how to decide", () => {
    const { host } = panel("yasin", vi.fn(), false);
    expect(buttons(host, "Approve")[0]?.disabled).toBe(true);
    expect(buttons(host, "Reject")[0]?.disabled).toBe(true);
    expect(host.textContent).toContain("opened without the operator's address");
    expect(host.textContent).toContain("#act=");
  });

  it("without an operator nothing can be decided, and the page says why", () => {
    const { host } = panel(null);
    expect(buttons(host, "Approve")[0]?.disabled).toBe(true);
    expect(buttons(host, "Reject")[0]?.disabled).toBe(true);
    expect(whyNot(null)).toContain("without naming an operator");
  });
});

describe("the headline is plain words from the source and cause, the raw error one fold down", () => {
  const RAW =
    "The review of subtask s1, attempt 2, reached no verdict (invalid_verdict: the binary's cap on refused verdicts ended it: " +
    "Failed to provide valid structured output after 5 attempts \u2014 last StructuredOutput error: Output does not match required schema: /review: must be object). " +
    "Decide whether to review it again, review it yourself, or set the attempt aside. No repair attempt was spent.";
  const unavailable = itemView(
    rawView({
      item: {
        ...(rawView().item as Record<string, unknown>),
        source: "review_unavailable",
        decision_required: RAW,
      },
    }),
  );

  it("is derived by code from the source and the cause, with the attempt and the tries", () => {
    expect(queueHeadline(unavailable.item)).toBe(
      "The review of attempt 2 reached no verdict: the reviewer's answer did not fit the required form (5 tries)",
    );
  });

  it("falls back to the source's own sentence when no cause can be read", () => {
    expect(queueHeadline({ source: "review_unavailable", decisionRequired: "odd" })).toBe(
      "The review reached no verdict",
    );
    expect(queueHeadline(VIEW.item)).toBe("A subtask used up its repairs");
    expect(queueHeadline({ source: "escalation_decision", decisionRequired: "x" })).toBe(
      "A subtask was sent to a person",
    );
  });

  it("the heading is the plain headline and the raw string sits in a collapsed details section", () => {
    const host = mount(
      <QueueItem view={unavailable} decided={undefined} source={SOURCE} subtaskName="Subtask 1" />,
    );
    const heading = host.querySelector("h2")?.textContent ?? "";
    expect(heading).toContain("reached no verdict");
    expect(heading).not.toContain("StructuredOutput");
    expect(heading).not.toContain("must be object");
    const raw = [...host.querySelectorAll<HTMLDetailsElement>("details")].find((d) =>
      d.textContent.includes("must be object"),
    );
    expect(raw).toBeDefined();
    expect(raw?.open).toBe(false);
    expect(raw?.querySelector("summary")?.textContent).toBe("Details");
    expect(raw?.textContent).toContain(RAW);
  });

  it("keeps the item's finding, diff and quantities as they are", () => {
    const host = mount(
      <QueueItem view={unavailable} decided={undefined} source={SOURCE} subtaskName="Subtask 1" />,
    );
    expect(host.textContent).toContain("the stall current is too high");
    expect(host.querySelector(".pg-queue-diff")?.textContent).toBe("--- a/x\n+++ b/x\n");
    expect(host.querySelector(".pg-quantity")?.textContent).toBe("3.4A");
  });
});
