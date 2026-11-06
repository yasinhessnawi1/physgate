// @vitest-environment happy-dom
/**
 * The Queue screen over a run's answers as the server's routes send them: a failed contract's
 * open item, its positions' keys sorted by the route, is shown with a way to choose each; and a
 * listing the page refuses is shown as refused, never as a read that does not end.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import contractItem from "../../api/served/item-contract.json";
import reviewItem from "../../api/served/item-review-unavailable.json";
import contractOpen from "../../api/served/queue-contract-open.json";
import status from "../../api/served/status.json";
import Queue from "./Queue";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const BASE = "/api/runs/0/run-7";

/** The decided firmware item at position 1: the first item's view, renamed. */
function firmwareItem(): unknown {
  const view = structuredClone(reviewItem);
  view.position = 1;
  view.item.item_id = "run-7-firmware-a7cd7e";
  view.item.subtask_id = "firmware-a7cd7e";
  return view;
}

function answers(listing: unknown): Record<string, unknown> {
  return {
    "/api/runs": {
      runs: [{ root: 0, name: "run-7", run_id: "run-7", manifest_id: "m", gate_mode: "on" }],
    },
    [`${BASE}/config`]: {
      manifest_id: "m",
      config: {
        run_id: "run-7",
        gate_mode: "on",
        harness: { commit: null },
        auth: "subscription",
        brief_sha256: "b",
        seed: 1,
        models: { roles: {}, decomposition: null },
      },
    },
    [`${BASE}/status`]: status,
    [`${BASE}/queue`]: listing,
    [`${BASE}/queue/items/0`]: reviewItem,
    [`${BASE}/queue/items/1`]: firmwareItem(),
    [`${BASE}/queue/items/2`]: contractItem,
  };
}

let root: Root | null = null;

afterEach(() => {
  act(() => {
    root?.unmount();
  });
  root = null;
  document.body.innerHTML = "";
  vi.restoreAllMocks();
});

async function mounted(listing: unknown, query = ""): Promise<HTMLElement> {
  const served = answers(listing);
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = typeof input === "string" ? input : (input as Request).url;
    if (url === `${BASE}/events`) return Promise.resolve(new Response(""));
    return Promise.resolve(new Response(JSON.stringify(served[url]), { status: 200 }));
  });
  const host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  act(() => {
    root?.render(<Queue setHeader={vi.fn()} query={new URLSearchParams(query)} />);
  });
  for (let i = 0; i < 12; i += 1)
    await act(async () => {
      await Promise.resolve();
    });
  return host;
}

describe("a failed contract's open item, as the route sends it", () => {
  it("is shown, with a way to choose the producer's work and the consumer's", async () => {
    const host = await mounted(contractOpen, "item=run-7-contract-4");
    expect(host.textContent).not.toContain("could not be read");
    const labels = [...host.querySelectorAll(".pg-queue-actions button")].map((b) => b.textContent);
    expect(labels.filter((l) => l.startsWith("Choose"))).toHaveLength(2);
    expect(host.querySelector(".pg-queue-entry-on")?.getAttribute("href")).toContain(
      "item=run-7-contract-4",
    );
  });
});

describe("a listing the page refuses", () => {
  it("is shown as refused, with the reason, not as a read that never ends", async () => {
    const refused = structuredClone(contractOpen) as { open: { source: string }[] };
    const first = refused.open[0];
    if (first !== undefined) first.source = "not_a_source";
    const host = await mounted(refused);
    expect(host.textContent).not.toContain("Reading the queue");
    expect(host.textContent).toContain("The queue could not be read");
    expect(host.textContent).toContain("a queue source");
  });
});
