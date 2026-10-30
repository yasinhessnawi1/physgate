// @vitest-environment happy-dom
/**
 * A choice between the two positions of an arbitration item: offered on that item alone, written
 * as the queue writes it (the verb, the position, the note), sent with its position, and said to
 * do exactly what the item says, which in this build is to be recorded.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ShapeError } from "../../api/client";
import { decisionRequest, decisionText, type ItemView, itemView } from "../../api/queue";
import { bannedIn, decisionSummary } from "../../words/queue";
import { Decide } from "./Decide";
// The queue's own bytes for one choice with a note, as the Python writer writes them.
import PYTHON_CHOICE_LINE from "./choice-with-note.line?raw";
import { lineToWrite } from "./model";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const DIGEST = "a".repeat(64);
const BOTH = { sizing: "record_only", domain: "record_only" };

function raw(source: string, onChoose: unknown): Record<string, unknown> {
  return {
    position: 0,
    item_sha256: DIGEST,
    open: true,
    item: {
      kind: "item",
      item_id: "run-1-s1",
      ts: "2026-10-30T09:00:00.000000Z",
      run_id: "run-1",
      subtask_id: "s1",
      source,
      decision_required: "Subtask s1 disputes a value of a cross node. Decide which value stands.",
      artefact_diff: "",
      triggering_finding:
        'Node "sizing.bus" holds 24 "volt". The disputing subtask holds it at 5 V.',
      quantities: [{ node_id: "sizing.bus", name: "supply_voltage", value: 24, unit: "V" }],
      trajectories: ["/r/sessions/s-1/stdout.jsonl"],
      consequence: {
        attempt: 2,
        attempt_commit: "c".repeat(40),
        on_approve: "record_only",
        on_reject: "record_only",
        why_record_only: "source",
        confirmed_indicators: [],
        scan_hits: [],
        ...(onChoose === undefined ? {} : { on_choose: onChoose }),
      },
    },
    trajectories: [{ link: "/r/sessions/s-1/stdout.jsonl", session_id: "s-1", status: "holds" }],
  };
}

const ARBITRATION: ItemView = itemView(raw("arbitration", BOTH));

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

function buttons(host: HTMLElement, label: string): HTMLButtonElement[] {
  return [...host.querySelectorAll<HTMLButtonElement>("button")].filter((b) =>
    b.textContent.includes(label),
  );
}

function panel(view: ItemView, send = vi.fn()) {
  const host = mount(
    <Decide
      view={view}
      runId="run-1"
      operator="yasin"
      holdsToken
      send={send}
      onDecided={vi.fn()}
    />,
  );
  return { host, send };
}

describe("a choice's text, line and request are the queue's own", () => {
  it("is the verb and the position, with the note after a colon; no position, no choice", () => {
    expect(decisionText("choose", "", "sizing")).toBe("choose sizing");
    expect(decisionText("choose", " \n", "domain")).toBe("choose domain");
    expect(decisionText("choose", "keep 24 V", "sizing")).toBe("choose sizing: keep 24 V");
    expect(decisionText("choose", "keep 24 V")).toBeNull();
  });

  it("the line names the position after the verb, as the queue writes it", () => {
    expect(lineToWrite(ARBITRATION, "choose", "", "yasin", "domain")).toBe(
      '{"item_id":"run-1-s1","ts":"‹the time you confirm›","kind":"resolution",' +
        '"decision":"choose domain","resolved_by":"yasin","verb":"choose","position":"domain",' +
        `"shown_sha256":"${DIGEST}"}`,
    );
  });

  it("a choice with a note is the line the Python writer writes, read from the shared fixture", () => {
    // The fixture is the queue's own bytes for this choice, its time put as the dialog puts it;
    // a Python row holds the writer to the same file, so the two languages are compared.
    const python = PYTHON_CHOICE_LINE.trimEnd();
    expect(lineToWrite(ARBITRATION, "choose", "keep 24 V", "yasin", "sizing")).toBe(python);
  });

  it("names no position on approve or reject, and no choice without one", () => {
    expect(decisionText("approve", "", "sizing")).toBeNull();
    expect(decisionText("reject", "a reason", "domain")).toBeNull();
    expect(() => decisionSummary("yasin", "choose", "Decide.", "")).toThrow(/position/);
    expect(() => decisionSummary("yasin", "approve", "Decide.", "", "sizing")).toThrow(/position/);
  });

  it("the request carries the position with choose, and no position with another verb", () => {
    expect(JSON.parse(decisionRequest(ARBITRATION, "choose", "x", "sizing"))).toEqual({
      item_id: "run-1-s1",
      verb: "choose",
      position: "sizing",
      note: "x",
      shown: { item_sha256: DIGEST, trajectories: ["holds"] },
    });
    expect(JSON.parse(decisionRequest(ARBITRATION, "approve", ""))).not.toHaveProperty("position");
  });
});

describe("what each position does is read from the item", () => {
  it("is both positions, in the set's order", () => {
    expect(ARBITRATION.item.consequence?.onChoose).toEqual(BOTH);
    expect(itemView(raw("review_unavailable", undefined)).item.consequence?.onChoose).toBeNull();
  });

  it("a set on an item of another kind, or an arbitration consequence without one, is refused", () => {
    expect(() => itemView(raw("review_unavailable", BOTH))).toThrow(ShapeError);
    expect(() => itemView(raw("arbitration", undefined))).toThrow(ShapeError);
  });

  it("a position set of another shape is refused whole", () => {
    for (const forged of [
      { domain: "record_only", sizing: "record_only" },
      { sizing: "record_only" },
      { sizing: "record_only", domain: "merge" },
      { ...BOTH, producer: "record_only" },
    ]) {
      expect(() => itemView(raw("arbitration", forged)), JSON.stringify(forged)).toThrow(
        ShapeError,
      );
    }
  });
});

describe("the choice is offered on an arbitration item alone", () => {
  it("shows one button per position on an arbitration item, and none on another", () => {
    const { host } = panel(ARBITRATION);
    expect(buttons(host, "Choose sizing's value")).toHaveLength(1);
    expect(buttons(host, "Choose the domain's value")).toHaveLength(1);
    act(() => {
      root?.unmount();
    });
    root = null;
    const other = panel(itemView(raw("review_unavailable", undefined)));
    expect(buttons(other.host, "Choose")).toHaveLength(0);
  });

  it("offers both positions on an arbitration item with no consequence, as a run that records writes it", () => {
    const recorded = raw("arbitration", undefined);
    (recorded.item as Record<string, unknown>).consequence = undefined;
    const { host } = panel(itemView(recorded));
    expect(buttons(host, "Choose sizing's value")).toHaveLength(1);
    expect(buttons(host, "Choose the domain's value")).toHaveLength(1);
  });

  it.each([
    ["sizing", "Choose sizing's value", "chose sizing's value on"],
    ["domain", "Choose the domain's value", "chose the domain's value on"],
  ] as const)("the dialog's opening sentence names the %s position", (_, label, says) => {
    const { host } = panel(ARBITRATION);
    const [button] = buttons(host, label);
    act(() => {
      button?.click();
    });
    const dialog = [...host.querySelectorAll("dialog")].find((d) => d.open);
    expect(dialog?.textContent).toContain(`This records: yasin ${says}`);
  });

  it.each([
    [
      "retry",
      "Choose: this attempt is spent, and the next one is told sizing's value as the graph holds " +
        "it, and your note if you write one. Its reviewer is told what it was told.",
    ],
    [
      "fix",
      "Choose: one fix is made by a fresh session in the subtask's working copy, told sizing's " +
        "value as the graph holds it and your note if you write one. It is the subtask's last " +
        "attempt; if it is not accepted, the subtask ends rejected.",
    ],
    ["end_subtask", "Choose: the subtask ends rejected, and nothing of it is merged."],
  ] as const)(
    "an item whose choice of sizing does %s is read, and the dialog says so",
    (does, says) => {
      const stated = raw("arbitration", { sizing: does, domain: "record_only" });
      const view = ((): ItemView | null => {
        try {
          return itemView(stated);
        } catch {
          return null;
        }
      })();
      expect(view, "the item is read").not.toBeNull();
      if (view === null) return;
      const { host } = panel(view);
      const [button] = buttons(host, "Choose sizing's value");
      act(() => {
        button?.click();
      });
      const dialog = [...host.querySelectorAll("dialog")].find((d) => d.open);
      expect(dialog?.textContent).toContain(says);
      expect(bannedIn(dialog?.textContent ?? "")).toEqual([]);
    },
  );

  it("an item whose choice of the domain resizes is read, and the dialog says so", () => {
    const view = ((): ItemView | null => {
      try {
        return itemView(raw("arbitration", { sizing: "retry", domain: "resize" }));
      } catch {
        return null;
      }
    })();
    expect(view, "the item is read").not.toBeNull();
    if (view === null) return;
    const { host } = panel(view);
    const [button] = buttons(host, "Choose the domain's value");
    act(() => {
      button?.click();
    });
    const dialog = [...host.querySelectorAll("dialog")].find((d) => d.open);
    expect(dialog?.textContent).toContain(
      "Choose: the subtask waits while sizing's closing pass is ordered to write the domain's " +
        "value into the graph; once that pass is merged, this attempt is judged again, with no " +
        "new session.",
    );
    expect(bannedIn(dialog?.textContent ?? "")).toEqual([]);
  });

  it("confirming sends the choice once, with its position, and says it is recorded", async () => {
    const send = vi.fn().mockResolvedValue({
      ok: true,
      value: { itemId: "run-1-s1", ts: "t", decision: "choose domain", resolvedBy: "yasin" },
    });
    const { host } = panel(ARBITRATION, send);
    const [button] = buttons(host, "Choose the domain's value");
    act(() => {
      button?.click();
    });
    const dialog = [...host.querySelectorAll("dialog")].find((d) => d.open);
    expect(dialog, "a confirmation opened").toBeDefined();
    if (dialog === undefined) return;
    expect(dialog.querySelector(".pg-writes-line")?.textContent).toBe(
      lineToWrite(ARBITRATION, "choose", "", "yasin", "domain"),
    );
    expect(dialog.textContent).toContain("recorded, and nothing in the run acts on it");
    expect(bannedIn(dialog.textContent)).toEqual([]);
    const confirm = [...dialog.querySelectorAll("button")].find((b) => b.textContent === "Choose");
    expect(confirm?.disabled).toBe(false);
    await act(async () => {
      confirm?.click();
      await Promise.resolve();
    });
    expect(send).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenCalledWith("choose", "", "domain");
  });
});

describe("a failed contract's item is read with its own positions", () => {
  const PAIR = { producer: "record_only", consumer: "record_only" };

  it("reads the producer and the consumer, in the set's order, and a reopen", () => {
    expect(() => itemView(raw("contract", PAIR))).not.toThrow();
    expect(itemView(raw("contract", PAIR)).item.consequence?.onChoose).toEqual(PAIR);
    const reopens = { producer: "reopen", consumer: "record_only" };
    expect(itemView(raw("contract", reopens)).item.consequence?.onChoose).toEqual(reopens);
  });

  it("refuses the other kind's set on either kind, and a contract consequence without one", () => {
    expect(() => itemView(raw("contract", BOTH))).toThrow(ShapeError);
    expect(() => itemView(raw("arbitration", PAIR))).toThrow(ShapeError);
    expect(() => itemView(raw("contract", undefined))).toThrow(ShapeError);
    expect(() =>
      itemView(raw("contract", { consumer: "record_only", producer: "record_only" })),
    ).toThrow(ShapeError);
  });

  it("offers no arbitration choice on a contract item", () => {
    expect(() => itemView(raw("contract", PAIR))).not.toThrow();
    const { host } = panel(itemView(raw("contract", PAIR)));
    expect(buttons(host, "Choose sizing's value")).toHaveLength(0);
    expect(buttons(host, "Choose the domain's value")).toHaveLength(0);
  });
});
