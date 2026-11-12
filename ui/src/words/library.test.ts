import { describe, expect, it } from "vitest";

import { namesACommand } from "../rules/commands";
import { bannedIn } from "./queue";
import {
  candidateErrorWords,
  candidateLabel,
  documentErrorWords,
  documentLabel,
  EFFECT_WORDS,
  LIBRARY_COPY,
  libraryErrorTitle,
  promotionsCount,
  proposedTab,
  roleWord,
  STATE_WORDS,
  stagedErrorLabel,
  writtenWords,
} from "./library";

/** Every label the table holds, as a person reads it: role, kind, label. */
const LABELS: readonly (readonly [string, string, string])[] = [
  ["control", "standards", "Control standards"],
  ["control", "skill", "Control skill"],
  ["control", "bounds", "Control bounds"],
  ["control", "rubric", "Control reviewer rubric"],
  ["electrical", "standards", "Electrical standards"],
  ["electrical", "skill", "Electrical skill"],
  ["electrical", "bounds", "Electrical bounds"],
  ["electrical", "rubric", "Electrical reviewer rubric"],
  ["mechanical", "standards", "Mechanical standards"],
  ["mechanical", "skill", "Mechanical skill"],
  ["mechanical", "bounds", "Mechanical bounds"],
  ["mechanical", "rubric", "Mechanical reviewer rubric"],
  ["firmware", "standards", "Firmware standards"],
  ["firmware", "skill", "Firmware skill"],
  ["firmware", "bounds", "Firmware bounds"],
  ["firmware", "rubric", "Firmware reviewer rubric"],
  ["cross", "standards", "Cross-domain standards"],
  ["cross", "bounds", "Cross-domain bounds"],
  ["design", "standards", "Design standards"],
  ["design", "skill", "Design skill"],
  ["design", "rubric", "Design reviewer rubric"],
  ["integration", "standards", "Integration standards"],
  ["integration", "skill", "Integration skill"],
  ["integration", "rubric", "Integration reviewer rubric"],
  ["sizing", "standards", "Sizing standards"],
  ["sizing", "skill", "Sizing skill"],
  ["sizing", "rubric", "Sizing reviewer rubric"],
];

describe("a library file's label is its role and its kind, in words", () => {
  it.each(LABELS)("%s %s reads %s", (role, kind, label) => {
    expect(documentLabel(kind, role)).toBe(label);
  });

  it("drops the word the design drew and the record does not say", () => {
    for (const [role, kind] of LABELS) expect(documentLabel(kind, role)).not.toMatch(/engineering/);
  });

  it("shows a role the table does not hold as written, never guessed", () => {
    expect(documentLabel("standards", "laws")).toBe("laws standards");
    expect(roleWord("laws")).toBe("laws");
    expect(roleWord("power_stage")).toBe("power_stage");
  });

  it("shows a kind the table does not hold as written in full", () => {
    expect(documentLabel("law", "laws")).toBe("laws law");
    expect(documentLabel("law", "control")).toBe("Control law");
  });
});

describe("a staged candidate's label names what it would change", () => {
  it.each([
    ["standards", false, "control", "Proposed change to the control standards"],
    ["standards", true, "control", "Proposed change to the control standards"],
    ["skill", false, "control", "Proposed addition to the control skill"],
    ["skill", true, "control", "Proposed replacement of the control skill"],
    ["antipattern", false, "firmware", "Proposed antipattern for the firmware skill"],
    ["standards", false, "cross", "Proposed change to the cross-domain standards"],
    ["skill", false, "sizing", "Proposed addition to the sizing skill"],
    ["standards", false, "laws", "Proposed change to the laws standards"],
  ] as const)("%s (replaces: %s) for %s reads %s", (kind, replaces, role, label) => {
    expect(candidateLabel(kind, replaces, role)).toBe(label);
  });

  it("shows a kind it does not know as written", () => {
    expect(candidateLabel("law", false, "laws")).toBe("A staged law for laws");
  });

  it("names a row it could not read by its folder's kind, in words", () => {
    expect(stagedErrorLabel("standards")).toBe("A staged standards file");
    expect(stagedErrorLabel("skill")).toBe("A staged skill file");
    expect(stagedErrorLabel("antipattern")).toBe("A staged antipattern file");
  });
});

describe("the states, the effects and the sentences", () => {
  it("names each state the server chooses by bytes", () => {
    expect(STATE_WORDS).toEqual({
      matches: "Matches its promotion",
      differs: "Differs from every promotion",
      "never-promoted": "Never promoted",
      "no-digest": "No digest recorded",
    });
  });

  it("names each effect a promotion would have", () => {
    expect(EFFECT_WORDS).toEqual({
      creates: "Creates the file",
      "adds to": "Adds to the end of the file",
      "replaces whole": "Replaces the whole file",
    });
  });

  it("says what the next run reads, and that only some files enter by promotion", () => {
    expect(LIBRARY_COPY.lede).toBe(
      "What the next run from this checkout reads. Standards, skills and rubrics enter only by a person's promotion.",
    );
    const all = Object.values(LIBRARY_COPY).join(" ");
    expect(all).not.toMatch(/every run reads/i);
    expect(all).not.toMatch(/nothing enters/i);
  });

  it("says promotion is a person's act at a terminal, with no command", () => {
    expect(LIBRARY_COPY.promotionBlock).toBe(
      "Promotion is done by a person at a terminal, by design: no agent session can change what later runs read. This page can show a proposed change but cannot promote or discard it.",
    );
    expect(LIBRARY_COPY.candidate).toBe("Candidate");
    for (const text of Object.values(LIBRARY_COPY)) expect(namesACommand(text), text).toBe(false);
  });

  it("would find a command planted in the promotion block", () => {
    const planted = `${LIBRARY_COPY.promotionBlock} ${["physgate", "knowledge", "promote", "x"].join(" ")}`;
    expect(namesACommand(planted)).toBe(true);
  });

  it("says why rubric text is not shown, and what the diff is", () => {
    expect(LIBRARY_COPY.rubricsNote).toBe(
      "Rubric text is not shown here: only reviewers read it, so that a builder cannot read the rubric it is judged by.",
    );
    expect(LIBRARY_COPY.changedLines).toBe("Changed lines (a view of the file before and after)");
    expect(LIBRARY_COPY.wroteThisFile).toBe("Wrote this file");
    expect(LIBRARY_COPY.noDigest).toBe("No digest recorded");
  });

  it("has the empty and loading sentences, the no-library one naming no command", () => {
    expect(LIBRARY_COPY.reading).toBe("the library");
    expect(LIBRARY_COPY.noLibrary).toBe(
      "This server reads no library: it was started from no checkout with a knowledge/ folder, and no library was named.",
    );
    expect(LIBRARY_COPY.nothingProposed).toBe("Nothing is waiting for promotion.");
    expect(LIBRARY_COPY.noBoundsTable).toBe("No bounds table is loaded.");
    expect(LIBRARY_COPY.noEnvelope).toBe("No envelope is loaded.");
  });

  it("counts promotions and the proposed tab, never as a percentage", () => {
    expect(promotionsCount(57)).toBe("57 promotions recorded");
    expect(promotionsCount(1)).toBe("1 promotion recorded");
    expect(promotionsCount(0)).toBe("0 promotions recorded");
    expect(proposedTab(4)).toBe("Proposed · 4");
    expect(proposedTab(0)).toBe("Proposed");
  });

  it("says the written time is the candidate's own", () => {
    expect(writtenWords("2026-11-01T10:00:00Z")).toBe(
      "written 2026-11-01T10:00:00Z (as the candidate states it)",
    );
  });

  it("leads an error with a sentence naming what could not be read", () => {
    expect(libraryErrorTitle("the promotion log has a line this version cannot read")).toBe(
      "The library could not be read: the promotion log has a line this version cannot read.",
    );
    expect(libraryErrorTitle("refused.")).toBe("The library could not be read: refused.");
  });

  it("says nothing about a decision the harness does not make", () => {
    expect(bannedIn(Object.values(LIBRARY_COPY).join(" "))).toEqual([]);
  });
});

describe("a row's own error is a sentence", () => {
  it("for a library file", () => {
    expect(
      documentErrorWords(
        "a link inside the library is not read, so where it points is never shown",
      ),
    ).toBe("This file is a link, so it is not read.");
    expect(documentErrorWords("the file is larger than this page reads (1048576 bytes)")).toBe(
      "This file is larger than this page reads (1 MiB).",
    );
    expect(documentErrorWords("the file has more than one name on disk")).toBe(
      "This file cannot be read here: the file has more than one name on disk.",
    );
  });

  it("for a staged candidate", () => {
    expect(
      candidateErrorWords(
        "a link inside the library is not read, so where it points is never shown",
      ),
    ).toBe("This candidate is a link, so promotion would refuse it.");
    expect(
      candidateErrorWords(
        "a candidate's own kind is not the kind of the directory it is staged in",
      ),
    ).toBe(
      "This candidate's kind is not the kind of the folder it is in, so promotion would refuse it.",
    );
    expect(
      candidateErrorWords("the file does not read as a candidate: episode_id: Field required"),
    ).toBe("This candidate does not read as a candidate: episode_id: Field required.");
    expect(candidateErrorWords("the file is not named as staging names a candidate")).toBe(
      "This file is not named as staging names a candidate, so promotion would not find it.",
    );
    expect(candidateErrorWords("the file has more than one name on disk")).toBe(
      "This candidate cannot be read here: the file has more than one name on disk.",
    );
  });
});
