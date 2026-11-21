// @vitest-environment happy-dom
/**
 * A long hash reads short, its first characters, with the whole value one keypress away and
 * copied whole.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { Id } from "./Id";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const HASH = "f5803efd773199de013be6a068f24d863957eba693d44d69fca63f3e92e4d7ea";

let root: Root | null = null;
afterEach(() => {
  act(() => {
    root?.unmount();
  });
  root = null;
  document.body.replaceChildren();
});

function mount(): HTMLElement {
  const host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  act(() => {
    root?.render(<Id value={HASH} short={8} />);
  });
  return host;
}

describe("a long hash reads short, whole on demand", () => {
  it("shows its first eight characters, and copies the whole value", () => {
    const host = mount();
    const shown = host.querySelector(".pg-id");
    expect(shown?.textContent).toBe("f5803efd…");
    expect(host.querySelector(".pg-id-copy")?.getAttribute("aria-label")).toBe(`Copy ${HASH}`);
  });

  it("a button shows the whole value, and hides it again", () => {
    const host = mount();
    const toggle = host.querySelector<HTMLButtonElement>("button.pg-id-whole");
    expect(toggle?.getAttribute("aria-expanded")).toBe("false");
    act(() => {
      toggle?.click();
    });
    expect(host.querySelector(".pg-id")?.textContent).toBe(HASH);
    expect(toggle?.getAttribute("aria-expanded")).toBe("true");
  });

  it("an id as short as the cut is shown whole, with nothing to open", () => {
    const host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
    act(() => {
      root?.render(<Id value="a2-g11" short={8} />);
    });
    expect(host.querySelector(".pg-id")?.textContent).toBe("a2-g11");
    expect(host.querySelector("button.pg-id-whole")).toBeNull();
  });
});

describe("each toggle names what it shows whole", () => {
  it("its accessible name names the id, open and closed", () => {
    const host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
    act(() => {
      root?.render(<Id value={HASH} short={8} name="manifest id" />);
    });
    const toggle = host.querySelector<HTMLButtonElement>("button.pg-id-whole");
    expect(toggle?.getAttribute("aria-label")).toBe("Show whole manifest id");
    expect(toggle?.textContent).toBe("Show whole");
    act(() => {
      toggle?.click();
    });
    expect(toggle?.getAttribute("aria-label")).toBe("Show less of the manifest id");
  });
});
