// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Drifted } from "./Compare";

const SERVER =
  "the runs were answered under different pins, or asked different things: re-run the " +
  "baseline under the candidate's before comparing";

function shown(drifted: readonly string[]): HTMLElement {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(
    <Drifted refusal={{ status: 422, error: SERVER, context: {} }} drifted={drifted} />,
  );
  return host;
}

/** The text a visitor reads without opening anything. */
function visible(host: HTMLElement): string {
  const copy = host.cloneNode(true) as HTMLElement;
  for (const folded of copy.querySelectorAll("details")) folded.remove();
  return copy.textContent;
}

describe("the comparison's refusal says what is true for these runs", () => {
  it("two runs from different starting commits: why, in words, and what would make one possible", () => {
    const host = shown(["target_head"]);
    const text = visible(host);
    expect(host.querySelector("h2")?.textContent).toBe(
      "These two runs cannot be compared: they did not start from the same place",
    );
    expect(text).toContain("They started from different commits of the target repository");
    expect(text).toContain(
      "A comparison is possible between two runs of the same brief that start from the same " +
        "commit, with every setting the same but the one being measured",
    );
    expect(text).not.toContain("baseline");
  });

  it("the server's own sentence stays one click away, never as the advice", () => {
    const host = shown(["target_head", "max_output_tokens"]);
    expect(host.querySelector("details")?.textContent).toContain(SERVER);
    expect(visible(host)).not.toContain("re-run");
  });

  it("two runs measured on different tier versions: that reason, in words, and no file path", () => {
    const host = shown(["evaluation/tiers.json"]);
    const text = visible(host);
    expect(host.querySelector("h2")?.textContent).toBe(
      "These two runs cannot be compared: they were measured on different versions of the evaluation tasks",
    );
    expect(text).toContain(
      "A comparison is possible between two runs measured on the same version of the evaluation tasks.",
    );
    expect(text).not.toContain("evaluation/tiers.json");
    expect(text).not.toContain("same place");
    expect(text).not.toContain("started");
    expect(text).not.toContain("start from");
  });

  it("runs on different models or limits: settings, never where each started", () => {
    const host = shown(["models.decomposition", "max_output_tokens"]);
    const text = visible(host);
    expect(host.querySelector("h2")?.textContent).toBe(
      "These two runs cannot be compared: they were run with different settings",
    );
    expect(text).toContain("The model that plans the subtasks");
    expect(text).not.toContain("same place");
    expect(text).not.toContain("where each started");
    expect(text).not.toContain("different commits");
  });
});

describe("a refusal over the tier version and something else shows both", () => {
  it("tiers and the starting commit differ: the tier reason and the commit, both in words", () => {
    const host = shown(["evaluation/tiers.json", "target_head"]);
    const text = visible(host);
    const title = host.querySelector("h2")?.textContent ?? "";
    expect(title).toContain("different versions of the evaluation tasks");
    expect(title).toContain("did not start from the same place");
    expect(text).toContain(
      "Each run records the version of the evaluation tasks it was measured on.",
    );
    expect(text).toContain("They started from different commits of the target repository");
    expect(text).not.toContain("evaluation/tiers.json");
    expect(host.querySelectorAll("[data-drifted]")).toHaveLength(1);
  });

  it("tiers and a setting differ: the tier reason and the setting, both in words", () => {
    const host = shown(["evaluation/tiers.json", "models.decomposition"]);
    const text = visible(host);
    const title = host.querySelector("h2")?.textContent ?? "";
    expect(title).toContain("different versions of the evaluation tasks");
    expect(title).toContain("were run with different settings");
    expect(text).toContain("The model that plans the subtasks");
    expect(text).not.toContain("same place");
  });
});
