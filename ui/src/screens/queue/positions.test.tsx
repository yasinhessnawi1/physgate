// @vitest-environment happy-dom
/**
 * A disputed sizing value and a failed contract, as a person decides them: what the item is,
 * what choosing each of its positions does, what the server checks before it writes, which
 * verbs a broken seal disables, and what a decision on an item a reopen superseded does.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { type ItemView, itemView } from "../../api/queue";
import { type PaletteEntry, PaletteProvider } from "../../shell/palette";
import { bannedIn, CHOOSE_WORDS, queueHeadline, SOURCE_WORDS } from "../../words/queue";
import { Decide } from "./Decide";
import { QueueItem } from "./QueueItem";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const DIGEST = "a".repeat(64);
const SOURCE = { id: "run run-1", commit: "abcdef1234" };
const RESIZE =
  "Choose: the subtask waits while sizing's closing pass is ordered to write the domain's value " +
  "into the graph; once that pass is merged, this attempt is judged again from its finished " +
  "session, with no new session. If the pass writes another value, the dispute is ruled again.";
const REOPEN =
  "Choose: the other module is reopened for one more attempt, its next or its one fix, told the " +
  "interface's values it does not hold. Its earlier merge stays on the record, and the contract " +
  "is tested again once it is merged.";
const SEALED = (n: number) =>
  `that the item is still the one shown (its digest ${DIGEST}) and that each of its ` +
  `${String(n)} transcripts still holds its seal`;
const AS_SHOWN = (n: number) =>
  `that the item is still the one shown (its digest ${DIGEST}) and that each of its ` +
  `${String(n)} transcripts reads as it did when shown`;
const DOMAIN_UNSEALED =
  "A transcript of this item does not hold its seal, and choosing the domain's value carries the " +
  "agent's typed value into the graph, so it binds only to sealed work.";
const APPROVE_UNSEALED =
  "A transcript of this item does not hold its seal, and an approve binds only to sealed work.";

type Seal = "holds" | "tampered" | "missing";

function raw(
  source: "arbitration" | "contract",
  onChoose: Record<string, string>,
  { seals = ["holds"], indicators = [] }: { seals?: Seal[]; indicators?: unknown[] } = {},
): Record<string, unknown> {
  return {
    position: 0,
    item_sha256: DIGEST,
    open: true,
    item: {
      kind: "item",
      item_id: "run-1-c1",
      ts: "2026-10-31T09:00:00.000000Z",
      run_id: "run-1",
      subtask_id: "s1",
      source,
      decision_required: "Decide whose merged work stands.",
      artefact_diff: "",
      triggering_finding: "The interface's clause failed.",
      quantities: [],
      trajectories: seals.map((_, i) => `/r/sessions/s-${String(i)}/stdout.jsonl`),
      consequence: {
        attempt: 2,
        attempt_commit: null,
        on_approve: "record_only",
        on_reject: "record_only",
        why_record_only: "source",
        confirmed_indicators: indicators,
        scan_hits: [],
        on_choose: onChoose,
      },
    },
    trajectories: seals.map((status, i) => ({
      link: `/r/sessions/s-${String(i)}/stdout.jsonl`,
      session_id: `s-${String(i)}`,
      status,
    })),
  };
}

const DISPUTED = { sizing: "retry", domain: "resize" };
const PAIR = { producer: "reopen", consumer: "record_only" };

let root: Root | null = null;
function mount(node: React.ReactNode): HTMLElement {
  // One item at a time: a test that mounts a second unmounts the first.
  act(() => {
    root?.unmount();
  });
  document.body.innerHTML = "";
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

function panel(view: ItemView, supersededBy?: string): HTMLElement {
  return mount(
    <QueueItem
      view={view}
      decided={undefined}
      source={SOURCE}
      subtaskName="Subtask 1"
      supersededBy={supersededBy}
    >
      <Decide
        view={view}
        runId="run-1"
        operator="yasin"
        holdsToken
        send={vi.fn()}
        onDecided={vi.fn()}
        supersededBy={supersededBy}
      />
    </QueueItem>,
  );
}

function button(host: HTMLElement, label: string): HTMLButtonElement | undefined {
  return [...host.querySelectorAll<HTMLButtonElement>(".pg-queue-actions button")].find((b) =>
    b.textContent.startsWith(label),
  );
}

/** The confirmation ``label`` opens, as text. */
function dialogOf(host: HTMLElement, label: string): string {
  act(() => {
    button(host, label)?.click();
  });
  return [...host.querySelectorAll("dialog")].find((d) => d.open)?.textContent ?? "";
}

/** The reason beside a disabled button, or ``null`` while it is enabled. */
function disabledBecause(host: HTMLElement, label: string): string | null {
  const b = button(host, label);
  if (b === undefined || !b.disabled) return null;
  const id = b.getAttribute("aria-describedby");
  return id === null ? "" : (host.querySelector(`[id="${id}"]`)?.textContent ?? "");
}

describe("a disputed sizing value says what it is", () => {
  it("names the dispute, why a person is asked and its headline", () => {
    expect(SOURCE_WORDS.arbitration.kind).toBe("Disputed sizing value");
    expect(SOURCE_WORDS.arbitration.why).toBe(
      "A domain's agent disputes a value that sizing owns. The gate did not settle it, and by " +
        "the precedence rule it comes to a person: the same quantity was disputed in an earlier " +
        "attempt, or this was the subtask's last attempt.",
    );
    expect(queueHeadline({ source: "arbitration", decisionRequired: "x" })).toBe(
      "A domain disputes a value sizing owns",
    );
  });

  it("leaves the contract's words as they were", () => {
    expect(SOURCE_WORDS.contract).toEqual({
      kind: "Interface contract failed",
      why: "Two merged modules do not both hold an interface fixed at decomposition.",
    });
    expect(queueHeadline({ source: "contract", decisionRequired: "x" })).toBe(
      "Two merged modules break an interface contract",
    );
  });

  it("says what resizing and reopening do, whole", () => {
    expect(CHOOSE_WORDS.resize).toBe(RESIZE);
    expect(CHOOSE_WORDS.reopen).toBe(REOPEN);
    expect(bannedIn(`${RESIZE} ${REOPEN}`)).toEqual([]);
  });
});

describe("the server's check before it writes is said per verb", () => {
  it.each([
    ["Approve", "arbitration", SEALED],
    ["Choose the domain's value", "arbitration", SEALED],
    ["Reject", "arbitration", AS_SHOWN],
    ["Choose sizing's value", "arbitration", AS_SHOWN],
    ["Choose the producer's work", "contract", AS_SHOWN],
    ["Choose the consumer's work", "contract", AS_SHOWN],
  ] as const)("%s", (label, source, said) => {
    const view = itemView(
      raw(source, source === "arbitration" ? DISPUTED : PAIR, { seals: ["holds", "holds"] }),
    );
    const text = dialogOf(panel(view), label);
    expect(text).toContain(said(2));
    expect(text).not.toContain(said === SEALED ? AS_SHOWN(2) : SEALED(2));
  });

  it("closes with the line it appends and when it is stamped", () => {
    const text = dialogOf(panel(itemView(raw("arbitration", DISPUTED))), "Reject");
    expect(text).toContain(
      "One line appended to queue_decisions.jsonl in run run-1. This cannot be edited or " +
        "undone; the item closes. The time is stamped when it is written, beside the time this " +
        "server showed you the item if it still holds it, so the record says how long the " +
        "decision took.",
    );
  });
});

describe("a broken seal disables what binds only to sealed work", () => {
  it.each([
    ["one transcript tampered", ["holds", "tampered"] as Seal[]],
    ["one missing", ["missing"] as Seal[]],
    ["no transcript", [] as Seal[]],
  ])("%s: approve and the domain's value, with why; reject and sizing's value stay", (_, seals) => {
    const host = panel(itemView(raw("arbitration", DISPUTED, { seals })));
    expect(disabledBecause(host, "Choose the domain's value")).toBe(DOMAIN_UNSEALED);
    expect(disabledBecause(host, "Approve")).toBe(APPROVE_UNSEALED);
    expect(disabledBecause(host, "Reject")).toBeNull();
    expect(disabledBecause(host, "Choose sizing's value")).toBeNull();
  });

  it("every seal holding disables neither", () => {
    const host = panel(itemView(raw("arbitration", DISPUTED, { seals: ["holds", "holds"] })));
    expect(disabledBecause(host, "Choose the domain's value")).toBeNull();
    expect(disabledBecause(host, "Approve")).toBeNull();
  });

  it("the command palette's approve says the same", () => {
    let listed: readonly PaletteEntry[] = [];
    const registry = {
      entries: [],
      register: (_: string, entries: readonly PaletteEntry[]) => {
        listed = entries;
      },
      unregister: () => undefined,
    };
    const view = itemView(raw("arbitration", DISPUTED, { seals: ["tampered"] }));
    mount(
      <PaletteProvider registry={registry}>
        <Decide
          view={view}
          runId="run-1"
          operator="yasin"
          holdsToken
          send={vi.fn()}
          onDecided={vi.fn()}
        />
      </PaletteProvider>,
    );
    const approve = listed.find((e) => e.id === "queue-approve");
    expect(approve?.disabledBecause).toBe(APPROVE_UNSEALED);
    expect(listed.find((e) => e.id === "queue-reject")?.disabledBecause).toBeNull();
  });
});

describe("a failed contract offers its own two positions", () => {
  it("as buttons, and no arbitration position", () => {
    const host = panel(itemView(raw("contract", PAIR)));
    expect(button(host, "Choose the producer's work…")).toBeDefined();
    expect(button(host, "Choose the consumer's work…")).toBeDefined();
    expect(button(host, "Choose sizing's value")).toBeUndefined();
    expect(button(host, "Choose the domain's value")).toBeUndefined();
  });

  it("with its title, summary and what it does", () => {
    const view = itemView(raw("contract", PAIR));
    const producer = dialogOf(panel(view), "Choose the producer's work");
    expect(producer).toContain("Choose the producer's work?");
    expect(producer).toContain(
      "This records: yasin chose the producer's work on 'Decide whose merged work stands.'.",
    );
    expect(producer).toContain(REOPEN);
    const consumer = dialogOf(panel(view), "Choose the consumer's work");
    expect(consumer).toContain(
      "Choose: the decision is recorded, and nothing in the run acts on it.",
    );
    expect(consumer).not.toContain(REOPEN);
  });
});

describe("the item says what choosing each position does, before anyone decides", () => {
  function facts(host: HTMLElement): Record<string, string | undefined> {
    const dts = [...host.querySelectorAll("dl.pg-facts dt")];
    return Object.fromEntries(
      dts.map((dt) => [dt.textContent, dt.nextElementSibling?.textContent]),
    );
  }

  it("for each position, its own effect", () => {
    const said = facts(panel(itemView(raw("contract", PAIR))));
    expect(said["If you choose the producer's work"]).toBe(REOPEN);
    expect(said["If you choose the consumer's work"]).toBe(CHOOSE_WORDS.record_only);
    const disputed = facts(panel(itemView(raw("arbitration", DISPUTED))));
    expect(disputed["If you choose sizing's value"]).toBe(CHOOSE_WORDS.retry);
    expect(disputed["If you choose the domain's value"]).toBe(RESIZE);
  });

  it("names the reopened module's confirmed indicator on the position that reopens it", () => {
    const one = [{ attempt: 2, kind: "disabled_checks" }];
    const said = facts(panel(itemView(raw("contract", PAIR, { indicators: one }))));
    expect(said["If you choose the producer's work"]).toBe(
      `${REOPEN} A review of the module it reopens confirmed a reward-hacking indicator: ` +
        "attempt 2 (disabled_checks).",
    );
    expect(said["If you choose the consumer's work"]).toBe(CHOOSE_WORDS.record_only);
  });

  it("names several, on the position that reopens, whichever it is", () => {
    const two = [
      { attempt: 1, kind: "hard_coded_value" },
      { attempt: 2, kind: "disabled_checks" },
    ];
    const swapped = { producer: "record_only", consumer: "reopen" };
    const said = facts(panel(itemView(raw("contract", swapped, { indicators: two }))));
    expect(said["If you choose the consumer's work"]).toBe(
      `${REOPEN} Reviews of the module it reopens confirmed reward-hacking indicators: ` +
        "attempt 1 (hard_coded_value), attempt 2 (disabled_checks).",
    );
    expect(said["If you choose the producer's work"]).toBe(CHOOSE_WORDS.record_only);
  });
});

describe("a decision on an item a reopen superseded is said to record only", () => {
  it.each(["Approve", "Reject", "Choose the producer's work", "Choose the consumer's work"])(
    "%s",
    (label) => {
      const text = dialogOf(panel(itemView(raw("contract", PAIR)), "run-1-c0"), label);
      expect(text).toContain(
        "Recorded only: a choice on run-1-c0 reopened a module this item is about, so nothing " +
          "in the run acts on this decision.",
      );
      expect(text).not.toContain(REOPEN);
    },
  );
});
