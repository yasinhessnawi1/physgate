// @vitest-environment happy-dom
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ShapeError } from "../../api/client";
import { COMPARED } from "./answers";
import { evidenceComparison, MOST_NOTE } from "./api";
import { SideBySide } from "./Compare";

const NOTE =
  "the tier version 3f70a6d8 is marked exposed as the register reads now: it has been seen since";

function withNotes(notes: readonly string[]) {
  return { ...COMPARED, comparison: { ...COMPARED.comparison, notes } };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("what a comparison says beside its numbers", () => {
  it("shows each note it is sent, two equal ones as two, with no clash of keys", () => {
    const said = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const host = document.createElement("div");
    document.body.append(host);
    const compared = evidenceComparison(withNotes([NOTE, NOTE]));
    const root = createRoot(host);
    act(() => {
      root.render(<SideBySide compared={compared} />);
    });
    expect(host.querySelectorAll('[data-note="said"]').length).toBe(2);
    expect(said.mock.calls.map((call) => String(call[0]))).not.toContainEqual(
      expect.stringMatching(/same key/),
    );
    act(() => {
      root.unmount();
    });
    host.remove();
  });

  it("refuses a note longer than any the server writes", () => {
    expect(MOST_NOTE).toBeGreaterThanOrEqual(NOTE.length);
    expect(() => evidenceComparison(withNotes(["x".repeat(MOST_NOTE)]))).not.toThrow();
    expect(() => evidenceComparison(withNotes(["x".repeat(MOST_NOTE + 1)]))).toThrow(ShapeError);
  });
});
