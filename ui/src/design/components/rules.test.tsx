import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { BareNumberError, requireQuantity } from "../quantity";
import { Figure, WhatIfVerdictError } from "./Figure";
import { GateModeBadge, GateOutcome } from "./GateMode";
import { Quantity } from "./Quantity";
import { SourceChip } from "./SourceChip";
import { ErrorState } from "./States";
import { Tally, VerdictBadge } from "./VerdictBadge";

const SOURCE = { id: "run r-1", commit: "0123456789abcdef" };

describe("a quantity is always shown with its unit", () => {
  it("renders the value and its unit inside one unbreakable element", () => {
    const html = renderToStaticMarkup(<Quantity q={{ value: 0.625, unit: "rad" }} />);
    expect(html).toBe(
      '<span class="quantity"><span class="quantity-value">0.625</span><span class="quantity-unit">rad</span></span>',
    );
  });

  it("says dimensionless rather than showing nothing", () => {
    expect(renderToStaticMarkup(<Quantity q={{ value: 2.36, unit: "1" }} />)).toContain(
      "dimensionless",
    );
  });

  it("shows an exact decimal as the record wrote it", () => {
    expect(renderToStaticMarkup(<Quantity q={{ value: "14.790000", unit: "USD" }} />)).toContain(
      "14.790000",
    );
  });

  it("does not type a bare number", () => {
    // @ts-expect-error a bare number is not a quantity: if this line ever type-checks, the
    // directive is unused and the type check fails.
    const element = <Quantity q={2.4} />;
    expect(element).toBeTruthy();
    // @ts-expect-error a value without its unit is not a quantity either.
    expect(<Quantity q={{ value: 2.4 }} />).toBeTruthy();
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
    expect(() => renderToStaticMarkup(<Quantity q={bad as never} />)).toThrow(BareNumberError);
  });
});

describe("unchecked is never inside the evaluated count", () => {
  const html = renderToStaticMarkup(
    <Tally counts={{ pass: 10, fail: 1, warn: 2, unchecked: 3 }} />,
  );

  it("counts pass, fail and warn as evaluated, and only those", () => {
    expect(html).toContain('data-evaluated="13"');
  });

  it("puts unchecked after a separator, outside the evaluated group", () => {
    const evaluated = html.slice(html.indexOf("tally-evaluated"), html.indexOf("tally-separator"));
    expect(evaluated).not.toContain("verdict-unchecked");
    expect(html.indexOf("tally-separator")).toBeLessThan(html.indexOf("verdict-unchecked"));
  });

  it("counted under observe, shows would-be outcomes and no filled verdict", () => {
    const observed = renderToStaticMarkup(
      <Tally counts={{ pass: 2, fail: 1, warn: 0, unchecked: 4 }} observed />,
    );
    expect(observed).not.toMatch(/verdict-(pass|fail|warn)/);
    expect(observed).toContain("Would fail");
    expect(observed).toContain("not enforced");
    expect(observed).toContain('data-evaluated="3"');
  });

  it("draws unchecked dashed and unfilled, not like a pass", () => {
    expect(renderToStaticMarkup(<VerdictBadge verdict="unchecked" />)).toContain(
      "verdict-unchecked",
    );
  });
});

describe("an observe-mode result is never drawn as a filled pass or fail", () => {
  it.each(["fail", "pass", "warn"] as const)(
    "observe %s reads as would-be and not enforced",
    (outcome) => {
      const html = renderToStaticMarkup(<GateOutcome mode="observe" outcome={outcome} />);
      expect(html).toContain("not enforced");
      expect(html).toContain("observed");
      expect(html).not.toMatch(/verdict-(pass|fail|warn)/);
    },
  );

  it("observe fail says would fail", () => {
    expect(renderToStaticMarkup(<GateOutcome mode="observe" outcome="fail" />)).toContain(
      "Would fail · not enforced",
    );
  });

  it("a gated fail is a filled fail", () => {
    expect(renderToStaticMarkup(<GateOutcome mode="on" outcome="fail" />)).toContain(
      "verdict-fail",
    );
  });

  it("the observe badge says it is not gated", () => {
    expect(renderToStaticMarkup(<GateModeBadge mode="observe" />)).toContain("Observe · not gated");
  });
});

describe("a what-if value is never given a verdict", () => {
  it("renders the value with the what-if marker and no verdict", () => {
    const html = renderToStaticMarkup(
      <Figure q={{ value: 0.541, unit: "rad" }} whatIf={{ draft: "wi-1" }} />,
    );
    expect(html).toContain("What-if");
    expect(html).not.toContain("verdict");
  });

  it("has no place for a verdict in its type, and refuses one at run time", () => {
    expect(() =>
      renderToStaticMarkup(
        // @ts-expect-error a what-if figure takes no verdict.
        <Figure q={{ value: 0.541, unit: "rad" }} whatIf={{ draft: "wi-1" }} verdict="pass" />,
      ),
    ).toThrow(WhatIfVerdictError);
  });

  it("a recorded figure carries its verdict and names its source", () => {
    const html = renderToStaticMarkup(
      <Figure q={{ value: 0.625, unit: "rad" }} source={SOURCE} verdict="pass" />,
    );
    expect(html).toContain("verdict-pass");
    expect(html).toContain('data-source="run r-1@0123456"');
  });
});

describe("every figure names its source", () => {
  it("shows the id and the short commit", () => {
    const html = renderToStaticMarkup(<SourceChip source={SOURCE} />);
    expect(html).toContain("run r-1");
    expect(html).toContain("0123456");
    expect(html).not.toContain("0123456789");
  });

  it("says when a record has no commit", () => {
    expect(renderToStaticMarkup(<SourceChip source={{ id: "run r-2", commit: null }} />)).toContain(
      "no commit",
    );
  });
});

describe("an error names what was refused and shows nothing partial", () => {
  const html = renderToStaticMarkup(
    <ErrorState
      title="Task ledger: not shown"
      refusal={{
        status: 422,
        error: "the ledger disagrees with the run-event log",
        context: { ledger: "ledger.jsonl" },
      }}
    />,
  );

  it("is an alert carrying the title, the server's reason, its status and its context", () => {
    expect(html).toContain('role="alert"');
    expect(html).toContain("Task ledger: not shown");
    expect(html).toContain("the ledger disagrees with the run-event log");
    expect(html).toContain("422");
    expect(html).toContain("ledger.jsonl");
  });

  it("holds no table: nothing of the refused record is shown", () => {
    expect(html).not.toContain("<table");
  });
});
