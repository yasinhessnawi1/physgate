import { describe, expect, it } from "vitest";

import { BareNumberError } from "../design/quantity";
import { ShapeError } from "./client";
import {
  candidateDetail,
  candidateRoute,
  fileRoute,
  libraryFile,
  libraryListing,
  ratings,
  stagedList,
} from "./library";

const DIGEST = "c".repeat(64);
const OTHER = "d".repeat(64);

const line = (extra: Record<string, unknown> = {}) => ({
  candidate_id: "abc",
  kind: "standards",
  domain: "control",
  episode_id: "episode-1",
  destination: "knowledge/control/standards.md",
  promoted_by: "yasin",
  promoted: "2026-10-21T15:07:08Z",
  sha256: DIGEST,
  ...extra,
});

const LISTING = {
  library: "/tmp/x/knowledge",
  documents: [
    {
      kind: "standards",
      role: "control",
      path: "knowledge/control/standards.md",
      size: 52,
      sha256: DIGEST,
      promotion: line(),
      state: "matches",
    },
    {
      kind: "skill",
      role: "electrical",
      path: "knowledge/electrical/skill.md",
      error: "a link inside the library is not read, so where it points is never shown",
    },
    {
      kind: "standards",
      role: "laws",
      path: "knowledge/laws/standards.md",
      size: 3,
      sha256: OTHER,
      promotion: null,
      state: "never-promoted",
    },
  ],
  rubrics: [
    {
      role: "control",
      path: "knowledge/reviewers/control/rubric.md",
      promotions: [line({ kind: "rubric", sha256: undefined })],
    },
  ],
  promotions: 10,
  staged: 4,
};

describe("the listing", () => {
  it("is read whole: documents, a row's own error, rubrics and the counts", () => {
    const read = libraryListing(LISTING);
    expect(read.library).toBe("/tmp/x/knowledge");
    expect(read.promotions).toBe(10);
    expect(read.staged).toBe(4);
    expect(read.documents).toHaveLength(3);
    const [first, refused, unknown] = read.documents;
    expect(first).toEqual({
      kind: "standards",
      role: "control",
      path: "knowledge/control/standards.md",
      error: null,
      size: 52,
      sha256: DIGEST,
      state: "matches",
      promotion: {
        candidateId: "abc",
        kind: "standards",
        domain: "control",
        episodeId: "episode-1",
        destination: "knowledge/control/standards.md",
        promotedBy: "yasin",
        promoted: "2026-10-21T15:07:08Z",
        sha256: DIGEST,
        replaces: false,
      },
    });
    expect(refused).toEqual({
      kind: "skill",
      role: "electrical",
      path: "knowledge/electrical/skill.md",
      error: "a link inside the library is not read, so where it points is never shown",
    });
    expect(unknown?.role).toBe("laws");
    expect(read.rubrics[0]?.promotions[0]?.sha256).toBeNull();
    expect(read.rubrics[0]?.role).toBe("control");
  });

  it("keeps a line of a kind it does not know, as written", () => {
    const read = libraryListing({
      ...LISTING,
      documents: [
        {
          ...LISTING.documents[0],
          promotion: line({ kind: "law", promoted_by: 7, replaces: true }),
        },
      ],
    });
    const doc = read.documents[0];
    expect(doc?.error).toBeNull();
    if (doc === undefined || doc.error !== null) return;
    expect(doc.promotion?.kind).toBe("law");
    expect(doc.promotion?.promotedBy).toBe("7");
    expect(doc.promotion?.replaces).toBe(true);
  });

  it("refuses a state the server never sends, a size that is not a count, and a short digest", () => {
    const with_ = (over: Record<string, unknown>) => ({
      ...LISTING,
      documents: [{ ...LISTING.documents[0], ...over }],
    });
    expect(() => libraryListing(with_({ state: "promoted" }))).toThrow(ShapeError);
    expect(() => libraryListing(with_({ size: -1 }))).toThrow(ShapeError);
    expect(() => libraryListing(with_({ size: 1.5 }))).toThrow(ShapeError);
    expect(() => libraryListing(with_({ sha256: "abc" }))).toThrow(ShapeError);
    expect(() => libraryListing({ ...LISTING, documents: "none" })).toThrow(ShapeError);
    expect(() => libraryListing({ ...LISTING, staged: "4" })).toThrow(ShapeError);
    expect(() => libraryListing(null)).toThrow(ShapeError);
  });
});

describe("one library file", () => {
  const FILE = {
    kind: "standards",
    role: "control",
    path: "knowledge/control/standards.md",
    size: 52,
    sha256: DIGEST,
    text: "# Control standards\n\n<b>not markup</b>\n",
    promotions: [line({ sha256: OTHER }), line()],
    wrote: 1,
    state: "matches",
  };

  it("is read with its text and every line naming it, the one that wrote it by index", () => {
    const read = libraryFile(FILE);
    expect(read.text).toBe(FILE.text);
    expect(read.promotions.map((p) => p.sha256)).toEqual([OTHER, DIGEST]);
    expect(read.wrote).toBe(1);
    expect(libraryFile({ ...FILE, wrote: null, state: "differs" }).wrote).toBeNull();
  });

  it("refuses an index outside the history", () => {
    expect(() => libraryFile({ ...FILE, wrote: 2 })).toThrow(ShapeError);
    expect(() => libraryFile({ ...FILE, wrote: -1 })).toThrow(ShapeError);
    expect(() => libraryFile({ ...FILE, text: 3 })).toThrow(ShapeError);
  });
});

describe("the staged candidates", () => {
  it("lists each, and a row it could not read keeps its own error", () => {
    const read = stagedList({
      candidates: [
        {
          name: "cand-1.json",
          kind: "skill",
          candidate_id: "cand-1",
          role: "control",
          episode_id: "episode-7",
          written: "2026-11-01T10:00:00Z",
          replaces: true,
          destination: "knowledge/control/skill.md",
          size: 300,
          sha256: DIGEST,
        },
        { name: "bad name.json", kind: "standards", error: "the file is not named" },
      ],
    });
    expect(read).toEqual([
      {
        name: "cand-1.json",
        kind: "skill",
        error: null,
        candidateId: "cand-1",
        role: "control",
        episodeId: "episode-7",
        written: "2026-11-01T10:00:00Z",
        replaces: true,
        destination: "knowledge/control/skill.md",
        size: 300,
        sha256: DIGEST,
      },
      { name: "bad name.json", kind: "standards", error: "the file is not named" },
    ]);
  });

  it("refuses a row that names no file", () => {
    expect(() => stagedList({ candidates: [{ kind: "skill", error: "x" }] })).toThrow(ShapeError);
  });
});

describe("one candidate", () => {
  const DETAIL = {
    candidate: {
      kind: "skill",
      domain: "control",
      content: "A pattern.\n",
      episode_id: "episode-7",
      candidate_id: "cand-1",
      written: "2026-11-01T10:00:00Z",
      replaces: false,
    },
    kind: "skill",
    destination: "knowledge/control/skill.md",
    effect: "adds to",
    now: { size: 10, sha256: DIGEST },
    after: { size: 22, sha256: OTHER },
    lines: ["--- a", "+++ a", "@@ -1 +1,2 @@", " x", "+A pattern."],
  };

  it("is read with its effect, its fingerprints and its changed lines", () => {
    const read = candidateDetail(DETAIL);
    expect(read.effect).toBe("adds to");
    expect(read.now).toEqual({ size: 10, sha256: DIGEST });
    expect(read.after).toEqual({ size: 22, sha256: OTHER });
    expect(read.lines).toHaveLength(5);
    expect(read.candidate.candidateId).toBe("cand-1");
    expect(read.candidate.domain).toBe("control");
    expect(candidateDetail({ ...DETAIL, now: null, effect: "creates" }).now).toBeNull();
  });

  it("refuses an effect it cannot name", () => {
    expect(() => candidateDetail({ ...DETAIL, effect: "deletes" })).toThrow(ShapeError);
    expect(() => candidateDetail({ ...DETAIL, lines: [1] })).toThrow(ShapeError);
  });
});

describe("the ratings", () => {
  const RATINGS = {
    tables: [
      {
        domain: "electrical",
        path: "knowledge/electrical/bounds.toml",
        sha256: DIGEST,
        ranges: [
          {
            quantity: "sample_rate",
            kind: "frequency",
            low: { value: 0.78, unit: "Hz" },
            high: { value: 32000, unit: "Hz" },
            class: "a class",
            source: "a source",
            retrieved: "2026-10-19",
            confirmed: "2026-10-19",
            note: "a note",
          },
        ],
        envelopes: [
          {
            kind: "voltage",
            low: { value: 0, unit: "V" },
            high: { value: 60, unit: "V" },
            class: "every voltage",
            source: "a source",
            retrieved: "2026-10-20",
            confirmed: "2026-10-20",
            note: "",
          },
        ],
      },
    ],
    store_classes: [
      {
        name: "lithium-polymer hobby pack",
        fastest_discharge: { value: 150, unit: "1/h" },
        source: "a maker's sheet",
        confirmed: "2026-10-12",
      },
    ],
    catalogue_digest: OTHER,
  };

  it("keeps every value with its unit, unrounded", () => {
    const read = ratings(RATINGS);
    const range = read.tables[0]?.ranges[0];
    expect(range?.key).toBe("sample_rate");
    expect(range?.kind).toBe("frequency");
    expect(range?.low).toEqual({ value: 0.78, unit: "Hz" });
    expect(range?.high).toEqual({ value: 32000, unit: "Hz" });
    expect(range?.componentClass).toBe("a class");
    const envelope = read.tables[0]?.envelopes[0];
    expect(envelope?.key).toBe("voltage");
    expect(envelope?.kind).toBe("voltage");
    expect(read.storeClasses[0]?.fastestDischarge).toEqual({ value: 150, unit: "1/h" });
    expect(read.catalogueDigest).toBe(OTHER);
  });

  it("refuses a bare number where a quantity belongs", () => {
    const bare = structuredClone(RATINGS) as unknown as {
      tables: { ranges: { low: unknown }[] }[];
    };
    const range = bare.tables[0]?.ranges[0];
    if (range !== undefined) range.low = 0.78;
    expect(() => ratings(bare)).toThrow(BareNumberError);
  });
});

describe("the routes", () => {
  it("are built from fixed names, every part escaped", () => {
    expect(fileRoute("bounds", "electrical")).toBe("/api/library/files/bounds/electrical");
    expect(candidateRoute("cand-1")).toBe("/api/library/staged/cand-1");
    expect(candidateRoute("a/b")).toBe("/api/library/staged/a%2Fb");
  });
});
