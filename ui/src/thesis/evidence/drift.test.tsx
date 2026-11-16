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
      "These two runs cannot be compared: they did not start from the same place with the same settings",
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
});
