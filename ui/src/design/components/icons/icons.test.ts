import { existsSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { ICON_NAMES, iconFiles, iconUrl } from "./Icon";

const DIR = fileURLToPath(new URL("../../icons/", import.meta.url));

describe("the icons are vendored with their licence and drawn from these files only", () => {
  it("names exactly the files that are there", () => {
    expect([...ICON_NAMES].sort()).toEqual(iconFiles().sort());
    expect(
      readdirSync(DIR)
        .filter((f) => f.endsWith(".svg"))
        .map((f) => f.replace(/\.svg$/, ""))
        .sort(),
    ).toEqual([...ICON_NAMES].sort());
  });

  it("keeps the licence beside them", () => {
    expect(existsSync(`${DIR}LICENSE.txt`)).toBe(true);
  });

  it("resolves every icon to a local file, never a URL elsewhere", () => {
    for (const name of ICON_NAMES) expect(iconUrl(name)).not.toMatch(/^(https?:)?\/\//);
  });
});
