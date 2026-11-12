// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SOURCES } from "../../api/queue";
import { CHECK_NAMES } from "../../api/run";
import { GLOSSARY, GLOSSARY_GROUPS } from "../../design/components/help/glossary";
import { CHECK_WORDS } from "../../words/checks";
import { bannedIn, DECISION_COPY, SOURCE_WORDS } from "../../words/queue";
import Glossary from "./Glossary";

const html = renderToStaticMarkup(
  <Glossary setHeader={() => undefined} query={new URLSearchParams()} />,
);

describe("the glossary", () => {
  it("lists every term in the one table, in six groups", () => {
    expect(GLOSSARY_GROUPS).toHaveLength(6);
    for (const group of GLOSSARY_GROUPS) expect(html).toContain(`aria-label="${group}"`);
    for (const entry of Object.values(GLOSSARY)) expect(html).toContain(entry.term);
  });

  it("lists every gate check and every reason the queue asks, from their own tables", () => {
    // The markup escapes apostrophes; the sentences are compared as a person reads them.
    const text = html.replaceAll("&#x27;", "'").replaceAll("&quot;", '"');
    for (const name of CHECK_NAMES) {
      expect(text).toContain(`<dt>${CHECK_WORDS[name].name}</dt>`);
      expect(text).toContain(CHECK_WORDS[name].explains);
    }
    for (const source of SOURCES) {
      expect(text).toContain(`<dt>${SOURCE_WORDS[source].kind}</dt>`);
      expect(text).toContain(SOURCE_WORDS[source].why);
    }
  });

  it("holds every harness term the screens explain", () => {
    for (const key of [
      "gate",
      "observe",
      "unchecked",
      "attempt",
      "repair",
      "safe-point",
      "sealed",
      "partial",
      "actor",
      "queue-item",
      "digest",
      "seed",
      "manifest",
    ] as const)
      expect(GLOSSARY[key].means.length).toBeGreaterThan(10);
  });

  it("explains every term the Simulation screen uses, and says a record is not re-run", () => {
    for (const key of [
      "simulation-record",
      "read-off",
      "agreement",
      "set-aside",
      "superseded",
      "tool-view",
      "sealed",
      "attempt",
      "unchecked",
      "observe",
    ] as const)
      expect(GLOSSARY[key].means.length).toBeGreaterThan(10);
    expect(GLOSSARY["simulation-record"].means).toMatch(/does not re-run/);
    expect(GLOSSARY.agreement.means).not.toMatch(/\d/);
    expect(html).toContain("Simulation record");
  });

  it("explains every library term the library screen uses", () => {
    const library = Object.values(GLOSSARY).filter((e) => e.group === "The library");
    expect(library.map((e) => e.term)).toEqual([
      "Library",
      "Promotion",
      "Proposed change",
      "Standards file",
      "Skill file",
      "Antipattern",
      "Reviewer rubric",
      "Bounds table",
      "Data-sheet rating",
    ]);
    for (const entry of library) expect(entry.means.length).toBeGreaterThan(10);
    expect(html).toContain('aria-label="The library"');
  });

  it("says promotion is a person's act and that bounds tables are not promoted", () => {
    const means = (term: string) =>
      Object.values(GLOSSARY).find((e) => e.term === term)?.means ?? "";
    expect(means("Promotion")).toMatch(/person/);
    expect(means("Promotion")).toMatch(/terminal/);
    expect(means("Bounds table")).toMatch(/not promoted/);
    expect(means("Reviewer rubric")).toMatch(/only reviewers read/i);
  });

  it("says warn is a failed check whose failure does not block the attempt, as the gate records it", () => {
    expect(GLOSSARY.verdicts.means).toContain(
      "Warn is a check that failed where its failure does not block the attempt.",
    );
    expect(GLOSSARY.verdicts.means).not.toMatch(/close to a bound|passes but/);
  });

  it("says a queue item's decision is recorded and does not restart the subtask", () => {
    expect(GLOSSARY["queue-item"].means).toBe(DECISION_COPY.queueItem);
    expect(html).toContain("it does not restart the subtask unless the item says");
    expect(bannedIn(html)).toEqual([]);
  });
});
