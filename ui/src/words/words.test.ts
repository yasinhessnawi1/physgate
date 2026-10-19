import { describe, expect, it } from "vitest";

import { CHECK_NAMES } from "../api/run";
import { SOURCES } from "../api/queue";
import { agentOf, eventActor, writerActor } from "./actors";
import { CHECK_WORDS, checkWords } from "./checks";
import { nodeLabel, quantityLabel, VOCABULARY, word } from "./humanise";
import {
  BANNED_DECISION_WORDS,
  bannedIn,
  DECISION_COPY,
  decisionSummary,
  setAsideWith,
  SOURCE_WORDS,
} from "./queue";
import { clockTime, dayAndMinute, runLabels, utc } from "./runs";

describe("the humaniser never invents a label", () => {
  it.each(Object.entries(VOCABULARY))("expands %s to %s, and nothing else does", (token, words) => {
    expect(word(token)).toBe(words);
    expect(word(token.toUpperCase())).toBe(words);
  });

  it("keeps a token the table does not hold exactly as written", () => {
    expect(word("driver")).toBe("driver");
    expect(word("s1")).toBe("s1");
    expect(nodeLabel("electrical.node_s2_5e2ad0", "electrical")).toBe("Node s2 5e2ad0");
  });

  it("reads elec.driver as Driver under its domain, never as Motor driver", () => {
    expect(nodeLabel("elec.driver", "electrical")).toBe("Driver");
    expect(nodeLabel("electrical.motor_left", "electrical")).toBe("Motor left");
  });

  it("keeps the first segment when it is not the node's own domain", () => {
    expect(nodeLabel("iface.power_bus", "electrical")).toBe("Interface power bus");
    expect(nodeLabel("mech.housing", "electrical")).toBe("Mechanical housing");
  });

  it("keeps a key that is only its domain", () => {
    expect(nodeLabel("electrical", "electrical")).toBe("Electrical");
  });

  it("writes quantity names in sentence case, expanding only the table's tokens", () => {
    expect(quantityLabel("stall_current")).toBe("Stall current");
    expect(quantityLabel("max_temp")).toBe("Maximum temperature");
    expect(quantityLabel("i")).toBe("I");
  });

  it("gives the same label for the same key, every time", () => {
    const keys = ["elec.driver", "fw.foc", "ctl.speed_loop", "mech.gearbox.ratio"];
    for (const key of keys) expect(nodeLabel(key)).toBe(nodeLabel(key));
  });
});

describe("the check-name table covers the gate's checks exactly", () => {
  it("has one entry per check name, and no other", () => {
    expect(Object.keys(CHECK_WORDS).sort()).toEqual([...CHECK_NAMES].sort());
  });

  it("names each check in words with a one-line explanation", () => {
    for (const name of CHECK_NAMES) {
      expect(CHECK_WORDS[name].name).toMatch(/^[A-Z][a-z]/);
      expect(CHECK_WORDS[name].explains).toMatch(/\.$/);
    }
  });

  it("shows a check name it does not know as written", () => {
    expect(checkWords("brand-new").name).toBe("brand-new");
  });
});

describe("the queue-source table covers the queue's sources exactly", () => {
  it("has one entry per source, and no other", () => {
    expect(Object.keys(SOURCE_WORDS).sort()).toEqual([...SOURCES].sort());
  });

  it("says why a person is asked in a sentence", () => {
    for (const source of SOURCES) expect(SOURCE_WORDS[source].why).toMatch(/^[A-Z].*\.$/);
  });
});

describe("the decision copy says only what the harness does", () => {
  it("says nothing else happens in the run, for both verbs and every source", () => {
    expect(DECISION_COPY.then).toBe(
      "Nothing else happens in this run. The subtask is not retried, resumed or merged. If the " +
        "run is still going, the orchestrator removes the subtask's working copy at its next clean-up.",
    );
  });

  it("holds no banned word in any sentence of the table", () => {
    const all = [
      ...Object.values(DECISION_COPY),
      setAsideWith("an-item"),
      decisionSummary("Ada", "approve", "Approve the sizing", ""),
      decisionSummary("Ada", "reject", "Approve the sizing", "too hot"),
      ...SOURCES.map((s) => SOURCE_WORDS[s].why),
      ...SOURCES.map((s) => SOURCE_WORDS[s].kind),
    ];
    for (const sentence of all) expect(bannedIn(sentence), sentence).toEqual([]);
  });

  it("would find each banned phrase", () => {
    for (const planted of [
      "the subtask resumes",
      "Resume it",
      "we retry",
      "it retries",
      "the run merges it",
      "it gets a new attempt",
      "a fresh attempt",
      "This subtask waits for your decision",
      "Approve: side with reviewer",
    ])
      expect(bannedIn(planted), planted).not.toEqual([]);
    expect(BANNED_DECISION_WORDS.length).toBe(8);
  });

  it("opens the dialog with who records what", () => {
    expect(decisionSummary("Yasin K.", "approve", "Approve the motor-driver sizing", "")).toBe(
      "This records: Yasin K. approved 'Approve the motor-driver sizing'.",
    );
    expect(decisionSummary("Yasin K.", "reject", "Approve it", "Margin must hold")).toBe(
      "This records: Yasin K. rejected 'Approve it', with the note 'Margin must hold'.",
    );
  });
});

describe("a run's label is its start, in plain words", () => {
  const started = "2026-10-16T11:58:04.123456Z";

  it("reads day, month and minute in the viewer's time zone, UTC behind it", () => {
    const local = new Date(Date.parse("2026-10-16T11:58:04.123Z"));
    const hh = String(local.getHours()).padStart(2, "0");
    const mm = String(local.getMinutes()).padStart(2, "0");
    expect(dayAndMinute(started)).toBe(`${String(local.getDate())} Oct, ${hh}:${mm}`);
    expect(utc(started)).toBe("2026-10-16 11:58:04 UTC");
    expect(clockTime(started)).toMatch(/^\d{2}:\d{2}:\d{2}$/);
  });

  it("tells two runs of one minute apart by run id, and by folder when ids match", () => {
    const labels = runLabels([
      { key: "0/a", name: "a", runId: "run-a", started },
      { key: "0/b", name: "b", runId: "run-b", started },
      { key: "0/c", name: "c", runId: "run-b", started },
      { key: "0/d", name: "d", runId: "run-d", started: "2026-10-17T09:00:00Z" },
    ]);
    const shown = [...labels.values()].map((l) => l.label);
    expect(new Set(shown).size).toBe(4);
    expect(labels.get("0/a")?.label).toMatch(/· run-a$/);
    expect(labels.get("0/b")?.label).toMatch(/· b$/);
    expect(labels.get("0/c")?.label).toMatch(/· c$/);
    expect(labels.get("0/d")?.label).not.toContain("·");
    expect(labels.get("0/a")?.detail).toContain("UTC");
    expect(labels.get("0/a")?.detail).toContain("run run-a");
  });

  it("leads with Run, never with an id", () => {
    const labels = runLabels([{ key: "0/x", name: "run-0417", runId: null, started: null }]);
    expect(labels.get("0/x")?.label).toBe("Run run-0417");
  });
});

describe("actors come from the record, and an unmapped writer is shown as written", () => {
  const models = {
    roleModels: { electrical: "claude-sonnet-5" },
    decompositionModel: "claude-sonnet-5",
    reviewerModels: { electrical: "claude-opus-5-5" },
  };

  it("names an agent with its role and the model the run recorded", () => {
    expect(writerActor("electrical", models)).toEqual({
      kind: "agent",
      name: "Electrical agent",
      role: "electrical",
      model: "claude-sonnet-5",
    });
  });

  it("never gives a kind to a writer the run names no model for", () => {
    expect(writerActor("mechanical", models)).toEqual({ kind: "unmapped", name: "mechanical" });
    expect(writerActor("someone", models)).toEqual({ kind: "unmapped", name: "someone" });
    expect(agentOf("thermal", undefined)).toEqual({ kind: "unmapped", name: "Thermal agent" });
  });

  it("maps the harness's own lines to the orchestrator and the gate", () => {
    const line = { seq: 1, ts: "t" };
    expect(
      eventActor({ ...line, kind: "escalated", subtask: "s", itemId: "q" }, {}, models),
    ).toEqual({
      kind: "deterministic",
      name: "Orchestrator",
    });
    expect(
      eventActor({ ...line, kind: "gate_skipped", subtask: "s", attempt: 1 }, {}, models),
    ).toEqual({ kind: "deterministic", name: "Gate" });
  });

  it("a line of a kind the table does not list gets no actor, never a default one", () => {
    const line = { seq: 1, ts: "t" };
    expect(eventActor({ ...line, kind: "other", recorded: "tokens_spent" }, {}, models)).toBeNull();
  });

  it("names a reviewer by the model its review recorded, and a session by its subtask's role", () => {
    const line = { seq: 1, ts: "t" };
    expect(
      eventActor(
        {
          ...line,
          kind: "review_ran",
          subtask: "s",
          attempt: 1,
          verdict: "pass",
          finding: null,
          reviewerModel: "claude-opus-5-5",
          sessionId: null,
        },
        { s: "electrical" },
        models,
      ),
    ).toMatchObject({ kind: "agent", model: "claude-opus-5-5" });
    expect(
      eventActor(
        {
          ...line,
          kind: "session_ended",
          subtask: "s",
          attempt: 1,
          sessionId: "x",
          outcome: "completed",
          cause: null,
          sealed: true,
        },
        { s: "electrical" },
        models,
      ),
    ).toMatchObject({ kind: "agent", role: "electrical", model: "claude-sonnet-5" });
  });
});
