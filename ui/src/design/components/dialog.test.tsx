// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ActButton } from "./Buttons";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function mount(onConfirm: () => void, reject = false) {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  act(() => {
    root.render(
      <ActButton
        act={{ label: "Approve", writes: "one decision line in queue_decisions.jsonl", onConfirm }}
        reject={reject}
      />,
    );
  });
  const trigger = host.querySelector("button");
  const dialog = host.querySelector("dialog");
  if (trigger === null || dialog === null) throw new Error("the button did not render");
  return { host, root, trigger, dialog };
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("acting goes through a confirmation that names what gets written", () => {
  it("a click opens the confirmation and writes nothing", () => {
    const onConfirm = vi.fn();
    const { trigger, dialog } = mount(onConfirm);
    act(() => {
      trigger.click();
    });
    expect(dialog.open).toBe(true);
    expect(dialog.textContent).toContain("This writes: one decision line in queue_decisions.jsonl");
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("cancel closes it, writes nothing, and gives focus back to the button", () => {
    const onConfirm = vi.fn();
    const { trigger, dialog } = mount(onConfirm);
    act(() => {
      trigger.click();
    });
    const cancel = [...dialog.querySelectorAll("button")].find((b) => b.textContent === "Cancel");
    act(() => {
      cancel?.click();
    });
    expect(dialog.open).toBe(false);
    expect(onConfirm).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(trigger);
  });

  it("confirming acts exactly once", () => {
    const onConfirm = vi.fn();
    const { trigger, dialog } = mount(onConfirm);
    act(() => {
      trigger.click();
    });
    const confirm = [...dialog.querySelectorAll("button")].find((b) => b.textContent === "Approve");
    act(() => {
      confirm?.click();
    });
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(dialog.open).toBe(false);
  });

  it("an act button is solid with a leading glyph; reject is a red outline", () => {
    expect(mount(vi.fn()).trigger.className).toContain("button-act");
    const rejecting = mount(vi.fn(), true).trigger;
    expect(rejecting.className).toContain("button-reject");
    expect(rejecting.textContent).toContain("✕");
  });
});
