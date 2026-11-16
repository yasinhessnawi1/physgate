// @vitest-environment happy-dom
/**
 * Beside the buttons, before a person decides, every item says in plain words what each decision
 * will do, from its own consequence record and nothing else: an approve that only records says so
 * and why; an item that states no consequence says nothing extra.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { itemView } from "../../api/queue";
import type { Consequence } from "../../api/queue";
import { bannedIn, effectWords, supersededOutcome } from "../../words/queue";
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

interface Options {
  readonly source?: string;
  readonly supersededBy?: string;
  readonly holdsToken?: boolean;
  readonly unsealed?: boolean;
}

function decide(c: Record<string, unknown> | null, options: Options = {}): HTMLElement {
  const data = raw(c, options.source);
  if (options.unsealed === true)
    data.trajectories = [{ link: "/r/x", session_id: "s-1", status: "tampered" }];
  const view = itemView(data);
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
        supersededBy={options.supersededBy}
      >
        <Decide
          view={view}
          runId="run-1"
          operator="yasin"
          holdsToken={options.holdsToken ?? true}
          supersededBy={options.supersededBy}
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

function verbs(host: HTMLElement): string[] {
  return [...host.querySelectorAll(".pg-queue-effects [data-verb]")].map(
    (e) => e.getAttribute("data-verb") ?? "",
  );
}

interface Row {
  readonly name: string;
  readonly source: string;
  readonly consequence: Record<string, unknown>;
  readonly sentences: Record<string, string>;
}

// The one fixture the command line's own rows read too: a change to either copy fails a row.
const ROWS = JSON.parse(
  readFileSync(resolve(process.cwd(), "../tests/fixtures/queue_sentences.json"), "utf8"),
) as Row[];

function recordOf(c: Record<string, unknown>): Consequence {
  const indicators = (c.confirmed_indicators ?? []) as { attempt: number; kind: string }[];
  return {
    attempt: (c.attempt ?? null) as number | null,
    attemptCommit: (c.attempt_commit ?? null) as string | null,
    onApprove: c.on_approve,
    onReject: c.on_reject,
    whyRecordOnly: (c.why_record_only ?? null) as Consequence["whyRecordOnly"],
    confirmedIndicators: indicators,
    scanHits: 0,
    scanHitAttempts: [],
    judgedEarlier: [],
    onChoose: c.on_choose ?? null,
  } as Consequence;
}

describe("the sentences are the ones the command line says", () => {
  it.each(ROWS.map((r) => [r.name, r] as const))("%s", (_name, row) => {
    const said = Object.fromEntries(
      effectWords(recordOf(row.consequence)).map((e) => [
        e.key === "approve" || e.key === "reject" || e.key === "note" ? e.key : `choose_${e.key}`,
        e.text,
      ]),
    );
    expect(said).toEqual(row.sentences);
    for (const text of Object.values(said)) expect(bannedIn(text), text).toEqual([]);
  });
});

describe("what each decision will do, beside the buttons", () => {
  it("says an approve that only records will not merge, closes the item, and why", () => {
    const host = decide(
      consequence({ on_approve: "record_only", why_record_only: "gate", on_reject: "fix" }),
    );
    expect(beside(host, "approve")).toBe(
      "Approving records your decision and closes this item for good. It will not merge this " +
        "attempt, because the physics gate refused the attempt, and a person overrides the " +
        "reviewer alone.",
    );
    expect(beside(host, "note")).toContain("cannot be edited or undone");
  });

  it("says a release and the end of a run", () => {
    const host = decide(
      consequence({
        attempt: null,
        attempt_commit: null,
        on_approve: "release",
        on_reject: "end_run",
      }),
      { source: "plan_review" },
    );
    expect(beside(host, "approve")).toBe(
      "Approving releases the hold, and the plan runs as it stands.",
    );
    expect(beside(host, "reject")).toBe("Rejecting ends the run with no module dispatched.");
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
      { source: "arbitration" },
    );
    expect(verbs(host)).toEqual(["approve", "reject", "sizing", "domain", "note"]);
  });

  it("says nothing extra when the item states no consequence", () => {
    expect(decide(null).querySelector(".pg-queue-effects")).toBeNull();
  });

  it("says only what the run does with a decision on an item a reopen superseded", () => {
    const host = decide(
      consequence({
        attempt: null,
        attempt_commit: null,
        on_approve: "record_only",
        on_reject: "record_only",
        why_record_only: "source",
        on_choose: { producer: "reopen", consumer: "record_only" },
      }),
      { source: "contract", supersededBy: "run-1-contract-1" },
    );
    expect(verbs(host)).toEqual(["superseded"]);
    expect(beside(host, "superseded")).toBe(supersededOutcome("run-1-contract-1"));
    expect(host.textContent).not.toContain("is reopened for one more attempt");
  });

  it("says nothing beside buttons that cannot be pressed", () => {
    expect(
      decide(consequence(), { holdsToken: false }).querySelector(".pg-queue-effects"),
    ).toBeNull();
  });

  it("leaves out the decisions that need a seal that does not hold", () => {
    const host = decide(consequence(), { unsealed: true });
    expect(verbs(host)).toEqual(["reject", "note"]);
  });
});
