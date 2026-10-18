import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import tokens from "../../tokens.json";
import { BareNumberError, requireQuantity, valueLabel } from "../../quantity";
import { DOMAIN_KINDS, DomainChip } from "./DomainChip";
import { Figure, WhatIfVerdictError } from "./Figure";
import { Quantity } from "./Quantity";
import { SourceChip } from "./SourceChip";

const SOURCE = { id: "run r-1", commit: "0123456789abcdef" };

describe("a quantity is always shown with its unit", () => {
  it("renders the value and its unit inside one unbreakable element", () => {
    const html = renderToStaticMarkup(<Quantity value={0.625} unit="rad" />);
    expect(html).toBe(
      '<span class="pg-quantity"><span class="pg-quantity-value">0.625</span><span class="pg-quantity-unit">rad</span></span>',
    );
  });

  it("says dimensionless rather than showing nothing", () => {
    expect(renderToStaticMarkup(<Quantity value={2.36} unit="1" />)).toContain("dimensionless");
  });

  it("shows a number with every digit the record holds, never rounded", () => {
    for (const value of [0.123456789, 14.7123, 1234.5678, -0.000123456, 6.02214076e23]) {
      expect(valueLabel(value)).toBe(String(value));
      expect(renderToStaticMarkup(<Quantity value={value} unit="m" />)).toContain(
        `<span class="pg-quantity-value">${String(value)}</span>`,
      );
    }
  });

  it("shows an exact decimal as the record wrote it", () => {
    expect(renderToStaticMarkup(<Quantity value="14.790000" unit="USD" />)).toContain("14.790000");
  });

  it("does not type a bare number", () => {
    // @ts-expect-error a bare number is not a quantity: if this line ever type-checks, the
    // directive is unused and the type check fails.
    const element = <Quantity value={2.4} />;
    expect(element).toBeTruthy();
    // @ts-expect-error a unit without its value is not a quantity either.
    expect(<Quantity unit="A" />).toBeTruthy();
  });

  it.each([
    2.4,
    { value: 2.4 },
    { value: 2.4, unit: "" },
    { value: Number.NaN, unit: "A" },
    { value: "2,4", unit: "A" },
    null,
  ])("refuses %j at run time, never showing the number", (bad) => {
    expect(() => requireQuantity(bad)).toThrow(BareNumberError);
    const props = (typeof bad === "object" && bad !== null ? bad : { value: bad }) as never;
    expect(() =>
      renderToStaticMarkup(<Quantity {...(props as { value: number; unit: string })} />),
    ).toThrow(BareNumberError);
  });

  it("adds 'so far' to a running total as text, not as decoration", () => {
    const html = renderToStaticMarkup(<Quantity value="3.20" unit="USD" partial />);
    expect(html).toContain('<span class="pg-so-far">so far</span>');
  });
});

describe("a what-if value is never given a verdict", () => {
  it("renders the value with the what-if marker and no verdict", () => {
    const html = renderToStaticMarkup(
      <Figure value={0.541} unit="rad" whatIf={{ draft: "wi-1" }} />,
    );
    expect(html).toContain("What-if");
    expect(html).not.toContain("verdict");
  });

  it("has no place for a verdict in its type, and refuses one at run time", () => {
    expect(() =>
      renderToStaticMarkup(
        // @ts-expect-error a what-if figure takes no verdict.
        <Figure value={0.541} unit="rad" whatIf={{ draft: "wi-1" }} verdict="pass" />,
      ),
    ).toThrow(WhatIfVerdictError);
  });

  it("a recorded figure carries its verdict and names its source", () => {
    const html = renderToStaticMarkup(
      <Figure value={0.625} unit="rad" source={SOURCE} verdict="pass" />,
    );
    expect(html).toContain("pg-verdict-pass");
    expect(html).toContain('data-source="run r-1@0123456"');
  });

  it("a recorded figure must name its source, and one with none shows the dashed chip", () => {
    // @ts-expect-error a recorded figure without a source is not a figure.
    expect(<Figure value={1} unit="A" />).toBeTruthy();
    const html = renderToStaticMarkup(<Figure value={1} unit="A" source={null} />);
    expect(html).toContain("pg-source-missing");
    expect(html).toContain("no source");
    expect(html).not.toContain("data-source");
  });
});

describe("every figure names its source", () => {
  it("shows the id and the short commit", () => {
    const html = renderToStaticMarkup(<SourceChip {...SOURCE} />);
    expect(html).toContain("run r-1");
    expect(html).toContain("0123456");
    expect(html).not.toContain("0123456789");
  });

  it("says when a record has no commit, dashed, never with a dash where the commit goes", () => {
    const html = renderToStaticMarkup(<SourceChip id="run r-2" commit={null} />);
    // The words are drawn on the chip itself, not only carried in its accessible name.
    const drawn = html.replace(/<[^>]*>/g, "");
    expect(drawn).toContain("no commit");
    expect(html).toContain("pg-source-missing");
    expect(html).not.toContain("—");
    const compact = renderToStaticMarkup(<SourceChip id="run r-2" commit={null} compact />);
    expect(compact).toContain('data-full="run r-2 · no commit"');
  });

  it("says when a figure has no source, dashed", () => {
    for (const id of [null, "", "  "]) {
      const html = renderToStaticMarkup(<SourceChip id={id} commit="abc" />);
      expect(html).toContain("no source");
      expect(html).toContain("pg-source-missing");
      expect(html).not.toContain("—");
    }
  });

  it("compact: an icon and a short name, the full id and commit on hover, focus and in its name", () => {
    const html = renderToStaticMarkup(<SourceChip id="0/run-on" commit="0123456789" compact />);
    expect(html).toContain('aria-label="Source: 0/run-on at commit 0123456"');
    expect(html).toContain('title="0/run-on · 0123456"');
    expect(html).toContain('tabindex="0"');
    expect(html).toContain('data-icon="git-commit-horizontal"');
    expect(html).toContain(">run-on<");
    expect(html).toContain('data-source="0/run-on@0123456"');
  });
});

describe("a domain is its word", () => {
  it("knows exactly the token file's domains", () => {
    expect([...DOMAIN_KINDS].sort()).toEqual([...tokens.domains].sort());
  });

  it("draws the word, outlined, never the colour alone", () => {
    expect(renderToStaticMarkup(<DomainChip domain="cross" />)).toBe(
      '<span class="pg-domain pg-domain-cross">Cross-domain</span>',
    );
  });
});
