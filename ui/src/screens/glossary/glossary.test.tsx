// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { GLOSSARY, GLOSSARY_GROUPS } from "../../design/components/help/glossary";
import { bannedIn, DECISION_COPY } from "../../words/queue";
import Glossary from "./Glossary";

const html = renderToStaticMarkup(
  <Glossary setHeader={() => undefined} query={new URLSearchParams()} />,
);

describe("the glossary", () => {
  it("lists every term in the one table, in five groups", () => {
    expect(GLOSSARY_GROUPS).toHaveLength(5);
    for (const group of GLOSSARY_GROUPS) expect(html).toContain(`aria-label="${group}"`);
    for (const entry of Object.values(GLOSSARY)) expect(html).toContain(entry.term);
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

  it("says a queue item's decision is recorded and does not restart the subtask", () => {
    expect(GLOSSARY["queue-item"].means).toBe(DECISION_COPY.queueItem);
    expect(html).toContain("it does not restart the subtask");
    expect(bannedIn(html)).toEqual([]);
  });
});
