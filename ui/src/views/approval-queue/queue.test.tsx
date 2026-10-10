// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { actToken, postAction, ShapeError } from "../../api/client";
import {
  decisionRequest,
  decisionText,
  type ItemView,
  itemView,
  queueListing,
  type Resolved,
  STATUSES,
} from "../../api/queue";
import { DecisionPanel } from "./DecisionPanel";
import { ItemDetail } from "./ItemDetail";
import { chosenItem, lineToWrite, STATUS_SHOWN, whyNot } from "./model";

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

describe("the action token comes only from this page", () => {
  it("is read from the page's meta element", () => {
    const meta = document.createElement("meta");
    meta.name = "physgate-act-token";
    meta.content = "tok-123";
    document.head.append(meta);
    expect(actToken()).toBe("tok-123");
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

describe("the item view shows the five things, and every seal status apart", () => {
  it("shows the decision required, the quantity with its unit, the finding, the diff and the trajectories", () => {
    const host = mount(
      <ItemDetail view={VIEW} decided={undefined} source={SOURCE} runKey="0/run-esc" />,
    );
    const text = host.textContent;
    expect(text).toContain("Subtask s1 was rejected on all 3 attempts. Decide.");
    expect(host.querySelector(".quantity")?.textContent).toBe("3.4A");
    expect(text).toContain("the stall current is too high");
    expect(host.querySelector(".queue-diff")?.textContent).toBe("--- a/x\n+++ b/x\n");
    const statuses = [...host.querySelectorAll("[data-status]")].map((b) =>
      b.getAttribute("data-status"),
    );
    expect(statuses).toEqual(["holds", "tampered"]);
    expect(host.querySelector("[data-source]")).not.toBeNull();
  });

  it("every status has its own words and glyph, and only holds is drawn as a pass", () => {
    const words = STATUSES.map((s) => STATUS_SHOWN[s][2]);
    expect(new Set(words).size).toBe(STATUSES.length);
    expect(STATUSES.filter((s) => STATUS_SHOWN[s][0] === "pass")).toEqual(["holds"]);
  });

  it("a decided item shows its decision and the queue's mark, and no way to decide again", () => {
    const host = mount(
      <ItemDetail
        view={itemView(rawView({ open: false }))}
        decided={{
          itemId: "run-esc-s1",
          ts: "2026-10-11T10:00:00.000000Z",
          decision: "approve",
          resolvedBy: "yasin",
          flag: "made while session still running or not yet resumed ran; confirm",
        }}
        source={SOURCE}
        runKey="0/run-esc"
      >
        <p>the panel</p>
      </ItemDetail>,
    );
    expect(host.textContent).toContain(
      "made while session still running or not yet resumed ran; confirm",
    );
    expect(host.textContent).not.toContain("the panel");
  });
});

describe("deciding goes through a confirmation naming the line it writes", () => {
  function panel(operator: string | null, send = vi.fn()) {
    const host = mount(
      <DecisionPanel
        view={VIEW}
        runId="run-esc"
        operator={operator}
        send={send}
        onDecided={vi.fn()}
      />,
    );
    const note = host.querySelector("textarea");
    if (note === null) throw new Error("no note field");
    return { host, note, send };
  }

  it("reject cannot open until the note says why; approve can", () => {
    const { host, note } = panel("yasin");
    const [approve] = buttons(host, "Approve");
    const [reject] = buttons(host, "Reject");
    expect(approve?.disabled).toBe(false);
    expect(reject?.disabled).toBe(true);
    expect(host.textContent).toContain("A rejection says why");
    type(note, "split it");
    expect(buttons(host, "Reject")[0]?.disabled).toBe(false);
  });

  it("the confirmation shows the exact line, and only confirming sends it, once", async () => {
    const send = vi.fn().mockResolvedValue({
      ok: true,
      value: {
        itemId: "run-esc-s1",
        ts: "t",
        decision: "reject: split it",
        resolvedBy: "yasin",
      } satisfies Resolved,
    });
    const { host, note } = panel("yasin", send);
    type(note, "split it");
    const [reject] = buttons(host, "Reject");
    act(() => {
      reject?.click();
    });
    const dialogs = [...host.querySelectorAll("dialog")].filter((d) => d.open);
    expect(dialogs).toHaveLength(1);
    const dialog = dialogs[0];
    expect(dialog?.textContent).toContain(
      "This writes: one line appended to queue_decisions.jsonl in run run-esc",
    );
    expect(dialog?.querySelector(".confirm-line")?.textContent).toBe(
      lineToWrite(VIEW, "reject", "split it", "yasin"),
    );
    expect(dialog?.textContent).toContain("This cannot be edited or undone; the item closes.");
    expect(send).not.toHaveBeenCalled();
    const confirm = [...(dialog?.querySelectorAll("button") ?? [])].find(
      (b) => b.textContent === "Reject",
    );
    await act(async () => {
      confirm?.click();
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
    const [approve] = buttons(host, "Approve");
    act(() => {
      approve?.click();
    });
    const confirm = [...host.querySelectorAll("dialog button")].find(
      (b) => b.textContent === "Approve",
    ) as HTMLButtonElement | undefined;
    await act(async () => {
      confirm?.click();
      await Promise.resolve();
    });
    expect(host.querySelector('[role="alert"]')?.textContent).toContain(
      "a trajectory of the item is no longer as it was shown",
    );
  });

  it("without an operator nothing can be decided, and the page says why", () => {
    const { host } = panel(null);
    expect(buttons(host, "Approve")[0]?.disabled).toBe(true);
    expect(buttons(host, "Reject")[0]?.disabled).toBe(true);
    expect(whyNot("approve", "", null)).toContain("without naming an operator");
  });
});
