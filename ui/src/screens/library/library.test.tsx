// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { namesACommand } from "../../rules/commands";
import { InspectorContext } from "../../shell/inspector";
import { candidateLabel, EFFECT_WORDS, LIBRARY_COPY, libraryErrorTitle } from "../../words/library";
import Library from "./Library";
import { diffRows, parseOpen, parseTab } from "./model";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const SHA = (c: string) => c.repeat(64);

/** A promotion line as the server sends it: as recorded, without its canary. */
const line = (extra: Record<string, unknown> = {}) => ({
  candidate_id: "0123456789abcdef0123456789abcdef",
  kind: "standards",
  domain: "control",
  episode_id: "episode-1",
  destination: "knowledge/control/standards.md",
  promoted_by: "Yasin Hessnawi",
  promoted: "2026-10-21T15:07:08Z",
  sha256: SHA("a"),
  ...extra,
});

const doc = (kind: string, role: string, state: string, extra: Record<string, unknown> = {}) => ({
  kind,
  role,
  path: `knowledge/${role}/${kind === "bounds" ? "bounds.toml" : `${kind}.md`}`,
  size: 52,
  sha256: SHA("a"),
  promotion: state === "matches" ? line({ domain: role }) : null,
  state,
  ...extra,
});

const LISTING = {
  library: "/tmp/fixture/knowledge",
  documents: [
    doc("standards", "control", "matches"),
    doc("skill", "control", "differs", { sha256: SHA("b") }),
    doc("standards", "cross", "never-promoted"),
    doc("bounds", "cross", "never-promoted"),
    doc("standards", "design", "matches", { promotion: line({ promoted_by: "yasin" }) }),
    doc("standards", "electrical", "no-digest"),
    doc("bounds", "electrical", "never-promoted"),
    {
      kind: "skill",
      role: "electrical",
      path: "knowledge/electrical/skill.md",
      error: "a link inside the library is not read, so where it points is never shown",
    },
    {
      kind: "standards",
      role: "firmware",
      path: "knowledge/firmware/standards.md",
      error: "the file has more than one name on disk",
    },
    doc("standards", "laws", "differs"),
    doc("standards", "sizing", "matches", { promotion: line({ promoted_by: "yasinhessnawi" }) }),
  ],
  rubrics: [
    {
      role: "control",
      path: "knowledge/reviewers/control/rubric.md",
      promotions: [
        // The first line in log order carries the later time: the latest is the last line.
        line({ kind: "rubric", promoted: "2026-10-09T12:00:00Z", sha256: SHA("e") }),
        line({ kind: "rubric", promoted: "2026-10-08T12:00:00Z", sha256: SHA("f") }),
      ],
    },
    {
      role: "sizing",
      path: "knowledge/reviewers/sizing/rubric.md",
      promotions: [line({ kind: "rubric", domain: "sizing", sha256: undefined })],
    },
  ],
  promotions: 10,
  staged: 4,
};

const staged = (
  id: string,
  kind: string,
  role: string,
  replaces = false,
  extra: Record<string, unknown> = {},
) => ({
  name: `${id}.json`,
  kind,
  candidate_id: id,
  role,
  episode_id: "episode-7",
  written: "2026-11-01T10:00:00Z",
  replaces,
  destination: `knowledge/${role}/${kind === "standards" ? "standards" : "skill"}.md`,
  size: 321,
  sha256: SHA("c"),
  ...extra,
});

const STAGED = {
  candidates: [
    staged("cand-standards-control", "standards", "control"),
    {
      name: "bad name.json",
      kind: "standards",
      error: "the file is not named as staging names a candidate",
    },
    staged("cand-skill-control", "skill", "control"),
    staged("cand-skill-replaces", "skill", "control", true),
    staged("cand-antipattern-firmware", "antipattern", "firmware"),
  ],
};

const DETAIL = {
  candidate: {
    kind: "standards",
    domain: "control",
    content: "# Control standards\n\nA new rule.\n",
    episode_id: "episode-7",
    candidate_id: "cand-standards-control",
    written: "2026-11-01T10:00:00Z",
    replaces: false,
  },
  kind: "standards",
  destination: "knowledge/control/standards.md",
  effect: "replaces whole",
  now: { size: 52, sha256: SHA("a") },
  after: { size: 34, sha256: SHA("d") },
  lines: [
    "--- knowledge/control/standards.md",
    "+++ knowledge/control/standards.md",
    "@@ -1,3 +1,3 @@",
    " # Control standards",
    " ",
    "-A loop is closed before it is tuned.",
    "+A new rule.",
  ],
};

const FILE = {
  kind: "standards",
  role: "control",
  path: "knowledge/control/standards.md",
  size: 52,
  sha256: SHA("a"),
  text: "# Control standards\n\nA loop is closed <b>before</b> it is tuned.\n",
  promotions: [
    line({ sha256: SHA("9"), promoted: "2026-10-22T05:58:48Z" }),
    line({ sha256: undefined }),
    line(),
  ],
  wrote: 2,
  state: "matches",
};

const RATINGS = {
  tables: [
    {
      domain: "cross",
      path: "knowledge/cross/bounds.toml",
      sha256: SHA("1"),
      ranges: [],
      envelopes: [
        {
          kind: "voltage",
          low: { value: 0, unit: "V" },
          high: { value: 60, unit: "V" },
          class: "every voltage on the fixture's class of machine",
          source: "A fixture source for the envelope.",
          retrieved: "2026-10-20",
          confirmed: "2026-10-20",
          note: "Fixture envelope.",
        },
      ],
    },
    {
      domain: "electrical",
      path: "knowledge/electrical/bounds.toml",
      sha256: SHA("2"),
      ranges: [
        {
          quantity: "sample_rate",
          kind: "frequency",
          low: { value: 0.78, unit: "Hz" },
          high: { value: 32000, unit: "Hz" },
          class: "a sensor's output data rate, with a class text long enough to wrap",
          source: "A fixture source, read on the date below.",
          retrieved: "2026-10-19",
          confirmed: "2026-10-19",
          note: "Fixture range.",
        },
      ],
      envelopes: [],
    },
  ],
  store_classes: [
    {
      name: "lithium-polymer hobby pack",
      fastest_discharge: { value: 150, unit: "1/h" },
      source: "A maker's sheet, as the catalogue cites it.",
      confirmed: "2026-10-12",
    },
  ],
  catalogue_digest: SHA("3"),
};

type Answer = readonly [number, unknown];

/** What the stand-in server answers, by path; a path it does not hold is a 404. */
let answers: Record<string, Answer> = {};
/** Every path asked, in order. */
let asked: string[] = [];
/** A read held open until the test lets it go. */
let held: { path: string; release: () => void } | null = null;

function serve(over: Record<string, Answer> = {}) {
  answers = {
    "/api/library": [200, LISTING],
    "/api/library/staged": [200, STAGED],
    "/api/library/staged/cand-standards-control": [200, DETAIL],
    "/api/library/files/standards/control": [200, FILE],
    "/api/library/ratings": [200, RATINGS],
    ...over,
  };
}

beforeEach(() => {
  asked = [];
  held = null;
  serve();
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string) => {
      asked.push(input);
      const [status, body] = answers[input] ?? [404, { error: "no such route" }];
      const response = () => new Response(JSON.stringify(body), { status });
      if (held?.path === input)
        return new Promise<Response>((resolve) => {
          if (held !== null)
            held.release = () => {
              resolve(response());
            };
        });
      return Promise.resolve(response());
    }),
  );
});

let root: Root | null = null;
let slot: HTMLElement | null = null;

afterEach(() => {
  // A read still held is let go, so nothing is pending once the window goes.
  held?.release();
  act(() => {
    root?.unmount();
  });
  root = null;
  slot = null;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

async function settle() {
  for (let i = 0; i < 6; i += 1)
    await act(async () => {
      await Promise.resolve();
    });
}

/** The screen at ``search``, with an inspector region of its own, read whole. */
async function mount(search = ""): Promise<HTMLElement> {
  const host = document.createElement("main");
  slot = document.createElement("aside");
  document.body.append(host, slot);
  root = createRoot(host);
  const element = slot;
  act(() => {
    root?.render(
      <InspectorContext.Provider value={{ element, setShown: () => undefined }}>
        <Library setHeader={() => undefined} query={new URLSearchParams(search)} />
      </InspectorContext.Provider>,
    );
  });
  await settle();
  return host;
}

function inspector(): HTMLElement {
  if (slot === null) throw new Error("no inspector region");
  return slot;
}

/** The first text of ``el``: what a person reads first. */
function firstText(el: Element): string {
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  let node = walker.nextNode();
  while (node !== null && (node.textContent ?? "").trim() === "") node = walker.nextNode();
  return (node?.textContent ?? "").trim();
}

/** A path, a hex digest of 7 to 64 characters, or a candidate id: never what leads. */
const AN_ID =
  /^(knowledge\/|[\w.-]+\/[\w./-]+|[0-9a-f]{7,64}\b|cand-[\w-]+|[\w-]+\.(md|toml|json)\b)/;

function rows(host: HTMLElement, table: string): HTMLTableRowElement[] {
  return [...host.querySelectorAll<HTMLTableRowElement>(`table[aria-label="${table}"] tbody tr`)];
}

const tabs = (host: HTMLElement) => [
  ...host.querySelectorAll<HTMLButtonElement>('[aria-label="Library sections"] button'),
];

describe("reading the library", () => {
  it("says it is reading, and shows nothing else until it has read", async () => {
    held = { path: "/api/library", release: () => undefined };
    const host = await mount();
    expect(host.querySelector('[aria-busy="true"]')?.textContent).toBe("Reading the library…");
    expect(host.querySelector("table")).toBeNull();
    expect(tabs(host)).toEqual([]);
  });

  it("with no library, says why in a sentence and names no command", async () => {
    serve({ "/api/library": [404, { error: "this server reads no library" }] });
    const host = await mount();
    const empty = host.querySelector(".pg-state-empty");
    expect(empty?.textContent).toContain(LIBRARY_COPY.noLibrary);
    expect(host.querySelector('[role="alert"]')).toBeNull();
    expect(host.querySelector("table")).toBeNull();
    expect(namesACommand(host.textContent)).toBe(false);
  });

  it("a refusal leads with a sentence, shows its details and nothing partial", async () => {
    serve({
      "/api/library": [
        422,
        { error: "the promotion log has a line this version cannot read", line: "7" },
      ],
    });
    const host = await mount();
    const alert = host.querySelector('[role="alert"]');
    expect(alert?.querySelector("h2")?.textContent).toBe(
      libraryErrorTitle("the promotion log has a line this version cannot read"),
    );
    expect(alert?.textContent).toContain("422");
    expect(alert?.textContent).toContain("/api/library");
    expect(alert?.textContent).toContain("line7");
    expect([...(alert?.querySelectorAll("button") ?? [])].map((b) => b.textContent)).toContain(
      "Read again",
    );
    expect(host.querySelector("table")).toBeNull();
    expect(tabs(host)).toEqual([]);
  });

  it("a refusal on another route is still the library's error, not the empty state", async () => {
    serve({ "/api/library": [404, { error: "no such file" }] });
    const host = await mount();
    expect(host.querySelector('[role="alert"]')).not.toBeNull();
    expect(host.querySelector(".pg-state-empty")).toBeNull();
  });
});

describe("the page", () => {
  it("leads with what the next run reads, counts the promotions, and lists five sections", async () => {
    const host = await mount();
    expect(host.textContent).toContain(LIBRARY_COPY.lede);
    expect(host.textContent).toContain("10 promotions recorded");
    expect(host.textContent).toContain("knowledge/promotions.jsonl");
    expect(tabs(host).map((b) => b.textContent)).toEqual([
      "Standards",
      "Skills",
      "Reviewer rubrics",
      "Proposed · 4",
      "Data-sheet ratings",
    ]);
    expect(tabs(host).map((b) => b.getAttribute("aria-pressed"))).toEqual([
      "true",
      "false",
      "false",
      "false",
      "false",
    ]);
  });

  it("calls the proposed section Proposed alone when nothing is staged", async () => {
    serve({ "/api/library": [200, { ...LISTING, staged: 0 }] });
    const host = await mount();
    expect(tabs(host)[3]?.textContent).toBe("Proposed");
  });

  it("reads only the listing for the standards", async () => {
    await mount();
    expect(asked).toEqual(["/api/library"]);
  });
});

describe("standards and skills", () => {
  it("one row per standards file, led by its label, the path under it", async () => {
    const host = await mount();
    const found = rows(host, "Standards");
    expect(found.map((r) => firstText(r))).toEqual([
      "Control standards",
      "Cross-domain standards",
      "Design standards",
      "Electrical standards",
      "Firmware standards",
      "laws standards",
      "Sizing standards",
    ]);
    for (const r of found) expect(firstText(r)).not.toMatch(AN_ID);
    expect(found[0]?.textContent).toContain("knowledge/control/standards.md");
  });

  it("shows each state as a neutral tag, never a verdict", async () => {
    const host = await mount();
    const tags = rows(host, "Standards").map(
      (r) => r.querySelector(".pg-status")?.textContent ?? "",
    );
    expect(tags).toEqual([
      "Matches its promotion",
      "Never promoted",
      "Matches its promotion",
      "No digest recorded",
      "Refused",
      "Differs from every promotion",
      "Matches its promotion",
    ]);
    expect(host.querySelector("table")?.innerHTML).not.toMatch(/pg-verdict|[✓✕]/);
  });

  it("keeps a row it could not read, with its reason as a sentence, and every other row", async () => {
    const host = await mount();
    const refused = rows(host, "Standards")[4];
    expect(firstText(refused ?? document.body)).toBe("Firmware standards");
    expect(refused?.textContent).toContain(
      "This file cannot be read here: the file has more than one name on disk.",
    );
    expect(refused?.querySelector("a")).toBeNull();
    expect(rows(host, "Standards")).toHaveLength(7);
  });

  it("names who promoted it as recorded, never merged", async () => {
    const host = await mount();
    const names = rows(host, "Standards").map(
      (r) => r.querySelector(".pg-actor-human .pg-actor-name")?.textContent ?? null,
    );
    expect(names).toEqual(["Yasin Hessnawi", null, "yasin", null, null, null, "yasinhessnawi"]);
  });

  it("gives the time a promotion was made in the viewer's zone, with UTC on hover", async () => {
    const host = await mount();
    const time = rows(host, "Standards")[0]?.querySelector("time");
    expect(time?.getAttribute("datetime")).toBe("2026-10-21T15:07:08Z");
    expect(time?.getAttribute("title")).toBe("2026-10-21 15:07:08 UTC");
  });

  it("draws a domain's chip for the schema's five domains only", async () => {
    const host = await mount();
    const chips = rows(host, "Standards").map(
      (r) => r.querySelector(".pg-domain")?.className ?? null,
    );
    expect(chips).toEqual([
      "pg-domain pg-domain-control",
      "pg-domain pg-domain-cross",
      null,
      "pg-domain pg-domain-electrical",
      "pg-domain pg-domain-firmware",
      null,
      null,
    ]);
    const sizing = rows(host, "Standards")[6];
    expect(sizing?.textContent).toContain("Sizing");
  });

  it("shows a seven-character digest, the whole one copyable", async () => {
    const host = await mount();
    const first = rows(host, "Standards")[0];
    expect(first?.querySelector(".pg-id")?.textContent).toBe("knowledge/control/standards.md");
    const digest = first?.querySelector(".pg-lib-digest");
    expect(digest?.textContent).toBe("aaaaaaa");
    expect(digest?.getAttribute("title")).toBe(SHA("a"));
    expect(first?.querySelector(`button[aria-label="Copy ${SHA("a")}"]`)).not.toBeNull();
  });

  it("opens a file from its row", async () => {
    const host = await mount();
    const open = rows(host, "Standards")[0]?.querySelector("a");
    expect(open?.getAttribute("href")).toBe("#/reference/library?open=file%3Astandards%2Fcontrol");
    expect(open?.textContent).toBe("Open Control standards");
  });

  it("lists the skills apart, a link among them kept as its own row", async () => {
    const host = await mount("tab=skills");
    const found = rows(host, "Skills");
    expect(found.map((r) => firstText(r))).toEqual(["Control skill", "Electrical skill"]);
    expect(found[0]?.textContent).toContain("Differs from every promotion");
    expect(found[1]?.textContent).toContain("This file is a link, so it is not read.");
  });

  it("says so when the library holds no skill", async () => {
    serve({
      "/api/library": [
        200,
        { ...LISTING, documents: LISTING.documents.filter((d) => d.kind !== "skill") },
      ],
    });
    const host = await mount("tab=skills");
    expect(host.querySelector(".pg-state-empty")?.textContent).toContain(LIBRARY_COPY.noSkills);
  });

  it("says so when the library holds no standards", async () => {
    serve({ "/api/library": [200, { ...LISTING, documents: [] }] });
    const host = await mount();
    expect(host.querySelector(".pg-state-empty")?.textContent).toContain(LIBRARY_COPY.noStandards);
  });
});

describe("one file, in the inspector", () => {
  it("reads the file and shows its label, its text as text, its fingerprints and its history", async () => {
    await mount("open=file:standards/control");
    expect(asked).toContain("/api/library/files/standards/control");
    const panel = inspector();
    expect(panel.querySelector(".pg-inspector-title")?.textContent).toBe("Control standards");
    const text = panel.querySelector(".pg-lib-text");
    expect(text?.textContent).toBe(FILE.text);
    expect(text?.querySelector("b")).toBeNull();
    expect(panel.querySelector('[data-fact="size"]')?.textContent).toBe("52B");
    expect(panel.textContent).toContain(SHA("a"));
  });

  it("names the file as its source, with no commit, dashed", async () => {
    await mount("open=file:standards/control");
    const chip = inspector().querySelector(".pg-source");
    expect(chip?.classList.contains("pg-source-missing")).toBe(true);
    expect(chip?.getAttribute("aria-label")).toBe(
      "Source: knowledge/control/standards.md at no commit",
    );
  });

  it("marks the line that wrote the file, and a line with no digest says so", async () => {
    await mount("open=file:standards/control");
    const entries = [...inspector().querySelectorAll(".pg-lib-history li")];
    expect(entries).toHaveLength(3);
    expect(entries[2]?.textContent).toContain(LIBRARY_COPY.wroteThisFile);
    expect(entries[0]?.textContent).not.toContain(LIBRARY_COPY.wroteThisFile);
    expect(entries[1]?.textContent).toContain(LIBRARY_COPY.noDigest);
    expect(entries[0]?.textContent).toContain("9999999");
  });

  it("moves focus into the inspector", async () => {
    await mount("open=file:standards/control");
    expect(inspector().contains(document.activeElement)).toBe(true);
  });

  it("a file it could not read is a sentence in the inspector", async () => {
    serve({
      "/api/library/files/standards/control": [
        403,
        { error: "a link inside the library is not read, so where it points is never shown" },
      ],
    });
    await mount("open=file:standards/control");
    const alert = inspector().querySelector('[role="alert"]');
    expect(alert?.querySelector("h2")?.textContent).toBe("The file could not be read.");
    expect(alert?.textContent).toContain("403");
  });
});

describe("reviewer rubrics", () => {
  it("says why the text is not shown, and lists each rubric's latest line in log order", async () => {
    const host = await mount("tab=rubrics");
    expect(host.textContent).toContain(LIBRARY_COPY.rubricsNote);
    const found = rows(host, "Reviewer rubrics");
    expect(found.map((r) => firstText(r))).toEqual([
      "Control reviewer rubric",
      "Sizing reviewer rubric",
    ]);
    // The last line in log order, not the one with the latest time.
    expect(found[0]?.querySelector(".pg-lib-digest")?.textContent).toBe("fffffff");
    expect(found[0]?.querySelector("time")?.getAttribute("datetime")).toBe("2026-10-08T12:00:00Z");
    expect(found[1]?.textContent).toContain(LIBRARY_COPY.noDigest);
    expect(found[0]?.textContent).toContain("2 promotions");
  });

  it("opens nothing and states nothing: the file's bytes are never read", async () => {
    const host = await mount("tab=rubrics");
    const table = host.querySelector('table[aria-label="Reviewer rubrics"]');
    expect(table?.querySelector("a")).toBeNull();
    expect(table?.querySelector(".pg-status")).toBeNull();
    expect(asked).toEqual(["/api/library"]);
  });
});

describe("proposed changes", () => {
  it("reads the staged list, and groups changes apart from antipatterns", async () => {
    const host = await mount("tab=proposed");
    expect(asked).toEqual(["/api/library", "/api/library/staged"]);
    expect(rows(host, "Proposed changes").map((r) => firstText(r))).toEqual([
      "Proposed change to the control standards",
      "A staged standards file",
      "Proposed addition to the control skill",
      "Proposed replacement of the control skill",
    ]);
    expect(rows(host, "Proposed antipatterns").map((r) => firstText(r))).toEqual([
      "Proposed antipattern for the firmware skill",
    ]);
  });

  it("says the written time is as the candidate states it, the ids after it", async () => {
    const host = await mount("tab=proposed");
    const first = rows(host, "Proposed changes")[0];
    expect(first?.textContent).toContain(
      "written 2026-11-01T10:00:00Z (as the candidate states it)",
    );
    expect(first?.textContent).toContain("cand-standards-control");
    expect(first?.textContent).toContain("episode-7");
    expect(first?.querySelector(".pg-quantity")?.textContent).toBe("321B");
  });

  it("keeps a candidate it could not read as its own row, with a sentence", async () => {
    const host = await mount("tab=proposed");
    const bad = rows(host, "Proposed changes")[1];
    expect(bad?.textContent).toContain(
      "This file is not named as staging names a candidate, so promotion would not find it.",
    );
    expect(bad?.textContent).toContain("bad name.json");
    expect(bad?.querySelector("a")).toBeNull();
  });

  it("says so when nothing is waiting", async () => {
    serve({ "/api/library/staged": [200, { candidates: [] }] });
    const host = await mount("tab=proposed");
    expect(host.querySelector(".pg-state-empty")?.textContent).toContain(
      LIBRARY_COPY.nothingProposed,
    );
    expect(host.querySelector("table")).toBeNull();
  });

  it("a refused staged list is a sentence, with nothing partial", async () => {
    serve({ "/api/library/staged": [403, { error: "refused here" }] });
    const host = await mount("tab=proposed");
    expect(host.querySelector('[role="alert"] h2')?.textContent).toBe(
      "The proposed changes could not be read.",
    );
    expect(host.querySelector("table")).toBeNull();
  });

  it("while it reads the staged list, says so", async () => {
    held = { path: "/api/library/staged", release: () => undefined };
    const host = await mount("tab=proposed");
    expect(host.querySelector('[aria-busy="true"]')?.textContent).toBe("Reading the library…");
  });
});

describe("one proposed change, in the inspector", () => {
  const OPEN = "tab=proposed&open=candidate:cand-standards-control";

  it("reads the candidate and says what promoting it would do", async () => {
    await mount(OPEN);
    expect(asked).toContain("/api/library/staged/cand-standards-control");
    const panel = inspector();
    expect(panel.querySelector(".pg-inspector-title")?.textContent).toBe(
      candidateLabel("standards", false, "control"),
    );
    expect(panel.textContent).toContain(EFFECT_WORDS["replaces whole"]);
    expect(panel.querySelector('[data-fact="now"] .pg-quantity')?.textContent).toBe("52B");
    expect(panel.querySelector('[data-fact="after"] .pg-quantity')?.textContent).toBe("34B");
    expect(panel.textContent).toContain(SHA("d"));
  });

  it("draws the changed lines with the accent and a strike, never red and green", async () => {
    await mount(OPEN);
    const diff = inspector().querySelector('[aria-label="Changed lines"]');
    expect(inspector().textContent).toContain(LIBRARY_COPY.changedLines);
    expect([...(diff?.querySelectorAll("ins") ?? [])].map((l) => l.textContent)).toEqual([
      "+A new rule.",
    ]);
    expect([...(diff?.querySelectorAll("del") ?? [])].map((l) => l.textContent)).toEqual([
      "-A loop is closed before it is tuned.",
    ]);
    expect(diff?.textContent).not.toContain("+++");
    expect(diff?.innerHTML).not.toMatch(/pass|fail/);
  });

  it("states promotion in words, the candidate id copyable, and offers no act", async () => {
    await mount(OPEN);
    const panel = inspector();
    expect(panel.textContent).toContain(LIBRARY_COPY.promotionBlock);
    expect(panel.querySelector('button[aria-label="Copy cand-standards-control"]')).not.toBeNull();
    const controls = [...panel.querySelectorAll("button, a")].map((b) => b.textContent);
    expect(controls.filter((t) => /promote|discard/i.test(t))).toEqual([]);
    expect(panel.querySelector(".pg-btn-act")).toBeNull();
    expect(namesACommand(panel.textContent)).toBe(false);
  });

  it("a candidate that creates its file has no file now", async () => {
    serve({
      "/api/library/staged/cand-standards-control": [
        200,
        {
          ...DETAIL,
          effect: "creates",
          now: null,
          lines: ["--- x", "+++ x", "@@ -0,0 +1 @@", "+a"],
        },
      ],
    });
    await mount(OPEN);
    expect(inspector().textContent).toContain(EFFECT_WORDS.creates);
    expect(inspector().querySelector('[data-fact="now"]')?.textContent).toContain(
      LIBRARY_COPY.noFileYet,
    );
  });

  it("moves focus into the inspector", async () => {
    await mount(OPEN);
    expect(inspector().contains(document.activeElement)).toBe(true);
  });

  it("a candidate it could not read is a sentence", async () => {
    serve({
      "/api/library/staged/cand-standards-control": [
        404,
        { error: "no candidate with this id is staged" },
      ],
    });
    await mount(OPEN);
    expect(inspector().querySelector('[role="alert"] h2')?.textContent).toBe(
      "The proposed change could not be read.",
    );
  });
});

describe("data-sheet ratings", () => {
  it("reads the ratings, each value a quantity as recorded, never rounded", async () => {
    const host = await mount("tab=ratings");
    expect(asked).toEqual(["/api/library", "/api/library/ratings"]);
    const range = rows(host, "Electrical bounds ranges")[0];
    expect(firstText(range ?? document.body)).toBe("Sample rate");
    expect([...(range?.querySelectorAll(".pg-quantity") ?? [])].map((q) => q.textContent)).toEqual([
      "0.78Hz",
      "32000Hz",
    ]);
    expect(range?.textContent).toContain(
      "a sensor's output data rate, with a class text long enough to wrap",
    );
  });

  it("every rating names its file as its source, with no commit, dashed", async () => {
    const host = await mount("tab=ratings");
    for (const table of ["Electrical bounds ranges", "Cross-domain bounds envelopes"]) {
      expect(rows(host, table).length, table).toBeGreaterThan(0);
      for (const r of rows(host, table)) {
        const chip = r.querySelector(".pg-source");
        expect(chip?.classList.contains("pg-source-missing")).toBe(true);
        expect(chip?.getAttribute("aria-label")).toMatch(
          /^Source: knowledge\/.*\/bounds\.toml at no commit$/,
        );
      }
    }
  });

  it("an envelope is a table where one is loaded, and a sentence where none is", async () => {
    const host = await mount("tab=ratings");
    expect(rows(host, "Cross-domain bounds envelopes").map((r) => firstText(r))).toEqual([
      "Voltage",
    ]);
    const electrical = host.querySelector('section[aria-label="Electrical bounds"]');
    expect(electrical?.textContent).toContain(LIBRARY_COPY.noEnvelope);
    const cross = host.querySelector('section[aria-label="Cross-domain bounds"]');
    expect(cross?.textContent).toContain(LIBRARY_COPY.noRange);
  });

  it("lists the energy store classes, rated per hour, from the gate catalogue", async () => {
    const host = await mount("tab=ratings");
    const store = rows(host, "Energy store classes")[0];
    expect(firstText(store ?? document.body)).toBe("Lithium-polymer hobby pack");
    expect(store?.querySelector(".pg-quantity")?.textContent).toBe("1501/h");
    expect(store?.querySelector(".pg-source")?.getAttribute("aria-label")).toBe(
      "Source: gate catalogue at no commit",
    );
    expect(host.textContent).toContain(SHA("3"));
  });

  it("says so when no bounds table is loaded, and still lists the store classes", async () => {
    serve({ "/api/library/ratings": [200, { ...RATINGS, tables: [] }] });
    const host = await mount("tab=ratings");
    expect(host.querySelector(".pg-state-empty")?.textContent).toContain(
      LIBRARY_COPY.noBoundsTable,
    );
    expect(rows(host, "Energy store classes")).toHaveLength(1);
  });

  it("a table that does not load is a sentence for the whole section", async () => {
    serve({ "/api/library/ratings": [422, { error: "a bounds table does not load" }] });
    const host = await mount("tab=ratings");
    expect(host.querySelector('[role="alert"] h2')?.textContent).toBe(
      "The data-sheet ratings could not be read.",
    );
    expect(host.querySelector("table")).toBeNull();
  });

  it("opens a range's whole record, with the file it comes from", async () => {
    await mount("tab=ratings&open=range:1/0");
    const panel = inspector();
    expect(panel.querySelector(".pg-inspector-title")?.textContent).toBe("Sample rate");
    for (const text of [
      "A fixture source, read on the date below.",
      "2026-10-19",
      "Fixture range.",
      "knowledge/electrical/bounds.toml",
      SHA("2"),
    ])
      expect(panel.textContent).toContain(text);
    const open = [...panel.querySelectorAll("a")].find((a) => a.textContent === "Open the file");
    expect(open?.getAttribute("href")).toBe(
      "#/reference/library?tab=ratings&open=file%3Abounds%2Felectrical",
    );
    expect(inspector().contains(document.activeElement)).toBe(true);
  });

  it("opens a store class's source", async () => {
    await mount("tab=ratings&open=store:0");
    const panel = inspector();
    expect(panel.querySelector(".pg-inspector-title")?.textContent).toBe(
      "Lithium-polymer hobby pack",
    );
    expect(panel.textContent).toContain("A maker's sheet, as the catalogue cites it.");
    expect(panel.querySelector(".pg-quantity")?.textContent).toBe("1501/h");
  });
});

describe("where the screen is lives in the address", () => {
  it("reads the section and the selection, and anything else is the default", () => {
    expect(parseTab("skills")).toBe("skills");
    expect(parseTab("ratings")).toBe("ratings");
    expect(parseTab(null)).toBe("standards");
    expect(parseTab("promote")).toBe("standards");
    expect(parseOpen("file:bounds/electrical")).toEqual({
      kind: "file",
      file: "bounds",
      role: "electrical",
    });
    expect(parseOpen("candidate:cand-1")).toEqual({ kind: "candidate", id: "cand-1" });
    expect(parseOpen("range:1/0")).toEqual({ kind: "range", table: 1, index: 0 });
    expect(parseOpen("envelope:0/2")).toEqual({ kind: "envelope", table: 0, index: 2 });
    expect(parseOpen("store:3")).toEqual({ kind: "store", index: 3 });
    for (const bad of [null, "", "file:x", "file:standards/", "range:a/0", "candidate:", "x:1"])
      expect(parseOpen(bad), String(bad)).toBeNull();
  });

  it("classifies the changed lines: headers left out, removed, added, unchanged and hunks", () => {
    expect(diffRows(DETAIL.lines)).toEqual([
      { kind: "hunk", text: "@@ -1,3 +1,3 @@" },
      { kind: "same", text: " # Control standards" },
      { kind: "same", text: " " },
      { kind: "removed", text: "-A loop is closed before it is tuned." },
      { kind: "added", text: "+A new rule." },
    ]);
    expect(diffRows([])).toEqual([]);
  });
});
