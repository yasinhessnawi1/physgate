// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ActLabelError, Button } from "./Button";
import { ConfirmationError, ConfirmDialog } from "./ConfirmDialog";

const LooseButton = Button as unknown as (props: Record<string, unknown>) => ReactNode;
const LooseConfirm = ConfirmDialog as unknown as (props: Record<string, unknown>) => ReactNode;

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function mount(
  onConfirm: (reason: string) => void,
  variant: "act" | "reject" = "act",
  needsReason = false,
) {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  act(() => {
    root.render(
      <Button
        variant={variant}
        label={variant === "act" ? "Approve…" : "Reject…"}
        confirm={{
          title: "Approve?",
          summary: "This records one decision.",
          writes: "one decision line in queue_decisions.jsonl",
          check: "the item is still as it was shown",
          outcome: "the item closes",
          recordedAs: "e2e-operator (human)",
          confirmLabel: variant === "act" ? "Approve" : "Reject",
          needsReason,
          onConfirm,
        }}
      />,
    );
  });
  const trigger = host.querySelector("button");
  const dialog = host.querySelector("dialog");
  if (trigger === null || dialog === null) throw new Error("the button did not render");
  const button = (text: string) =>
    [...dialog.querySelectorAll("button")].find((b) => b.textContent === text);
  return { host, root, trigger, dialog, button };
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

  it("shows the sentence first, the check as not written, the outcome as Then, and who", () => {
    const { trigger, dialog } = mount(vi.fn());
    act(() => {
      trigger.click();
    });
    const text = dialog.textContent;
    expect(text.indexOf("This records one decision.")).toBeLessThan(text.indexOf("This writes"));
    expect(text).toContain("Checked first, not writtenthe item is still as it was shown");
    expect(text).toContain("Thenthe item closes");
    expect(text).toContain("Recorded as e2e-operator (human)");
  });

  it("focus moves into the dialog when it opens", () => {
    const { trigger, dialog } = mount(vi.fn());
    act(() => {
      trigger.click();
    });
    expect(dialog.contains(document.activeElement)).toBe(true);
  });

  it("Tab stays inside the dialog, both ways", () => {
    const { trigger, dialog, button } = mount(vi.fn());
    act(() => {
      trigger.click();
    });
    const cancel = button("Cancel");
    const confirm = button("Approve");
    confirm?.focus();
    act(() => {
      dialog.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true }));
    });
    expect(document.activeElement).toBe(cancel);
    act(() => {
      dialog.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, bubbles: true }),
      );
    });
    expect(document.activeElement).toBe(confirm);
  });

  it("Escape cancels: it closes, writes nothing, and gives focus back", () => {
    const onConfirm = vi.fn();
    const { trigger, dialog } = mount(onConfirm);
    act(() => {
      trigger.click();
    });
    act(() => {
      dialog.dispatchEvent(new Event("cancel", { cancelable: true }));
    });
    expect(dialog.open).toBe(false);
    expect(onConfirm).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(trigger);
  });

  it("cancel closes it, writes nothing, and gives focus back to the button", () => {
    const onConfirm = vi.fn();
    const { trigger, dialog, button } = mount(onConfirm);
    act(() => {
      trigger.click();
    });
    act(() => {
      button("Cancel")?.click();
    });
    expect(dialog.open).toBe(false);
    expect(onConfirm).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(trigger);
  });

  it("confirming acts exactly once", () => {
    const onConfirm = vi.fn();
    const { trigger, dialog, button } = mount(onConfirm);
    act(() => {
      trigger.click();
    });
    act(() => {
      button("Approve")?.click();
    });
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(dialog.open).toBe(false);
  });

  it("an act button is solid with a leading icon; reject is a red outline with a cross", () => {
    const acting = mount(vi.fn()).trigger;
    expect(acting.className).toContain("pg-btn-act");
    expect(acting.firstElementChild?.getAttribute("data-icon")).toBe("check");
    expect(acting.textContent).toBe("Approve…");
    const rejecting = mount(vi.fn(), "reject").trigger;
    expect(rejecting.className).toContain("pg-btn-reject");
    expect(rejecting.firstElementChild?.getAttribute("data-icon")).toBe("x");
  });

  it("an act's label ends in '…', in the type and at run time", () => {
    const confirm = {
      title: "t",
      writes: "w",
      recordedAs: "r",
      confirmLabel: "c",
      onConfirm: () => undefined,
    };
    // @ts-expect-error an act whose label does not say it opens a confirmation.
    expect(<Button variant="act" label="Approve" confirm={confirm} />).toBeTruthy();
    expect(() =>
      renderToStaticMarkup(<LooseButton {...{ variant: "act", label: "Approve", confirm }} />),
    ).toThrow(ActLabelError);
  });

  it("a confirmation names what it writes and who it is recorded as, in the type and at run time", () => {
    const base = {
      open: false,
      title: "t",
      confirmLabel: "c",
      onCancel: () => undefined,
      onConfirm: () => undefined,
    };
    // @ts-expect-error no line written.
    expect(<ConfirmDialog {...base} recordedAs="r" />).toBeTruthy();
    // @ts-expect-error no attribution.
    expect(<ConfirmDialog {...base} writes="w" />).toBeTruthy();
    expect(() => renderToStaticMarkup(<LooseConfirm {...base} recordedAs="r" />)).toThrow(
      ConfirmationError,
    );
    expect(() => renderToStaticMarkup(<LooseConfirm {...base} writes="w" />)).toThrow(
      ConfirmationError,
    );
    expect(() =>
      renderToStaticMarkup(<ConfirmDialog {...base} writes="w" recordedAs=" " />),
    ).toThrow(ConfirmationError);
  });
});

describe("a required reason is blank exactly as the server judges it", () => {
  function typed(text: string) {
    const { trigger, dialog, button } = mount(vi.fn(), "reject", true);
    act(() => {
      trigger.click();
    });
    const field = dialog.querySelector("textarea");
    if (field === null) throw new Error("no reason field");
    // React reads a field's value through the prototype's setter, so a test types through it.
    // eslint-disable-next-line @typescript-eslint/unbound-method -- called with the field below
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
    act(() => {
      setter?.call(field, text);
      field.dispatchEvent(new Event("input", { bubbles: true }));
    });
    return button("Reject");
  }

  it("Confirm stays disabled on nothing, and on Python's whitespace", () => {
    expect(typed("")?.disabled).toBe(true);
    expect(typed(" \t\n")?.disabled).toBe(true);
    // U+001C to U+001F and U+0085: whitespace to Python, though JavaScript's trim keeps them.
    expect(typed("\u001c\u001d\u001e\u001f\u0085")?.disabled).toBe(true);
  });

  it("U+FEFF is a reason, though JavaScript's trim would call it blank; a word is a reason", () => {
    expect(typed("﻿")?.disabled).toBe(false);
    expect(typed("too hot")?.disabled).toBe(false);
  });
});
