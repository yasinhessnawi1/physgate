import { describe, expect, it } from "vitest";

import { namesACommand, shownText } from "../../rules/commands";
import { files, isTest } from "../../rules/scan";

/**
 * The library screen's own sources, read as text: no control that acts, and no terminal
 * command in anything they can show. Planted strings are built at run time.
 */
describe("the screen's sources", () => {
  const OURS = files().filter(
    (f) =>
      !isTest(f.path) &&
      (f.path.startsWith("screens/library/") ||
        f.path === "words/library.ts" ||
        f.path === "api/library.ts"),
  );

  it("are found", () => {
    expect(OURS.length).toBeGreaterThan(4);
  });

  it("hold no act and no control that promotes or discards", () => {
    for (const f of OURS) {
      expect(f.text, f.path).not.toMatch(/variant=["{]+act/);
      expect(f.text, f.path).not.toMatch(/>\s*(Promote|Discard)/);
    }
  });

  it("show no terminal command", () => {
    const found = OURS.flatMap((f) =>
      shownText(f.path, f.text)
        .filter(namesACommand)
        .map((t) => `${f.path}: ${t}`),
    );
    expect(found).toEqual([]);
  });

  it("would find one planted in the promotion block", () => {
    const block = OURS.find((f) => f.path === "words/library.ts");
    expect(block).toBeDefined();
    const planted = (block?.text ?? "").replace(
      "cannot promote or discard it.",
      `cannot promote or discard it. ${["physgate", "knowledge", "promote", "x"].join(" ")}`,
    );
    expect(planted).not.toBe(block?.text);
    expect(shownText("words/library.ts", planted).some(namesACommand)).toBe(true);
  });
});
