import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Segmented } from "./Segmented";

const OPTIONS = [
  { value: "on", label: "On" },
  { value: "observe", label: "Observe" },
  { value: "off", label: "Off" },
] as const;

describe("a segmented control with no value presses no option", () => {
  it("draws every option unpressed when its value is null", () => {
    const html = renderToStaticMarkup(
      <Segmented options={OPTIONS} value={null} label="Gate mode" disabled />,
    );
    expect(html).not.toContain('aria-pressed="true"');
    expect(html.match(/aria-pressed="false"/g)).toHaveLength(3);
    expect(html.match(/disabled=""/g)).toHaveLength(3);
  });

  it("still presses the one option its value names", () => {
    const html = renderToStaticMarkup(<Segmented options={OPTIONS} value="observe" label="Mode" />);
    expect(html.match(/aria-pressed="true"/g)).toHaveLength(1);
    expect(html).toMatch(/aria-pressed="true"[^>]*>Observe</);
  });

  it("links the sentence that says why to the group and to every option", () => {
    const html = renderToStaticMarkup(
      <Segmented options={OPTIONS} value={null} label="Gate mode" disabled describedBy="why" />,
    );
    expect(html.match(/aria-describedby="why"/g)).toHaveLength(4);
  });

  it("links nothing when no sentence is named", () => {
    const html = renderToStaticMarkup(<Segmented options={OPTIONS} value="on" label="Mode" />);
    expect(html).not.toContain("aria-describedby");
  });
});
