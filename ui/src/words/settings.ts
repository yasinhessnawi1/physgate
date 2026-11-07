/**
 * Everything the Settings screen says, in one place: its labels, its sentences, and the words for
 * each value of a recorded field this version knows.
 *
 * Three rules hold every line here. Nothing is shown as set where nothing keeps it: physgate keeps
 * no defaults for new runs, so a disabled control's sentence says what sets the value today, in
 * words, and never names a command. A run's values are that run's, and the catalogue's defaults
 * are the catalogue's. And no line says anything of a credential's state: whether one is kept is
 * known only to the desktop app, never to this page.
 *
 * A value a table does not hold is shown as written, never mapped onto a word it might resemble.
 */

/** A value in words, or, where these words do not know it, as the record wrote it. */
export type Worded =
  | { readonly kind: "known"; readonly words: string }
  | { readonly kind: "as-written"; readonly value: string };

export type Table = Readonly<Record<string, string>>;

/** How a run's sessions reach the engine. */
export const AUTH_WORDS: Table = {
  subscription: "Claude subscription",
  api_key: "API key, billed per token",
};

export const EFFORT_WORDS: Table = {
  low: "Low",
  medium: "Medium",
  high: "High",
  xhigh: "Extra high",
  max: "Maximum",
};

export const THINKING_WORDS: Table = {
  summarized: "Summarised in each session's transcript, which its reviewer reads",
  omitted: "Left out of the transcripts",
};

export const NETWORK_WORDS: Table = {
  open: "Open",
  none: "None",
};

export const QUEUE_DECISION_WORDS: Table = {
  record: "Decisions are recorded. The run does not act on them.",
  act:
    "Decisions act on the run: an approval merges the attempt, and a rejection retries it, " +
    "fixes it once or ends the subtask. A run like this runs only inside the OS layer.",
};

export const OS_LAYER_ABSENT_WORDS: Table = {
  refuse:
    "Role sessions run only inside the OS layer. Where it is absent, the run is refused before " +
    "any session starts.",
  allow:
    "Role sessions may run without the OS layer, for development only. They are then held by " +
    "the text hooks alone, and a run that acts on decisions is still refused.",
};

function replans(times: string, each: string): string {
  return `As on, except that a plan the reviewer does not pass is planned again ${times}, ${each}.`;
}

export const DESIGN_REVIEW_WORDS: Table = {
  off: "The plan is not reviewed.",
  observe:
    "A plan reviewer judges the plan before anything is dispatched. What it says is recorded, " +
    "and the run goes on whatever it says.",
  on:
    "A plan reviewer judges the plan before anything is dispatched. A plan it does not pass " +
    "waits for a person to decide.",
  "repair:1": replans("once", "and reviewed again"),
  "repair:2": replans("at most 2 times", "each reviewed again"),
  "repair:3": replans("at most 3 times", "each reviewed again"),
};

export const OS_LAYER_STATE_WORDS: Table = {
  present: "Present",
  absent: "Absent",
};

export const MECHANISM_WORDS: Table = {
  seatbelt: "Seatbelt",
  bubblewrap: "bubblewrap",
};

/** An engine's status in the catalogue. Only "available" can be chosen. */
export const ENGINE_STATUS_WORDS = {
  available: "Available",
  "not-yet": "Not yet",
} as const satisfies Table;

/** The gate mode's options, for a control that draws them. */
export const GATE_MODE_WORDS: Table = {
  on: "On",
  observe: "Observe",
  off: "Off",
};

export const THEME_WORDS: Table = {
  light: "Light",
  dark: "Dark",
  system: "Follow the system",
};

export const DENSITY_WORDS: Table = {
  compact: "Compact",
  comfortable: "Comfortable",
};

/**
 * A reviewer's model beside its builder's: a comparison of two recorded strings, never a claim
 * that a review ran or passed. The harness holds the rule itself, when each reviewer starts.
 */
export const PAIR_WORDS = {
  different: "Different model strings",
  same: "Same model string as its builder: the harness refuses to start this reviewer",
} as const;

/** ``value`` in ``table``'s words, or as written. Only the table's own entries are words. */
export function wordsFor(table: Table, value: string): Worded {
  return Object.hasOwn(table, value)
    ? { kind: "known", words: table[value] ?? value }
    : { kind: "as-written", value };
}

/**
 * The network role sessions' shells had, with whether anything enforced it. ``enforced`` is
 * ``null`` where the harness recorded no measure and ``undefined`` where the run recorded nothing
 * of it. An open network makes no claim of enforcement either way.
 */
export function networkWords(network: string, enforced: boolean | null | undefined): Worded {
  if (network === "open") return { kind: "known", words: "Open" };
  if (network !== "none") return { kind: "as-written", value: network };
  const words =
    enforced === true
      ? "None, enforced by the OS layer"
      : enforced === false
        ? "None requested, not enforceable here"
        : enforced === null
          ? "None, not measured"
          : "None. Whether it was enforced is not recorded by this run";
  return { kind: "known", words };
}

/** A value the guard refused, in its own row. */
export function refusedValue(reason: string): string {
  return `This value could not be read: ${reason}.`;
}

/** A catalogue entry the guard refused, in its own row. */
export function refusedEntry(reason: string): string {
  return `This entry could not be read: ${reason}.`;
}

/** Who decisions taken in this window are recorded under. */
export function recordedAs(operator: string): string {
  return `Decisions taken in this window are recorded as ${operator}`;
}

/** The theme control's sentence while the page's address fixes the theme. */
export function fixedBy(theme: "light" | "dark"): string {
  return `Fixed to ${theme} by this page's address`;
}

/** The catalogue's source, as its chip reads: the checkout, and the file inside it. */
export function catalogueSource(file: string): string {
  return `this checkout · ${file}`;
}

export const SETTINGS_COPY = {
  title: "Settings",
  lede:
    "How physgate is set up: the engines it offers, what each run recorded, and how this app " +
    "looks. Nothing here changes a run.",

  // Engines
  enginesTitle: "Engines",
  enginesLead: "The engines the desktop app's engine step offers, as this checkout lists them.",
  catalogueDigest: "Digest",
  catalogueSize: "Size",
  models: "Models",
  defaultBuilderMark: "default builder",
  defaultReviewerMark: "default reviewer",
  noStatus: "No status listed",
  localModels: "Local models offered later",
  localModelsTable: "Local models",
  columnModel: "Model",
  columnMemory: "Memory, approximate",
  columnDisk: "Disk, approximate",
  columnLicence: "Licence",
  columnSource: "Source",
  engineChosenWhere:
    "In the desktop app, the engine is chosen in its engine step: physgate menu → Engine…. " +
    "Runs still use the credential and models their own parameters name.",
  enginesLoading: "the engines this checkout lists",
  enginesEmpty: "This checkout lists no engines.",
  enginesError: "The engine catalogue could not be read.",

  // Defaults for new runs
  defaultsTitle: "Defaults for new runs",
  defaultsLead:
    "physgate keeps no defaults yet. Each run names these in its own parameters, and a run's " +
    "recorded values are below.",
  rowEngine: "Engine",
  rowBuilder: "Builder model",
  rowReviewer: "Reviewer model",
  rowGateMode: "Gate mode",
  noDefaultKept: "No default kept",
  reviewerMustDiffer: "must differ from the builder model",
  noEngineToChoose: "This checkout lists no engine that can be chosen.",
  tokens: "tokens",
  defaultEngine:
    "Chosen in the desktop app's engine step today, as a record for later. A default kept here " +
    "is coming.",
  defaultBuilder:
    "Each run names its builder models in its parameters. A default kept here is coming.",
  defaultReviewer:
    "Each run names its reviewer models in its parameters. A reviewer never runs on its " +
    "builder's model: the harness refuses it when the reviewer starts.",
  defaultGateMode: "Each run names its gate mode in its parameters. A default kept here is coming.",
  defaultTokenCeiling:
    "Each run names this ceiling in its parameters. A default kept here is coming.",

  // System, as the run recorded it
  systemTitle: "System, as the run recorded it",
  systemLoading: "the run's recorded configuration",
  runListLoading: "the run list",
  runListError: "The run list could not be read.",
  systemEmpty: "No run yet",
  systemEmptyBody: "A run's recorded system appears here once one exists.",
  systemError: "The run's recorded configuration could not be read.",
  notRecorded: "not recorded by this run",
  engineGroup: "Engine",
  credential: "Credential",
  endpoint: "Endpoint",
  endpointDefault: "the engine's own",
  claudeVersion: "Claude Code version",
  effort: "Effort",
  outputLimit: "Output limit per request",
  thinking: "Reasoning in transcripts",
  git: "Git used by the harness",
  python: "Python for role sessions",
  pythonNone: "none named",
  resolvesTo: "resolves to",
  engineItself: "The engine",
  pairsTitle: "Who built and who reviewed",
  pairsNote:
    "A reviewer runs on a different model from what it reviews. The harness checks this when " +
    "each reviewer starts, and also refuses two spellings of one model.",
  columnRole: "Role",
  columnBuilder: "Builder model",
  columnReviewer: "Reviewer model",
  columnPair: "The two strings",
  decomposition: "Splitting the brief",
  noReviewer: "No reviewer pinned for this role",
  noPlanReviewer: "No plan reviewer pinned",
  unknownReviewerKey: "no role of this run has this name",
  nothingToCompare: "nothing to compare",
  gateGroup: "Gate and queue",
  gateMode: "Gate mode",
  observeMeans: "what observe means",
  planReview: "Plan review",
  queueDecisions: "Queue decisions",
  escalation: "Escalation backend (by its register name)",
  osLayerGroup: "OS layer and network",
  osLayer: "OS layer",
  withoutLayer: "Without the OS layer",
  network: "Network for role sessions' shells",
  limitsGroup: "Session limits",
  tokenCeiling: "What each session loads at start, at most",
  wallClock: "Wall clock per session",
  turns: "Turns per session",
  retries: "Retries by the binary",
  delays: "Delays between infrastructure retries",
  noDelays: "none",
  reportable: "Reportable",
  reportableYes: "Yes: its numbers may be reported",
  reportableNo: "No: its numbers are not for reporting",
  fullRecord: "The run's full record is in Run records.",

  // Who decides here
  whoTitle: "Who decides here",
  canDecide: "This window can decide.",
  cannotDecide: "This window was opened without the operator's address, so it can only read.",
  noOperator: "This window is read-only: the server was started without an operator.",
  operatorWhere: "In the desktop app: physgate menu → Operator Name…",

  // Appearance
  appearanceTitle: "Appearance",
  theme: "Theme",
  density: "Density",
  keptHere: "Kept in this browser only. Nothing is recorded.",
} as const;
