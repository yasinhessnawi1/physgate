// @vitest-environment happy-dom
/**
 * The timeline's rows for disputes, rulings, failed contracts, reopens and returns: each a
 * sentence built from the fields its line names and nothing else. Sizing's held value and a
 * contract's values never reach a row, and a dispute's reason is shown only folded, as the
 * disputing agent's own words, which nothing checks.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { runEvent } from "../../api/events";
import type { LedgerLine } from "../../api/records";
import { bannedIn } from "../../words/queue";
import { RowView } from "../common/RowView";
import { type Row, rowsOf } from "../common/rows";
import { LedgerTable } from "../run-records/Ledger";
import { foldLedger } from "../run-records/ledgerRows";

const MODELS = {
  roleModels: { electrical: "claude-sonnet-5" },
  decompositionModel: "claude-sonnet-5",
  reviewerModels: {},
};

const ON = { run_id: "r", gate_mode: "on" };
let next = 0;
/** One event line as the Python loop writes it, with the next sequence number. */
function written(fields: Record<string, unknown>): Record<string, unknown> {
  const seq = next++;
  return { seq, ts: `2026-10-31T09:00:${String(seq).padStart(2, "0")}.000000Z`, ...ON, ...fields };
}

const POSITION = { node_id: "drive_motor", name: "current_draw" };
const STANDING = { gate_refused: false, counted_before: 0, attempt_left: true };
const HELD = {
  position: { ...POSITION, value: 2.5, unit: "A" },
  source: "the sizing pass",
  written_by: "sizing",
  revision: 12,
};
const REASON = "The motor stalls at 2.5 A under the stated load, so it needs 4 A.";

function ruled(level: string): Record<string, unknown> {
  return written({
    kind: "arbitration_decided",
    subtask_id: "s1",
    attempt: 2,
    conflict: { kind: "dispute", ...POSITION },
    standing: STANDING,
    level,
    held: HELD,
  });
}

function contract(level: string, quantity: string | null, found: number): Record<string, unknown> {
  const value = (node: string, v: number, revision: number) => ({
    position: { node_id: node, name: quantity, value: v, unit: "A" },
    revision,
  });
  return written({
    kind: "contract_ruled",
    conflict: { kind: "contract", interface: "power_bus", quantity },
    standing: STANDING,
    level,
    wanted: quantity === null ? null : value("power_bus", 2, 3),
    found: Array.from({ length: found }, (_, i) => value(`node_${String(i)}`, 3, 4)),
  });
}

const PLANNED = [
  written({ kind: "subtask_planned", subtask_id: "s1", assigned_role: "electrical" }),
  written({ kind: "subtask_planned", subtask_id: "s2", assigned_role: "firmware" }),
  written({ kind: "subtask_planned", subtask_id: "s3", assigned_role: "firmware" }),
];
const DISPUTE = written({
  kind: "dispute_recorded",
  subtask_id: "s1",
  attempt: 2,
  position: { ...POSITION, value: 4, unit: "A" },
  reason: REASON,
});
const LEVELS = { gate: ruled("gate"), person: ruled("person"), sizing: ruled("sizing") };
const QUEUED = ruled("queue");
const CONTRACTS = {
  queue: contract("queue", "current_draw", 2),
  gate: contract("gate", "current_draw", 1),
  bare: contract("queue", null, 1),
};
const RAISED = written({ kind: "contract_item_raised", item_id: "r-contract-1" });
const RETURNED = written({
  kind: "attempt_returned",
  subtask_id: "s1",
  attempt: 2,
  item_id: "r-s1-1",
});
const REOPENED = written({
  kind: "subtask_reopened",
  subtask_id: "s3",
  item_id: "r-contract-1",
  shown_sha256: "a".repeat(64),
  merge_commit: `abc1234${"d".repeat(33)}`,
  attempt: 2,
});
const ENDED = {
  person: written({
    kind: "subtask_rejected",
    subtask_id: "s3",
    attempt: 2,
    by: "person",
    item_id: "r-s3-1",
  }),
  fix: written({
    kind: "subtask_rejected",
    subtask_id: "s3",
    attempt: 3,
    by: "fix_not_accepted",
    item_id: null,
  }),
  pass: written({
    kind: "subtask_rejected",
    subtask_id: "s1",
    attempt: 2,
    by: "closing_pass",
    item_id: "r-s1-1",
  }),
};

const LINES = [
  ...PLANNED,
  DISPUTE,
  ...Object.values(LEVELS),
  QUEUED,
  ...Object.values(CONTRACTS),
  RAISED,
  RETURNED,
  REOPENED,
  ...Object.values(ENDED),
];
const EVENTS = LINES.map(runEvent);
const ROWS = rowsOf(EVENTS, MODELS);

/** The row the line was written as, if it has one. */
function rowOfLine(line: Record<string, unknown>): Row | undefined {
  return ROWS.find((r) => r.seq === line.seq);
}

describe("a dispute's row says what the agent proposes, and folds its reason as its own words", () => {
  const row = rowOfLine(DISPUTE);

  it("names the attempt, the quantity, the node and the proposed value, by the agent", () => {
    expect(row?.sentence).toBe(
      "Attempt 2 disputes sizing's value of Current draw on Drive motor, proposing",
    );
    expect(row?.value).toEqual({ value: 4, unit: "A" });
    expect(row?.depth).toBe(2);
    expect(row?.meta).toBe("Subtask 1 · attempt 2 · drive_motor · current_draw");
    expect(row?.actor).toEqual({
      kind: "agent",
      name: "Electrical agent",
      role: "electrical",
      model: "claude-sonnet-5",
    });
  });

  it("folds the reason, labelled as the agent's own words, which nothing checks", () => {
    expect(row?.more).toBe(`The agent's reason, in its own words, which nothing checks: ${REASON}`);
    const host = document.createElement("div");
    host.innerHTML = row === undefined ? "" : renderToStaticMarkup(<RowView row={row} />);
    const folded = host.querySelector("details");
    expect(folded?.textContent).toContain(
      `The agent's reason, in its own words, which nothing checks: ${REASON}`,
    );
    // Outside the fold the reason is nowhere: not in the sentence, the meta or the value.
    folded?.remove();
    expect(host.textContent).toContain("disputes sizing's value");
    expect(host.textContent).not.toContain("stalls");
  });
});

describe("a ruling's row says which level stands, by its name, and never sizing's value", () => {
  it.each([
    [
      "gate",
      "The gate refused attempt 2, so its refusal stands over the dispute of Current draw on Drive motor",
    ],
    [
      "person",
      "A person's choice stands: attempt 2 holds the value chosen for Current draw on Drive motor",
    ],
    ["sizing", "Sizing's value of Current draw on Drive motor stands over attempt 2's dispute"],
  ] as const)("at level %s", (level, says) => {
    const row = rowOfLine(LEVELS[level]);
    expect(row?.sentence).toBe(says);
    expect(row?.depth).toBe(2);
    expect(row?.value).toBeNull();
    expect(row?.meta).toBe("Subtask 1 · attempt 2 · sizing's value from revision 12");
    expect(row?.actor).toEqual({ kind: "deterministic", name: "Orchestrator" });
  });

  it("at the queue", () => {
    expect(rowOfLine(QUEUED)?.sentence).toBe(
      "The dispute of Current draw on Drive motor goes to a person",
    );
  });
});

describe("a failed contract's rows name the clause and the count of failing nodes, never a value", () => {
  it("a clause that goes to a person", () => {
    const row = rowOfLine(CONTRACTS.queue);
    expect(row?.sentence).toBe(
      "The contract clause Current draw on interface Power bus failed: ruled for a person",
    );
    expect(row?.meta).toBe("contract · 2 failing nodes");
    expect(row?.depth).toBe(0);
    expect(row?.value).toBeNull();
    expect(row?.actor).toEqual({ kind: "deterministic", name: "Orchestrator" });
  });

  it("a clause the gate refused", () => {
    const row = rowOfLine(CONTRACTS.gate);
    expect(row?.sentence).toBe(
      "The gate's refusal stands over the contract clause Current draw on interface Power bus",
    );
    expect(row?.meta).toBe("contract · 1 failing node");
  });

  it("an interface with no quantity", () => {
    expect(rowOfLine(CONTRACTS.bare)?.sentence).toBe(
      "Interface Power bus has no quantity, and a side is not joined to it: ruled for a person",
    );
  });

  it("the item it raised", () => {
    const row = rowOfLine(RAISED);
    expect(row?.sentence).toBe("A failed contract was sent to a person (r-contract-1)");
    expect(row?.depth).toBe(0);
    expect(row?.actor).toEqual({ kind: "deterministic", name: "Orchestrator" });
  });
});

describe("a return, a reopen and an end say what a person's decision ordered", () => {
  it("an attempt judged again once sizing's closing pass merged", () => {
    const row = rowOfLine(RETURNED);
    expect(row?.sentence).toBe(
      "Sizing's closing pass merged; attempt 2 is judged again from its finished session, with no new session (r-s1-1)",
    );
    expect(row?.depth).toBe(2);
    expect(row?.actor).toEqual({ kind: "deterministic", name: "Orchestrator" });
  });

  it("a module reopened, its earlier merge kept", () => {
    const row = rowOfLine(REOPENED);
    expect(row?.sentence).toBe(
      "Subtask 3 reopened for attempt 2, as a person's choice on r-contract-1 ordered; its earlier merge stays on the record",
    );
    expect(row?.meta).toBe("s3 · earlier merge abc1234");
    expect(row?.depth).toBe(1);
  });

  it.each([
    ["person", "Subtask 3 ended rejected, as a person's decision ordered (r-s3-1)"],
    ["fix", "Subtask 3 ended rejected: the fix a person ordered was not accepted"],
    [
      "pass",
      "Subtask 1 ended rejected: sizing's closing pass ended without merging the value a person chose (r-s1-1)",
    ],
  ] as const)("a subtask ended by %s", (by, says) => {
    const row = rowOfLine(ENDED[by]);
    expect(row?.sentence).toBe(says);
    expect(row?.depth).toBe(1);
    expect(row?.actor).toEqual({ kind: "deterministic", name: "Orchestrator" });
  });

  it("no row uses a word that claims more than the record", () => {
    const said = ROWS.map((r) => `${r.sentence} ${r.meta} ${r.more ?? ""}`).join("\n");
    expect(bannedIn(said)).toEqual([]);
  });
});

describe("no held or contract value, source or writer reaches a screen", () => {
  const canaries = /SOURCECANARY|WRITERCANARY|UNITCANARY|VALUECANARY/;
  const marked = [
    ...PLANNED,
    written({
      kind: "arbitration_decided",
      subtask_id: "s1",
      attempt: 2,
      conflict: { kind: "dispute", ...POSITION },
      standing: STANDING,
      level: "sizing",
      held: {
        position: { ...POSITION, value: 2.5, unit: "UNITCANARY" },
        source: "SOURCECANARY",
        written_by: "WRITERCANARY",
        revision: 12,
      },
    }),
    written({
      kind: "contract_ruled",
      conflict: { kind: "contract", interface: "power_bus", quantity: "current_draw" },
      standing: STANDING,
      level: "queue",
      wanted: {
        position: { node_id: "power_bus", name: "current_draw", value: 2, unit: "UNITCANARY" },
        revision: 3,
      },
      found: [
        {
          position: { node_id: "node_0", name: "current_draw", value: 3, unit: "UNITCANARY" },
          revision: 4,
        },
      ],
    }),
  ];
  const events = marked.map(runEvent);

  it("the lines are read, as a ruling and a contract", () => {
    expect(events.map((e) => e.kind)).toEqual([
      "subtask_planned",
      "subtask_planned",
      "subtask_planned",
      "arbitration_decided",
      "contract_ruled",
    ]);
  });

  it("the parser keeps none of them", () => {
    expect(JSON.stringify(events)).not.toMatch(canaries);
  });

  it("neither the timeline nor the run records draw one", () => {
    const rows = rowsOf(events, MODELS);
    expect(rows.length).toBe(5);
    const timeline = rows.map((row) => renderToStaticMarkup(<RowView row={row} />)).join("");
    expect(timeline).toContain("Sizing's value of Current draw on Drive motor stands");
    expect(timeline).not.toMatch(canaries);
    const lines: LedgerLine[] = [
      { id: "s1", role: "electrical", attempts: 2, gate: "pass", review: null, mergeCommit: null },
    ];
    const ledger = renderToStaticMarkup(
      <LedgerTable
        rows={foldLedger(lines, { events, status: null, queue: null, budget: 3 })}
        lines={1}
        mode="on"
        run="r"
      />,
    );
    expect(ledger).toContain("Electrical module");
    expect(ledger).not.toMatch(canaries);
  });
});
