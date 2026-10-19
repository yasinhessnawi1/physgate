import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { costRecord, type CostRecord } from "../../api/records";
import type { Tokens, Usage } from "../../api/run";
import { TokensCard } from "./Cards";

const SOURCE = { id: "run r-1", commit: "0123456789abcdef" };

function usage(input: number, output: number): Usage {
  return { input, output, cacheRead: 0, cacheWrite: 0 };
}

describe("the token figures are the account's, never a sum made here", () => {
  // Deliberately inconsistent: the total is not the sum of the attributions. The card must
  // show the account's own total, so a total recomputed in the view would show here.
  const TOKENS: Tokens = {
    byAttribution: { "session:a": usage(10, 3), "reviewer:b": usage(4, 1) },
    byKind: {
      decomposition: usage(0, 0),
      reviewer: usage(4, 1),
      routing: usage(0, 0),
      session: usage(10, 3),
    },
    total: usage(999, 777),
  };

  it("shows the total the account gave", () => {
    const html = renderToStaticMarkup(<TokensCard tokens={TOKENS} cost={null} source={SOURCE} />);
    const total = html.slice(html.indexOf("the run"));
    expect(total).toContain('<span class="pg-quantity-value">999</span>');
    expect(total).toContain('<span class="pg-quantity-value">777</span>');
    expect(html).toContain("all routing");
  });
});

describe("a cost that is a lower bound says so beside its figure", () => {
  const TOKENS: Tokens = {
    byAttribution: { "session:a": usage(10, 3), "reviewer:b": usage(4, 1) },
    byKind: {
      decomposition: usage(0, 0),
      reviewer: usage(4, 1),
      routing: usage(0, 0),
      session: usage(10, 3),
    },
    total: usage(14, 4),
  };
  /** A cost line as the server serves it: reviews it could not reach, named unread. */
  const LINE = {
    usd: "0.25",
    nok: "2.37",
    basis: "list_price_estimate",
    prices_date: "2026-10-16",
    partial: false,
    rows: [{ model: "claude-sonnet-5", tokens: { output_tokens: 4 }, usd: "0.25" }],
    reconciliation: { unread: ["reviewer:b"], ttl_unread: ["reviewer:b", "session:a"] },
    lower_bound: true,
  };

  it("reads the mark and the calls it is short by from the line", () => {
    const cost = costRecord(LINE);
    expect(cost.lowerBound).toBe(true);
    expect(cost.unpriced).toEqual(["reviewer:b", "session:a"]);
    expect(costRecord({ ...LINE, lower_bound: false, reconciliation: null }).unpriced).toEqual([]);
    expect(() => costRecord({ ...LINE, lower_bound: undefined })).toThrow();
  });

  it("marks the card, and names the reviews the server cannot price at their rate", () => {
    const cost: CostRecord = costRecord(LINE);
    const html = renderToStaticMarkup(<TokensCard tokens={TOKENS} cost={cost} source={SOURCE} />);
    expect(html).toContain("Lower bound");
    expect(html).toContain("2 calls not priced at the rate they paid");
    expect(html).toContain("reviews unpriced at their rate");
  });

  it("says nothing of a bound when every call was read", () => {
    const whole = costRecord({ ...LINE, lower_bound: false, reconciliation: null });
    const html = renderToStaticMarkup(<TokensCard tokens={TOKENS} cost={whole} source={SOURCE} />);
    expect(html).not.toContain("Lower bound");
  });
});
