// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";

import { runConfig, runListing } from "../../../api/records";
import { type OsLayer, OsLayerBadge } from "./OsLayerBadge";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function shown(layer: OsLayer | null): HTMLElement {
  const host = document.createElement("div");
  const root = createRoot(host);
  act(() => {
    root.render(<OsLayerBadge layer={layer} />);
  });
  const badge = host.querySelector<HTMLElement>(".pg-os-layer");
  if (badge === null) throw new Error("no badge");
  return badge;
}

describe("a run says whether its sessions ran inside the OS layer", () => {
  it("names the mechanism when present", () => {
    expect(shown({ state: "present", mechanism: "seatbelt" }).textContent).toContain(
      "OS layer · Seatbelt",
    );
  });

  it("says absent, with the reason, when absent", () => {
    const badge = shown({ state: "absent", reason: "bwrap missing", noOsProtection: false });
    expect(badge.textContent).toContain("OS layer absent");
    expect(badge.getAttribute("aria-label")).toContain("bwrap missing");
  });

  it("says there is no OS protection on native Windows", () => {
    const badge = shown({ state: "absent", reason: "native Windows", noOsProtection: true });
    expect(badge.textContent).toContain("No OS protection");
  });

  it("never reads an unrecorded state as present", () => {
    const badge = shown(null);
    expect(badge.textContent).toBe("OS layer not recorded");
    expect(badge.textContent).not.toContain("Seatbelt");
  });
});

describe("the records carry the state the run recorded", () => {
  const config = {
    run_id: "r",
    gate_mode: "on",
    harness: { commit: null },
    auth: "api_key",
    brief_sha256: "a".repeat(64),
    seed: 1,
    models: { roles: {} },
  };

  it("reads each state, and an older run's missing field as not recorded", () => {
    const present = { state: "present", mechanism: "bubblewrap", claude_version: "2.1.301" };
    expect(
      runConfig({ manifest_id: "m", config: { ...config, os_layer: present } }).osLayer,
    ).toEqual({ state: "present", mechanism: "bubblewrap" });
    const absent = { state: "absent", reason: "no bwrap", no_os_protection: false };
    expect(
      runConfig({ manifest_id: "m", config: { ...config, os_layer: absent } }).osLayer,
    ).toEqual({ state: "absent", reason: "no bwrap", noOsProtection: false });
    expect(runConfig({ manifest_id: "m", config }).osLayer).toBeNull();
  });

  it("refuses a state it does not know", () => {
    const odd = { state: "maybe" };
    expect(() => runConfig({ manifest_id: "m", config: { ...config, os_layer: odd } })).toThrow();
  });

  it("lists each run's state", () => {
    const listed = runListing({
      runs: [
        { root: 0, name: "a", run_id: "a", manifest_id: "m", gate_mode: "on", os_layer: null },
      ],
    });
    expect(listed[0]?.osLayer).toBeNull();
  });
});
