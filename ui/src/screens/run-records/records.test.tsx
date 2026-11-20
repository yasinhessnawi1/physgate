import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { costRecord, type CostRecord } from "../../api/records";
import { tokens as tokenAccount, type Tokens, type Usage } from "../../api/run";
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
    cutShort: {},
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
    cutShort: {},
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
    expect(html).toContain("Lower bound: the cost may be higher.");
    expect(html).toContain("2 calls counted at the lowest rate");
    expect(html).toContain("the records of the reviews are kept where this app does not read");
  });

  it("says nothing of a bound when every call was read", () => {
    const whole = costRecord({ ...LINE, lower_bound: false, reconciliation: null });
    const html = renderToStaticMarkup(<TokensCard tokens={TOKENS} cost={whole} source={SOURCE} />);
    expect(html).not.toContain("Lower bound");
  });
});

describe("a response cut off by a connection error is said in plain words and listed apart", () => {
  const CUT_OFF =
    "A response was cut off by a connection error; its tokens are listed separately and the cost shown is a lower bound.";
  const usageOf = (input: number, output: number, cacheWrite: number) => ({
    input_tokens: input,
    output_tokens: output,
    cache_read_input_tokens: 0,
    cache_creation_input_tokens: cacheWrite,
  });
  /** The token account as the server serves it: one review's cut response apart. */
  const ACCOUNT = {
    by_attribution: { "session:a": usageOf(10, 3, 0), "reviewer:b": usageOf(2, 180, 46710) },
    by_kind: {
      decomposition: usageOf(0, 0, 0),
      reviewer: usageOf(2, 180, 46710),
      routing: usageOf(0, 0, 0),
      session: usageOf(10, 3, 0),
    },
    total: usageOf(12, 183, 46710),
    not_in_binary_totals_billing_unknown: { "reviewer:b": usageOf(2, 1, 55515) },
  };
  /** Its cost line: every call read, so the cut response alone makes it a lower bound. */
  const LINE = {
    usd: "0.25",
    nok: "2.37",
    basis: "list_price_estimate",
    prices_date: "2026-10-16",
    partial: false,
    rows: [{ model: "claude-sonnet-5", tokens: { output_tokens: 183 }, usd: "0.25" }],
    reconciliation: { unread: [], ttl_unread: [] },
    lower_bound: true,
    not_in_binary_totals_billing_unknown: { "reviewer:b": usageOf(2, 1, 55515) },
  };

  it("reads the cut tokens from the account and the calls holding them from the cost line", () => {
    const read = tokenAccount(ACCOUNT);
    expect(read.cutShort).toEqual({
      "reviewer:b": { input: 2, output: 1, cacheRead: 0, cacheWrite: 55515 },
    });
    expect(read.total.cacheWrite).toBe(46710);
    expect(costRecord(LINE).cutShort).toEqual(["reviewer:b"]);
    expect(
      costRecord({ ...LINE, not_in_binary_totals_billing_unknown: undefined }).cutShort,
    ).toEqual([]);
  });

  it("says the line beside the cost, lists the tokens apart, and counts no call unpriced", () => {
    const html = renderToStaticMarkup(
      <TokensCard tokens={tokenAccount(ACCOUNT)} cost={costRecord(LINE)} source={SOURCE} />,
    );
    expect(html).toContain(CUT_OFF);
    expect(html).not.toContain("0 calls");
    const apart = html.slice(html.indexOf('aria-label="Cut off"'));
    expect(apart).toContain("A review · b");
    expect(apart).toContain('<span class="pg-quantity-value">55515</span>');
    expect(html).toContain("whether they were billed is not known");
  });

  it("says the line where the tokens are shown even when the cost could not be read", () => {
    const html = renderToStaticMarkup(
      <TokensCard tokens={tokenAccount(ACCOUNT)} cost={null} source={SOURCE} />,
    );
    expect(html).toContain(CUT_OFF);
    expect(html).toContain('aria-label="Cut off"');
  });

  it("keeps both reasons when calls were also unpriced", () => {
    const both = costRecord({ ...LINE, reconciliation: { unread: ["session:a"], ttl_unread: [] } });
    const html = renderToStaticMarkup(
      <TokensCard tokens={tokenAccount(ACCOUNT)} cost={both} source={SOURCE} />,
    );
    expect(html).toContain("1 call counted at the lowest rate");
    expect(html).toContain(CUT_OFF);
  });

  it("says nothing of a cut response where there is none", () => {
    const html = renderToStaticMarkup(
      <TokensCard
        tokens={tokenAccount({ ...ACCOUNT, not_in_binary_totals_billing_unknown: {} })}
        cost={costRecord({
          ...LINE,
          lower_bound: false,
          not_in_binary_totals_billing_unknown: undefined,
        })}
        source={SOURCE}
      />,
    );
    expect(html).not.toContain("cut off");
    expect(html).not.toContain('aria-label="Cut off"');
  });
});
