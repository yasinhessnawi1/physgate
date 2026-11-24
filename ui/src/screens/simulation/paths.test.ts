import { describe, expect, it } from "vitest";

import { shownPath, withoutAbsolutePaths } from "./paths";

describe("a path of the machine that recorded", () => {
  it("is shown as a label and the file's own name, never with a home folder or an account name", () => {
    expect(shownPath("/Users/someone-private/toolenv/env-1/lib/python3.12/os.py")).toBe(
      "<outside the run>/os.py",
    );
    expect(shownPath("C:\\Users\\someone-private\\env\\os.py")).toBe("<outside the run>/os.py");
  });

  it("leaves a path that is already relative to the run as it is", () => {
    expect(shownPath("modules/control/margins.py")).toBe("modules/control/margins.py");
  });

  it("is replaced inside a sentence, and nothing else of the sentence changes", () => {
    expect(
      withoutAbsolutePaths(
        "ran from a path that is not plain: /Users/someone-private/env/os.py, and left by /opt/x/y.json.",
      ),
    ).toBe(
      "ran from a path that is not plain: <outside the run>/os.py, and left by <outside the run>/y.json.",
    );
  });

  it("does not take a unit, a fraction or a relative path for one", () => {
    const words = "speed in m/s**2 and kg*m**2, 1/2 of series/s1/3/sess/edge_01.json at 5 m/s";
    expect(withoutAbsolutePaths(words)).toBe(words);
  });
});
