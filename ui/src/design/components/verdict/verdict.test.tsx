import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { GateModeBadge, GateOutcome } from "./GateMode";
import { Tally } from "./Tally";
import { VerdictBadge } from "./VerdictBadge";

describe("unchecked is never inside the evaluated count", () => {
  const html = renderToStaticMarkup(<Tally pass={10} fail={1} warn={2} unchecked={3} />);

  it("counts pass, fail and warn as evaluated, and only those", () => {
    expect(html).toContain('data-evaluated="13"');
  });

  it("puts unchecked after a separator, outside the evaluated group", () => {
    const evaluated = html.slice(html.indexOf("pg-tally-evaluated"), html.indexOf("pg-tally-sep"));
    expect(evaluated).not.toContain("pg-verdict-unchecked");
    expect(html.indexOf("pg-tally-sep")).toBeLessThan(html.indexOf("pg-verdict-unchecked"));
  });

  it("counted under observe, shows would-be outcomes and no filled verdict", () => {
    const observed = renderToStaticMarkup(
      <Tally pass={2} fail={1} warn={0} unchecked={4} observed />,
    );
    expect(observed).not.toMatch(/pg-verdict-(pass|fail|warn)/);
    expect(observed).toContain("Would fail");
    expect(observed).toContain("not enforced");
    expect(observed).toContain('data-evaluated="3"');
  });

  it("draws unchecked dashed and unfilled, not like a pass", () => {
    expect(renderToStaticMarkup(<VerdictBadge verdict="unchecked" />)).toContain(
      "pg-verdict-unchecked",
    );
  });

  it("compact keeps the word in each badge, and unchecked still after the separator", () => {
    const compact = renderToStaticMarkup(
      <Tally pass={11} fail={1} warn={0} unchecked={2} compact />,
    );
    for (const word of ["Pass", "Fail", "Warn", "Unchecked"]) expect(compact).toContain(word);
    expect(compact).toContain('data-evaluated="12"');
    expect(compact.indexOf("pg-tally-sep")).toBeLessThan(compact.indexOf("pg-verdict-unchecked"));
    const evaluated = compact.slice(0, compact.indexOf("pg-tally-sep"));
    expect(evaluated).not.toContain("pg-verdict-unchecked");
  });

  it("partial reads 'so far', as text", () => {
    const partial = renderToStaticMarkup(
      <Tally pass={1} fail={0} warn={0} unchecked={0} partial />,
    );
    expect(partial).toContain('<span class="pg-so-far">so far</span>');
  });
});

describe("a verdict is a glyph, a word and a colour, always all three", () => {
  it.each([
    ["pass", "✓", "Pass"],
    ["fail", "✕", "Fail"],
    ["warn", "!", "Warn"],
    ["unchecked", "○", "Unchecked"],
  ] as const)("%s", (verdict, glyph, word) => {
    const html = renderToStaticMarkup(<VerdictBadge verdict={verdict} />);
    expect(html).toContain(glyph);
    expect(html).toContain(word);
    expect(html).toContain(`pg-verdict-${verdict}`);
  });
});

describe("an observe-mode result is never drawn as a filled pass or fail", () => {
  it.each(["fail", "pass", "warn"] as const)(
    "observe %s reads as would-be and not enforced",
    (outcome) => {
      const html = renderToStaticMarkup(<GateOutcome mode="observe" outcome={outcome} />);
      expect(html).toContain("not enforced");
      expect(html).toContain("observed");
      expect(html).not.toMatch(/pg-verdict-(pass|fail|warn)/);
    },
  );

  it("observe fail says would fail", () => {
    expect(renderToStaticMarkup(<GateOutcome mode="observe" outcome="fail" />)).toContain(
      "Would fail · not enforced",
    );
  });

  it("a gated fail is a filled fail", () => {
    expect(renderToStaticMarkup(<GateOutcome mode="on" outcome="fail" />)).toContain(
      "pg-verdict-fail",
    );
  });

  it("the observe badge says it is not gated", () => {
    expect(renderToStaticMarkup(<GateModeBadge mode="observe" />)).toContain("Observe · not gated");
  });

  it("on, observe and off read and draw apart", () => {
    const words = (["on", "observe", "off"] as const).map((mode) =>
      renderToStaticMarkup(<GateModeBadge mode={mode} />),
    );
    expect(new Set(words.map((w) => /pg-gate-(\w+)/.exec(w)?.[1])).size).toBe(3);
    expect(words[0]).toContain("Gate on");
    expect(words[2]).toContain("Gate off");
  });
});
