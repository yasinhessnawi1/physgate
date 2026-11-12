import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { GLOSSARY } from "../design/components/help/glossary";
import { namesACommand } from "../rules/commands";
import {
  AUTH_WORDS,
  DENSITY_WORDS,
  DESIGN_REVIEW_WORDS,
  EFFORT_WORDS,
  ENGINE_STATUS_WORDS,
  fixedBy,
  GATE_MODE_WORDS,
  MECHANISM_WORDS,
  NETWORK_WORDS,
  networkWords,
  OS_LAYER_ABSENT_WORDS,
  OS_LAYER_STATE_WORDS,
  PAIR_WORDS,
  QUEUE_DECISION_WORDS,
  recordedAs,
  refusedEntry,
  refusedValue,
  SETTINGS_COPY,
  type Table,
  THEME_WORDS,
  THINKING_WORDS,
  wordsFor,
} from "./settings";

/** Each table of words, the values it knows, in the record's own spelling. */
const TABLES: readonly (readonly [string, Table, readonly string[]])[] = [
  ["auth", AUTH_WORDS, ["subscription", "api_key"]],
  ["effort", EFFORT_WORDS, ["low", "medium", "high", "xhigh", "max"]],
  ["thinking_display", THINKING_WORDS, ["summarized", "omitted"]],
  ["network", NETWORK_WORDS, ["open", "none"]],
  ["queue_decisions", QUEUE_DECISION_WORDS, ["record", "act"]],
  ["os_layer_absent", OS_LAYER_ABSENT_WORDS, ["refuse", "allow"]],
  [
    "design_review",
    DESIGN_REVIEW_WORDS,
    ["off", "observe", "on", "repair:1", "repair:2", "repair:3"],
  ],
  ["the OS layer's state", OS_LAYER_STATE_WORDS, ["present", "absent"]],
  ["the OS layer's mechanism", MECHANISM_WORDS, ["seatbelt", "bubblewrap"]],
  ["an engine's status", ENGINE_STATUS_WORDS, ["available", "not-yet"]],
  ["gate_mode", GATE_MODE_WORDS, ["on", "observe", "off"]],
  ["theme", THEME_WORDS, ["light", "dark", "system"]],
  ["density", DENSITY_WORDS, ["compact", "comfortable"]],
];

/** Every value each table maps, with the words it must map it to. */
const MAPPED: readonly (readonly [string, Table, string, string])[] = [
  ["auth", AUTH_WORDS, "subscription", "Claude subscription"],
  ["auth", AUTH_WORDS, "api_key", "API key, billed per token"],
  ["effort", EFFORT_WORDS, "low", "Low"],
  ["effort", EFFORT_WORDS, "medium", "Medium"],
  ["effort", EFFORT_WORDS, "high", "High"],
  ["effort", EFFORT_WORDS, "xhigh", "Extra high"],
  ["effort", EFFORT_WORDS, "max", "Maximum"],
  [
    "thinking_display",
    THINKING_WORDS,
    "summarized",
    "Summarised in each session's transcript, which its reviewer reads",
  ],
  ["thinking_display", THINKING_WORDS, "omitted", "Left out of the transcripts"],
  ["network", NETWORK_WORDS, "open", "Open"],
  ["network", NETWORK_WORDS, "none", "None"],
  [
    "queue_decisions",
    QUEUE_DECISION_WORDS,
    "record",
    "Decisions are recorded. The run does not act on them.",
  ],
  [
    "queue_decisions",
    QUEUE_DECISION_WORDS,
    "act",
    "Decisions act on the run: an approval merges the attempt, and a rejection retries it, fixes it once or ends the subtask. A run like this runs only inside the OS layer.",
  ],
  [
    "os_layer_absent",
    OS_LAYER_ABSENT_WORDS,
    "refuse",
    "Role sessions run only inside the OS layer. Where it is absent, the run is refused before any session starts.",
  ],
  [
    "os_layer_absent",
    OS_LAYER_ABSENT_WORDS,
    "allow",
    "Role sessions may run without the OS layer, for development only. They are then held by the text hooks alone, and a run that acts on decisions is still refused.",
  ],
  ["design_review", DESIGN_REVIEW_WORDS, "off", "The plan is not reviewed."],
  [
    "design_review",
    DESIGN_REVIEW_WORDS,
    "observe",
    "A plan reviewer judges the plan before anything is dispatched. What it says is recorded, and the run goes on whatever it says.",
  ],
  [
    "design_review",
    DESIGN_REVIEW_WORDS,
    "on",
    "A plan reviewer judges the plan before anything is dispatched. A plan it does not pass waits for a person to decide.",
  ],
  [
    "design_review",
    DESIGN_REVIEW_WORDS,
    "repair:1",
    "As on, except that a plan the reviewer does not pass is planned again once, and reviewed again.",
  ],
  [
    "design_review",
    DESIGN_REVIEW_WORDS,
    "repair:2",
    "As on, except that a plan the reviewer does not pass is planned again at most 2 times, each reviewed again.",
  ],
  [
    "design_review",
    DESIGN_REVIEW_WORDS,
    "repair:3",
    "As on, except that a plan the reviewer does not pass is planned again at most 3 times, each reviewed again.",
  ],
  ["the OS layer's state", OS_LAYER_STATE_WORDS, "present", "Present"],
  ["the OS layer's state", OS_LAYER_STATE_WORDS, "absent", "Absent"],
  ["the OS layer's mechanism", MECHANISM_WORDS, "seatbelt", "Seatbelt"],
  ["the OS layer's mechanism", MECHANISM_WORDS, "bubblewrap", "bubblewrap"],
  ["an engine's status", ENGINE_STATUS_WORDS, "available", "Available"],
  ["an engine's status", ENGINE_STATUS_WORDS, "not-yet", "Not yet"],
  ["gate_mode", GATE_MODE_WORDS, "on", "On"],
  ["gate_mode", GATE_MODE_WORDS, "observe", "Observe"],
  ["gate_mode", GATE_MODE_WORDS, "off", "Off"],
  ["theme", THEME_WORDS, "light", "Light"],
  ["theme", THEME_WORDS, "dark", "Dark"],
  ["theme", THEME_WORDS, "system", "Follow the system"],
  ["density", DENSITY_WORDS, "compact", "Compact"],
  ["density", DENSITY_WORDS, "comfortable", "Comfortable"],
];

describe("the words map exactly the values this version knows", () => {
  it.each(TABLES)("%s knows exactly its values", (_, table, values) => {
    expect(Object.keys(table)).toEqual(values);
  });

  it.each(MAPPED)("%s: %s reads %s", (_, table, value, words) => {
    expect(wordsFor(table, value)).toEqual({ kind: "known", words });
  });

  it.each(TABLES)("%s shows a value it does not know as written", (_, table) => {
    for (const value of ["turbo", "", "Subscription", "constructor", "toString", "__proto__"])
      expect(wordsFor(table, value)).toEqual({ kind: "as-written", value });
  });
});

describe("the network for role sessions' shells is read with whether it was enforced", () => {
  it.each([
    ["none", true, "None, enforced by the OS layer"],
    ["none", false, "None requested, not enforceable here"],
    ["none", null, "None, not measured"],
    ["none", undefined, "None. Whether it was enforced is not recorded by this run"],
    ["open", null, "Open"],
    ["open", undefined, "Open"],
    ["open", true, "Open"],
  ] as const)("%s with enforced %s reads %s", (network, enforced, words) => {
    expect(networkWords(network, enforced)).toEqual({ kind: "known", words });
  });

  it("shows a network it does not know as written, and claims nothing of enforcement", () => {
    expect(networkWords("loopback", true)).toEqual({ kind: "as-written", value: "loopback" });
  });
});

describe("the sentences the screen says", () => {
  it("names the token ceiling for what it bounds, and never a budget", () => {
    expect(SETTINGS_COPY.tokenCeiling).toBe("What each session loads at start, at most");
    expect(SETTINGS_COPY.defaultTokenCeiling).toBe(
      "Each run names this ceiling in its parameters. A default kept here is coming.",
    );
    const table = GLOSSARY as Readonly<Record<string, { means: string }>>;
    expect(table["token-ceiling"]?.means).toBe(
      "The most a role session may load before it starts work: its standards, its spec and its skill file. It is counted generously, one token for every byte, so a set can be refused while really under it. It is not a budget for the run.",
    );
  });

  it("compares a pair's two recorded strings, and says the harness is what checks the rule", () => {
    expect(PAIR_WORDS.different).toBe("Different model strings");
    expect(PAIR_WORDS.same).toBe(
      "Same model string as its builder: the harness refuses to start this reviewer",
    );
    expect(SETTINGS_COPY.pairsNote).toBe(
      "A reviewer runs on a different model from what it reviews. The harness checks this when each reviewer starts, and also refuses two spellings of one model.",
    );
    for (const words of Object.values(PAIR_WORDS)) expect(words).not.toMatch(/checked|verified/i);
  });

  it("says a refused value and a refused entry in one sentence, with the reason", () => {
    expect(refusedValue("it is not text")).toBe("This value could not be read: it is not text.");
    expect(refusedEntry("its name is not text")).toBe(
      "This entry could not be read: its name is not text.",
    );
  });

  it("says who decisions here are recorded as, and when the address fixes the theme", () => {
    expect(recordedAs("Yasin K.")).toBe("Decisions taken in this window are recorded as Yasin K.");
    expect(fixedBy("dark")).toBe("Fixed to dark by this page's address");
    expect(fixedBy("light")).toBe("Fixed to light by this page's address");
  });

  it("names the menus where things are set, and no command", () => {
    expect(SETTINGS_COPY.engineChosenWhere).toContain("physgate menu → Engine…");
    expect(SETTINGS_COPY.operatorWhere).toBe("In the desktop app: physgate menu → Operator Name…");
  });

  it("says what sets each disabled value today, and that a kept default is coming", () => {
    for (const key of [
      "defaultEngine",
      "defaultBuilder",
      "defaultGateMode",
      "defaultTokenCeiling",
    ] as const)
      expect(SETTINGS_COPY[key], key).toMatch(/A default kept here is coming\.$/);
    expect(SETTINGS_COPY.defaultReviewer).toContain(
      "the harness refuses it when the reviewer starts",
    );
  });
});

/** Every string the words module holds: its tables and its sentences. */
const EVERY_STRING: readonly string[] = [
  ...TABLES.flatMap(([, table]) => Object.values(table)),
  ...Object.values(PAIR_WORDS),
  ...Object.values(SETTINGS_COPY),
  refusedValue("x"),
  refusedEntry("x"),
  recordedAs("x"),
  fixedBy("dark"),
];

describe("no sentence names a terminal command", () => {
  it("finds none in any of the words", () => {
    expect(EVERY_STRING.length).toBeGreaterThan(60);
    expect(EVERY_STRING.filter(namesACommand)).toEqual([]);
  });
});

/**
 * What no Settings text may claim: a credential's state, a default kept as if set, or a budget.
 * The planted examples are built at run time, so the patterns are the only literals here.
 */
const CLAIMS: readonly RegExp[] = [
  /signed[\s-]*in/i,
  /\bconnected\b/i,
  /your\s+key/i,
  /keychain\s+token/i,
  /\btoken\s+(is\s+)?(kept|stored|saved)\b/i,
  /\bbudget\b/i,
  /\bDefault:\s/,
];

const SRC = fileURLToPath(new URL("..", import.meta.url));

/** The Settings screen's sources and its words, as written. */
function settingsSources(): { path: string; text: string }[] {
  const screen = join(SRC, "screens", "settings");
  const own = existsSync(screen)
    ? readdirSync(screen)
        .filter((name) => !/\.test\.tsx?$/.test(name))
        .map((name) => join("screens", "settings", name))
    : [];
  return [join("words", "settings.ts"), ...own].map((path) => ({
    path,
    text: readFileSync(join(SRC, path), "utf8"),
  }));
}

describe("no Settings text claims a credential's state, a kept default or a budget", () => {
  it("finds none in the screen's sources or its words", () => {
    const found = settingsSources().flatMap((f) =>
      CLAIMS.filter((claim) => claim.test(f.text)).map((claim) => `${f.path}: ${String(claim)}`),
    );
    expect(found).toEqual([]);
  });

  it("finds none in any of the words", () => {
    expect(EVERY_STRING.filter((s) => CLAIMS.some((claim) => claim.test(s)))).toEqual([]);
  });

  it("would find each kind", () => {
    const join2 = (...parts: string[]) => parts.join("");
    for (const planted of [
      join2("Claude Code · signed", " in with subscription"),
      join2("Sign", "ed-in"),
      join2("The engine is con", "nected"),
      join2("Paste your ", "key"),
      join2("Keychain ", "token present"),
      join2("A token is ", "kept"),
      join2("Run bud", "get 10.00 USD"),
      join2("Default", ": Opus"),
    ])
      expect(
        CLAIMS.some((claim) => claim.test(planted)),
        planted,
      ).toBe(true);
  });
});

describe("the glossary explains every term the screen uses", () => {
  it.each([
    ["engine", "Engine"],
    ["engine-catalogue", "Engine catalogue"],
    ["builder-model", "Builder model"],
    ["reviewer-model", "Reviewer model (pairing)"],
    ["plan-reviewer", "Plan reviewer"],
    ["endpoint", "Endpoint"],
    ["effort", "Effort"],
    ["token-ceiling", "Token ceiling"],
    ["session-limits", "Session limits"],
    ["default-for-new-runs", "Default for new runs"],
    ["recorded-value", "Recorded value"],
  ] as const)("%s is the term %s, with a sentence", (key, term) => {
    const table = GLOSSARY as Readonly<Record<string, { term: string; means: string }>>;
    expect(table[key]?.term).toBe(term);
    expect(table[key]?.means.length ?? 0).toBeGreaterThan(40);
  });

  it("says how the harness reads a value an older run did not write", () => {
    const table = GLOSSARY as Readonly<Record<string, { means: string }>>;
    expect(table["recorded-value"]?.means).toContain("did not write");
  });
});
