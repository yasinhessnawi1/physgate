/**
 * The library's words: a file's label from its role and kind, a staged candidate's label, the
 * states the server chooses by bytes, what a promotion would do, and the sentences the screen
 * says. Every label comes from the record through these tables: a role or a kind they do not
 * hold is shown as written, never guessed at.
 *
 * Promotion is a person's act at a terminal. These words say so, and show no command: the page
 * can show a proposed change but cannot make it.
 */
import type { Effect, FileState } from "../api/library";

/** Each role's word, as it leads a label. A role the table does not hold is shown as written. */
export const ROLE_WORDS: Readonly<Record<string, string>> = {
  control: "Control",
  electrical: "Electrical",
  mechanical: "Mechanical",
  firmware: "Firmware",
  cross: "Cross-domain",
  design: "Design",
  integration: "Integration",
  sizing: "Sizing",
};

/** Each kind of library file's word, as it ends a label. */
export const KIND_WORDS: Readonly<Record<string, string>> = {
  standards: "standards",
  skill: "skill",
  bounds: "bounds",
  rubric: "reviewer rubric",
};

/** A role as it leads a label: from the table, or as written. */
export function roleWord(role: string): string {
  return ROLE_WORDS[role] ?? role;
}

/** A role inside a sentence: the table's word in lower case, or the role as written. */
function roleInSentence(role: string): string {
  const known = ROLE_WORDS[role];
  return known === undefined ? role : known.toLowerCase();
}

/** "Control standards", "Cross-domain bounds", "Sizing reviewer rubric": role, then kind. */
export function documentLabel(kind: string, role: string): string {
  return `${roleWord(role)} ${KIND_WORDS[kind] ?? kind}`;
}

/** What a staged candidate would change, from its kind, whether it replaces, and its role. */
export function candidateLabel(kind: string, replaces: boolean, role: string): string {
  const r = roleInSentence(role);
  switch (kind) {
    case "standards":
      return `Proposed change to the ${r} standards`;
    case "skill":
      return replaces
        ? `Proposed replacement of the ${r} skill`
        : `Proposed addition to the ${r} skill`;
    case "antipattern":
      return `Proposed antipattern for the ${r} skill`;
    default:
      return `A staged ${kind} for ${r}`;
  }
}

/** A staged file that could not be read, named by the folder it is staged in. */
export function stagedErrorLabel(kind: string): string {
  return `A staged ${KIND_WORDS[kind] ?? kind} file`;
}

/** The states the server chooses by a file's bytes, never by time. None is a verdict. */
export const STATE_WORDS: Readonly<Record<FileState, string>> = {
  matches: "Matches its promotion",
  differs: "Differs from every promotion",
  "never-promoted": "Never promoted",
  "no-digest": "No digest recorded",
};

/** What promoting a candidate would do to its destination. */
export const EFFECT_WORDS: Readonly<Record<Effect, string>> = {
  creates: "Creates the file",
  "adds to": "Adds to the end of the file",
  "replaces whole": "Replaces the whole file",
};

export const LIBRARY_COPY = {
  lede: "What the next run from this checkout reads. Standards, skills and rubrics enter only by a person's promotion.",
  promotionBlock:
    "Promotion is done by a person at a terminal, by design: no agent session can change what later runs read. This page can show a proposed change but cannot promote or discard it.",
  candidate: "Candidate",
  rubricsNote:
    "Rubric text is not shown here: only reviewers read it, so that a builder cannot read the rubric it is judged by.",
  changedLines: "Changed lines (a view of the file before and after)",
  wroteThisFile: "Wrote this file",
  noDigest: "No digest recorded",
  reading: "the library",
  noLibrary:
    "This server reads no library: it was started from no checkout with a knowledge/ folder, and no library was named.",
  noLibraryTitle: "No library",
  nothingProposed: "Nothing is waiting for promotion.",
  noBoundsTable: "No bounds table is loaded.",
  noEnvelope: "No envelope is loaded.",
  noRange: "No range is loaded.",
  noStandards: "The library holds no standards file.",
  noSkills: "The library holds no skill file.",
  noRubrics: "The promotion log records no rubric.",
  noHistory: "No promotion line names this file.",
  noChange: "Promoting it would change no line.",
  noFileYet: "No file yet",
  none: "none",
  fileError: "The file could not be read.",
  stagedError: "The proposed changes could not be read.",
  candidateError: "The proposed change could not be read.",
  ratingsError: "The data-sheet ratings could not be read.",
  changes: "Proposed changes",
  antipatterns: "Proposed antipatterns",
  storeClasses: "Energy store classes",
  catalogue: "gate catalogue",
  openTheFile: "Open the file",
} as const;

/** "57 promotions recorded": a count, never a percentage. */
export function promotionsCount(n: number): string {
  return `${String(n)} promotion${n === 1 ? "" : "s"} recorded`;
}

/** "2 promotions": how many lines the log holds for one rubric. */
export function promotionLines(n: number): string {
  return `${String(n)} promotion${n === 1 ? "" : "s"}`;
}

/** The proposed section's name: its count of valid candidates, or the word alone at none. */
export function proposedTab(n: number): string {
  return n === 0 ? "Proposed" : `Proposed · ${String(n)}`;
}

/** A candidate's own time, shown as it states it: the field is informational. */
export function writtenWords(written: string): string {
  return `written ${written} (as the candidate states it)`;
}

/** ``text`` ending in a full stop, unless it ends in other punctuation already. */
function sentence(text: string): string {
  const trimmed = text.trim();
  return /[.!?…]$/.test(trimmed) ? trimmed : `${trimmed}.`;
}

/** The sentence that leads a refusal of the whole library. */
export function libraryErrorTitle(error: string): string {
  return `The library could not be read: ${sentence(error)}`;
}

/** The server's reason for refusing a link inside the library, as it words it. */
const A_LINK = /^a link inside the library is not read/;
/** The server's reason for a file over the size this page reads. */
const TOO_LARGE = /^the file is larger than this page reads/;
/** A staged file whose own kind is not its folder's. */
const KIND_MISMATCH = /^a candidate's own kind is not the kind of the directory/;
/** A staged file that is not a candidate, with the reason after the colon. */
const NOT_A_CANDIDATE = /^the file does not read as a candidate: (.*)$/s;
/** A staged file whose name is not a candidate's. */
const MISNAMED = /^the file is not named as staging names a candidate/;

/** A library file's row error, as a sentence. */
export function documentErrorWords(error: string): string {
  if (A_LINK.test(error)) return "This file is a link, so it is not read.";
  if (TOO_LARGE.test(error)) return "This file is larger than this page reads (1 MiB).";
  return `This file cannot be read here: ${sentence(error)}`;
}

/** A staged candidate's row error, as a sentence. */
export function candidateErrorWords(error: string): string {
  if (A_LINK.test(error)) return "This candidate is a link, so promotion would refuse it.";
  if (KIND_MISMATCH.test(error))
    return "This candidate's kind is not the kind of the folder it is in, so promotion would refuse it.";
  if (MISNAMED.test(error))
    return "This file is not named as staging names a candidate, so promotion would not find it.";
  const found = NOT_A_CANDIDATE.exec(error);
  if (found !== null)
    return `This candidate does not read as a candidate: ${sentence(found[1] ?? "")}`;
  return `This candidate cannot be read here: ${sentence(error)}`;
}
