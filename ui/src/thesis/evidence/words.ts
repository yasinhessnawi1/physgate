/**
 * The Evidence screen's words: its labels, the sentence for each state, and the words for the
 * settings a comparison is refused over. A setting, a record or a reason the screen has no words
 * for is shown as written, never guessed at. Every figure a sentence holds is a value the server
 * sent: none is computed here.
 */
import type { ApartGroup, Kind, UnreadRun } from "./api";

export const EVIDENCE_COPY = {
  title: "Evidence",
  lead: "What the recorded runs measured, each figure beside the run it came from.",
  tabs: "What to show",
  runsTab: "Runs",
  spendTab: "Spend",
  compareTab: "Compare",
  catchesTab: "Catches",
  gaps: "The two gaps are not on this page yet: no measurement of them exists.",
  noRun: "This server reads no run.",
  noReadable: "None of the runs could be read.",
  readingRuns: "the runs",
  runsRefused: "The runs could not be read",
  noneOfKind: "No run of this kind was read.",
  unread: "Runs that could not be read",
  setting: "Setting",
  kind: "Kind",
  runId: "Run id",
  seed: "Seed",
  manifestId: "Manifest id",
  configCheck: "Configuration check",
  configHolds: "Matches its first log line",
  recorded: "Recorded settings",
  pinned: "Pinned settings",
  notRecorded: "not recorded",
  run: "Run",
  chooseRun: "Choose a run",
  readingPrices: "the price sheets",
  pricesRefused: "The price sheets could not be read",
  noSheet: "The server holds no price sheet, so nothing here can be priced.",
  readingSpend: "the spend",
  cost: "The run's cost",
  partial: "Partial: the figures can still change.",
  atLeast: "at least",
  lowerBound: "Lower bound",
  lowerBoundLine: "A lower bound: some calls were not priced at the rate they paid.",
  reconciliation: "Against what the sessions reported",
  noReconciliation: "No session reported a figure to set the priced calls against.",
  reportedUsd: "Reported by the sessions",
  pricedUsd: "Priced here",
  differs: "Calls whose figures differ",
  unreadCalls: "Calls with no result read",
  ttlUnread: "Calls with no cache lifetime read",
  sealBrokenCalls: "Calls whose stream changed after their session ended",
  none: "None",
  perRole: "Per role",
  noRoles: "No session's call was priced under a role.",
  sum: "Sum",
  sealBroken: "Its stream changed after its session ended, so its result was not read.",
  apart: "Apart from the roles",
  session: "Session",
  call: "Call",
  subtask: "Subtask",
  attempt: "Attempt",
  outcome: "Outcome",
  model: "Model",
  input: "Input",
  output: "Output",
  cacheRead: "Cache read",
  cacheWritten: "Cache written",
  usd: "Cost",
  notes: "Notes",
  baseline: "Baseline",
  candidate: "Candidate",
  chooseTwo: "Choose two runs to compare: a baseline and a candidate.",
  readingComparison: "the comparison",
  comparisonRefused: "The comparison could not be read",
  driftTitle:
    "These two runs cannot be compared: they did not start from the same place with the same settings",
  driftLead:
    "Set side by side, their numbers could differ because of where each started, not because of the harness, so no number of either run is shown. What differs:",
  driftFromCommits:
    "They started from different commits of the target repository, so each worked on a different design.",
  driftPossible:
    "A comparison is possible between two runs of the same brief that start from the same commit, with every setting the same but the one being measured (for example the gate on in one and off in the other).",
  driftServer: "The server's words",
  differsIn: "The reported settings that differ:",
  differsNone: "No reported setting differs.",
  differsTag: "Differs",
  readingCatches: "the gate's catches",
  catchesRefused: "The gate's catches could not be read",
  catchesLead:
    "Each kind of run is counted over its own runs alone; the counts are never added across kinds.",
  noCheck: "No gate check ran in these runs",
  countedOver: "Counted over",
  notCounted: "Runs not counted",
  check: "Check",
  gateMode: "Gate mode",
  checksRun: "Checks run",
  blockingFailures: "Blocking failures",
  reviewerPassed: "Reviewer had passed",
  reviewerFailed: "Reviewer had failed",
  notReviewed: "Not reviewed",
  artefactsCaught: "Artefacts caught",
  caughtAfterPass: "Caught after a reviewer passed",
  allChecks: "All checks",
} as const;

/** Each kind's section heading, in the order the screen shows them. */
export const KIND_HEADINGS: Readonly<Record<Kind, string>> = {
  reportable: "Reportable runs",
  development: "Development runs",
  ablation: "Ablation runs",
};

/** The tag each run of a kind carries wherever it is shown. */
export const KIND_TAGS: Readonly<Record<Kind, string>> = {
  reportable: "Reportable",
  development: "Not reportable",
  ablation: "Ablation run: measures what removing a part changes; never reportable",
};

/** A run's kind in a run chooser, after its name. */
export const KIND_CHOICES: Readonly<Record<Kind, string>> = {
  reportable: "reportable",
  development: "development, not reportable",
  ablation: "ablation, never reportable",
};

/** Each group of calls apart from the roles, and what it says when it holds none. */
export const APART_WORDS: Readonly<Record<ApartGroup, { title: string; none: string }>> = {
  decomposition: {
    title: "Decomposition",
    none: "No decomposition call was priced in this run.",
  },
  review: {
    title: "Review",
    none: "No review call was priced in this run.",
  },
  routing: {
    title: "Routing",
    none: "No routing call was priced in this run.",
  },
  left_over: {
    title: "Sessions with no recorded end",
    none: "No session without a recorded end was priced in this run.",
  },
};

/** How a cost line was priced, in words. */
const BASIS_WORDS: Readonly<Record<string, string>> = {
  list_price: "At list price",
  list_price_estimate: "A list-price estimate",
};

/** The cost line's basis and sheet: "A list-price estimate, at the price sheet of 2026-11-01." */
export function basisWords(basis: string, date: string): string {
  return `${BASIS_WORDS[basis] ?? basis}, at the price sheet of ${date}.`;
}

/** Which root a run sits under, so two runs of one name under two roots can be told apart. */
export function rootWords(root: number): string {
  return `Root ${String(root)}`;
}

/** The sheet the spend is priced at, named. */
export function pricedAtWords(date: string): string {
  return `Priced at the price sheet of ${date}, the newest the server holds.`;
}

/** What could not be read of a run, in a sentence: its record and the reader's own words. */
export function unreadWords(row: UnreadRun): string {
  const where = row.offset === null ? "" : ` at offset ${row.offset}`;
  const reason = row.reason === null ? "" : ` (${row.reason})`;
  return `Its ${row.record} could not be read${where}: ${row.error}${reason}.`;
}

/** The title of a refused spend. */
export function spendRefusedWords(name: string): string {
  return `The spend of ${name} could not be read`;
}

/** A count out of another: "1 of 2". */
export function kOfN(k: number, n: number): string {
  return `${String(k)} of ${String(n)}`;
}

/** The settings a comparison is refused over, in words. */
const DRIFT_WORDS: Readonly<Record<string, string>> = {
  "models.decomposition": "The model that plans the subtasks",
  effort: "The effort setting",
  max_output_tokens: "The output token limit",
  thinking_display: "How thinking is shown",
  role_python: "The Python the roles run",
  claude_version: "The session binary's version",
  binary: "The session binary",
  git_binary: "The Git binary",
  endpoint: "The endpoint",
  brief_sha256: "The brief",
  target_head: "The target repository's starting commit",
  bounds: "The bounds table",
  token_ceiling: "The token ceiling",
  network: "The network the sessions may reach",
  held_out_sha256: "the tasks each run withheld differ",
};

/** A drifted setting in words; a role's or a reviewer's model names its role. */
export function driftWords(path: string): string {
  const known = DRIFT_WORDS[path];
  if (known !== undefined) return known;
  const role = /^models\.roles\.(.+)$/.exec(path)?.[1];
  if (role !== undefined) return `The model the ${role} role runs on`;
  const reviewer = /^models\.reviewers\.(.+)$/.exec(path)?.[1];
  if (reviewer !== undefined) return `The model the ${reviewer} reviewer runs on`;
  return path;
}

/** A recorded setting's name, leading: `max_output_tokens` reads "Max output tokens". */
export function settingLabel(path: string): string {
  const words = path
    .split(/[._]/)
    .filter((part) => part !== "")
    .join(" ");
  return words === "" ? path : `${words.charAt(0).toUpperCase()}${words.slice(1)}`;
}

/** A recorded value as written: a string as it is, anything else as its JSON. */
export function valueWords(value: unknown): string {
  if (value === null || value === undefined) return EVIDENCE_COPY.notRecorded;
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}
