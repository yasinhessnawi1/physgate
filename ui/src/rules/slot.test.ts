import { dirname, join, normalize } from "node:path";

import { describe, expect, it } from "vitest";

import { VIEWS } from "../screens/registry";
import { loadSlot, resolveSlot, slotModule, THESIS_VIEWS_ID } from "../thesisSlot";
import { files, isTest, specifiers } from "./scan";

const ALL = files();
const SHIPPED = ALL.filter((f) => !isTest(f.path) && !f.path.startsWith("rules/"));
const THESIS = SHIPPED.filter((f) => f.path.startsWith("thesis/") && /\.(ts|tsx)$/.test(f.path));
const PRODUCT = SHIPPED.filter((f) => !f.path.startsWith("thesis/") && /\.(ts|tsx)$/.test(f.path));

/**
 * What a thesis view may import from outside its folder: the product's shared layers (the API
 * client and its checks, the design system, the words, the shell's types and addresses, and the
 * one shared way a screen reads a route), and React. Never another screen, and nothing outside
 * the app's sources.
 */
const SHARED: readonly RegExp[] = [
  /^api\/(client|check|records)\.ts$/,
  /^design\/.+/,
  /^words\/.+\.ts$/,
  /^shell\/(header|route)\.ts$/,
  /^screens\/common\/read\.ts$/,
  /^screens\/registry\.ts$/,
];
const PACKAGES = ["react"];

/** Where ``spec``, imported from ``from``, lands, relative to the sources; ``null`` for a package. */
function landing(from: string, spec: string): string | null {
  if (!spec.startsWith(".")) return null;
  const target = normalize(join(dirname(from), spec));
  return /\.(ts|tsx|css)$/.test(target) ? target : `${target}.ts`;
}

describe("the thesis views arrive through the build's slot", () => {
  it("lists the Evidence screen under Analyse, beside Simulation, before Settings", () => {
    const evidence = VIEWS.filter((v) => v.slug === "evidence");
    expect(evidence.map((v) => [v.group, v.area, v.slug, v.title, v.icon])).toEqual([
      ["analyse", "home", "evidence", "Evidence", "microscope"],
    ]);
    const slugs = VIEWS.map((v) => v.slug);
    expect(slugs.indexOf("evidence")).toBe(slugs.indexOf("series") + 1);
    expect(VIEWS.at(-1)?.slug).toBe("settings");
  });

  it("is resolved to the thesis folder's list, or to none when the build has no folder", () => {
    expect(slotModule(null)).toBe("export const THESIS_VIEWS = [];\n");
    expect(slotModule("/a/src/thesis/views.ts")).toBe(
      'export { THESIS_VIEWS } from "/a/src/thesis/views.ts";\n',
    );
    const resolved = resolveSlot(THESIS_VIEWS_ID);
    expect(resolved).not.toBeNull();
    expect(resolveSlot("./thesis/views")).toBeNull();
    expect(loadSlot(resolved ?? "", null)).toBe("export const THESIS_VIEWS = [];\n");
    expect(loadSlot("virtual:physgate-tokens.css", null)).toBeNull();
  });

  it("is imported by the view registry alone among the product's files", () => {
    const importers = PRODUCT.filter((f) => specifiers(f.text).includes(THESIS_VIEWS_ID)).map(
      (f) => f.path,
    );
    expect(importers).toEqual(["screens/registry.ts"]);
  });

  it("the thesis views import nothing but each other, the shared layers and React", () => {
    expect(THESIS.length).toBeGreaterThan(5);
    const outside = THESIS.flatMap((f) =>
      specifiers(f.text)
        .filter((spec) => {
          const target = landing(f.path, spec);
          if (target === null) return !PACKAGES.includes(spec);
          if (target.startsWith("thesis/")) return false;
          return !SHARED.some((shape) => shape.test(target));
        })
        .map((spec) => `${f.path}: ${spec}`),
    );
    expect(outside).toEqual([]);
  });

  it("the thesis views send nothing but reads: no action, no method, no body", () => {
    const found = THESIS.filter((f) =>
      /postAction|method\s*:|body\s*:|XMLHttpRequest|sendBeacon/.test(f.text),
    ).map((f) => f.path);
    expect(found).toEqual([]);
  });

  it("would find an import that leaves the shared layers", () => {
    expect(landing("thesis/evidence/Spend.tsx", "../../screens/simulation/model")).toBe(
      "screens/simulation/model.ts",
    );
    expect(SHARED.some((shape) => shape.test("screens/simulation/model.ts"))).toBe(false);
    expect(landing("thesis/evidence/Spend.tsx", "node:fs")).toBeNull();
    expect(PACKAGES.includes("node:fs")).toBe(false);
  });
});
