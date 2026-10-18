// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { namesACommand } from "../../rules/commands";
import { NoRunsYet } from "./NoRunsYet";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const roots: Root[] = [];

afterEach(() => {
  act(() => {
    for (const root of roots.splice(0)) root.unmount();
  });
  document.body.innerHTML = "";
});

function mount() {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  roots.push(root);
  act(() => {
    root.render(<NoRunsYet />);
  });
  return host;
}

describe("Home with no run yet", () => {
  it("leads with starting a project, drawn disabled and said to be coming", () => {
    const host = mount();
    const state = host.querySelector(".pg-state-empty");
    expect(state?.getAttribute("aria-label")).toBe("No runs yet");
    const buttons = [...host.querySelectorAll("button")];
    expect(buttons).toHaveLength(1);
    const start = buttons[0];
    expect(start?.textContent).toBe("Start a project");
    expect(start?.disabled).toBe(true);
    // The first control of the empty state, and what says it is coming is tied to it.
    const said = document.getElementById(start?.getAttribute("aria-describedby") ?? "");
    expect(said?.textContent).toBe("Coming soon");
    expect(host.textContent).toContain("Starting a project from the app is coming soon.");
  });

  it("names no terminal command", () => {
    const host = mount();
    expect(namesACommand(host.textContent)).toBe(false);
    expect(host.querySelector("code, pre, kbd")).toBeNull();
  });
});
