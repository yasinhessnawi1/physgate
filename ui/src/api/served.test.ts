/**
 * The answers a run that acts on decisions served, read as the server's routes send them.
 *
 * The files in ``served/`` are one such run's answers with every path, name and session id made
 * neutral and the long texts cut: its ledger, its queue listing, its first item's view and where it
 * stands, each as the route wrote it. The failed contract's listing and view are built by the
 * server's own item model and passed through its own JSON response, because the run's contract
 * item was decided before its view could be kept. The route writes every object's keys sorted, so
 * an item's positions reach the page in the alphabet's order, not the order its kind states them.
 * ``config.json`` is the config route's answer for a run with a held-out tier, written by the route's
 * own code: the record less the tier's fields, which no answer carries.
 */
import { describe, expect, it } from "vitest";

import { ShapeError } from "./client";
import { itemView, queueListing } from "./queue";
import { ledgerLine, runConfig } from "./records";
import { runStatus } from "./run";
import config from "./served/config.json";
import contractItem from "./served/item-contract.json";
import reviewItem from "./served/item-review-unavailable.json";
import ledger from "./served/ledger.json";
import contractOpen from "./served/queue-contract-open.json";
import decidedListing from "./served/queue-decided.json";
import status from "./served/status.json";

/** A deep copy of a served answer, to change one field of it. */
const copy = <T>(value: T): T => structuredClone(value);

/** The contract item's consequence, as served, with ``on_choose`` replaced. */
function withChoices(onChoose: unknown, source = "contract"): unknown {
  const view = copy(contractItem) as unknown as {
    item: { source: string; consequence: Record<string, unknown> };
  };
  view.item.source = source;
  view.item.consequence.on_choose = onChoose;
  return view;
}

describe("a run's configuration is read without the held-out tier the route leaves out", () => {
  it("the answer names no held-out field, and the page reads everything it draws from it", () => {
    expect(Object.keys(config.config).filter((k) => k.startsWith("held_out"))).toEqual([]);
    const read = runConfig(config);
    expect(read.manifestId).toBe(config.manifest_id);
    expect(read.runId).toBe("run-7");
    expect(read.gateMode).toBe("observe");
    expect(read.roleModels).toEqual({ electrical: "claude-sonnet-5" });
    expect(read.repairBudget).toBe(3);
  });
});

describe("a review the ledger records as blocked is read, and only a review", () => {
  const blocked = ledger.filter((l) => l.review_result === "blocked");

  it("the run's ledger holds blocked reviews, the decided one among them", () => {
    expect(blocked.length).toBe(3);
    expect(blocked.some((l) => "person_decision" in l && "queue_item" in l)).toBe(true);
  });

  it("each blocked line is read with its review blocked, not refused", () => {
    const read: unknown[] = [];
    for (const l of blocked) {
      try {
        read.push(ledgerLine(l).review);
      } catch (e) {
        read.push(e instanceof ShapeError ? e.message : e);
      }
    }
    expect(read).toEqual(["blocked", "blocked", "blocked"]);
  });

  it("every line of the run's ledger is read, in order, its gate and review as written", () => {
    let read: unknown;
    expect(() => {
      read = ledger.map(ledgerLine).map((l) => [l.id, l.gate, l.review]);
    }).not.toThrow();
    expect(read).toEqual(ledger.map((l) => [l.id, l.gate_result, l.review_result]));
  });

  it("a gate is never blocked: a gate result of blocked is refused", () => {
    const first = ledger.find((l) => l.review_result === "blocked");
    expect(() => ledgerLine({ ...first, gate_result: "blocked" })).toThrow(ShapeError);
  });

  it("a review result outside the record's set is refused", () => {
    const first = ledger[0];
    for (const result of ["warn", "unchecked", "Blocked", "", 0, true])
      expect(() => ledgerLine({ ...first, review_result: result })).toThrow(ShapeError);
  });
});

describe("a failed contract's item is read as the route sends it, keys sorted", () => {
  it("the open item is read, its positions in its kind's order with what each does", () => {
    let choices: unknown;
    expect(() => {
      const listing = queueListing(contractOpen);
      choices = Object.entries(listing.open[0]?.consequence?.onChoose ?? {});
    }).not.toThrow();
    expect(choices).toEqual([
      ["producer", "reopen"],
      ["consumer", "record_only"],
    ]);
  });

  it("its view is read, the item, the seals and the view's id whole", () => {
    let read: unknown;
    expect(() => {
      const view = itemView(contractItem);
      read = [view.item.source, view.item.subtaskId, view.open, view.trajectories.length];
    }).not.toThrow();
    expect(read).toEqual(["contract", "contract", true, 2]);
  });

  it("an arbitration item whose positions came sorted is read in its own order too", () => {
    let choices: unknown;
    expect(() => {
      const view = itemView(withChoices({ domain: "resize", sizing: "retry" }, "arbitration"));
      choices = Object.entries(view.item.consequence?.onChoose ?? {});
    }).not.toThrow();
    expect(choices).toEqual([
      ["sizing", "retry"],
      ["domain", "resize"],
    ]);
  });
});

describe("what the item's positions must hold is still held", () => {
  it("a position missing, one added, or one of another kind is refused as the item's positions", () => {
    for (const stated of [
      { producer: "reopen" },
      { consumer: "record_only" },
      { consumer: "record_only", producer: "reopen", sizing: "retry" },
      { consumer: "record_only", domain: "resize" },
      { sizing: "retry", domain: "resize" },
      {},
    ]) {
      expect(() => itemView(withChoices(stated))).toThrow(ShapeError);
      // Refused as a set of another shape, not later as one position's effect.
      expect(() => itemView(withChoices(stated)), JSON.stringify(stated)).toThrow(
        "the server's answer is not an item's positions",
      );
    }
  });

  it("what choosing does must be one the record knows", () => {
    expect(() => itemView(withChoices({ consumer: "merge", producer: "reopen" }))).toThrow(
      ShapeError,
    );
    expect(() => itemView(withChoices({ consumer: null, producer: "reopen" }))).toThrow(ShapeError);
  });

  it("a contract item that says what its verbs do must say what choosing does", () => {
    expect(() => itemView(withChoices(undefined))).toThrow(ShapeError);
    expect(() => itemView(withChoices(null))).toThrow(ShapeError);
  });

  it("an item of a kind that offers no positions states none", () => {
    expect(() =>
      itemView(withChoices({ consumer: "record_only", producer: "reopen" }, "review_unavailable")),
    ).toThrow(ShapeError);
  });

  it("positions stated as a list, not a mapping, are refused", () => {
    expect(() => itemView(withChoices(["producer", "consumer"]))).toThrow(ShapeError);
  });

  it("a cited quantity without its unit is refused, never shown bare", () => {
    const view = copy(contractItem) as unknown as { item: { quantities: unknown[] } };
    view.item.quantities = [{ node_id: "firmware.loop", name: "rate", value: 1000 }];
    expect(() => itemView(view)).toThrow(/unit/);
  });
});

describe("the run's other answers are read as they are", () => {
  it("the first item's view, a review that reached no verdict, decided", () => {
    const view = itemView(reviewItem);
    expect(view.open).toBe(false);
    expect(view.item.consequence?.scanHits).toBe(2);
    expect(view.item.consequence?.onChoose).toBeNull();
  });

  it("the listing with every item decided, the choice among them with no time on record", () => {
    const listing = queueListing(decidedListing);
    expect(listing.open).toEqual([]);
    expect(listing.decided.map((d) => [d.decision.split(":")[0], d.taken?.effect ?? null])).toEqual(
      [
        ["approve", "merge"],
        ["reject", "retry"],
        ["choose producer", null],
      ],
    );
  });

  it("where it stands, with each module's completion and its open preconditions", () => {
    const s = runStatus(status);
    expect(s.kind).toBe("attempt");
    expect(s.completion.modules.map((m) => [m.subtask, m.open.length])).toEqual([
      ["sizing-3ac1b9", 3],
      ["control-c2599c", 3],
      ["firmware-a7cd7e", 3],
    ]);
  });
});
