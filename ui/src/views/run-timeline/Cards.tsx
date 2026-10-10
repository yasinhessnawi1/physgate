import { ScrollTable } from "../../design/components/ScrollTable";
import type { CostRecord } from "../../api/records";
import type { SessionTrace, TimelineEvents, Tokens, Usage } from "../../api/run";
import { Quantity } from "../../design/components/Quantity";
import { type Source, SourceChip, sourceAttribute } from "../../design/components/SourceChip";
import { VerdictBadge } from "../../design/components/VerdictBadge";

function tok(value: number) {
  return <Quantity q={{ value, unit: "tok" }} />;
}

function UsageCells({ usage }: { usage: Usage }) {
  return (
    <>
      <td className="numeric">{tok(usage.input)}</td>
      <td className="numeric">{tok(usage.output)}</td>
      <td className="numeric">{tok(usage.cacheRead)}</td>
      <td className="numeric">{tok(usage.cacheWrite)}</td>
    </>
  );
}

const USAGE_HEAD = (
  <>
    <th scope="col" className="numeric">
      Input
    </th>
    <th scope="col" className="numeric">
      Output
    </th>
    <th scope="col" className="numeric">
      Cache read
    </th>
    <th scope="col" className="numeric">
      Cache write
    </th>
  </>
);

/** Every session: how it ended, its wall clock and what it spent, as the trace recorded them. */
export function SessionsCard({
  sessions,
  source,
}: {
  sessions: readonly SessionTrace[];
  source: Source;
}) {
  return (
    <section className="card" aria-label="Sessions" data-source={sourceAttribute(source)}>
      <h2 className="card-title">Sessions</h2>
      <p className="view-note">
        A session&apos;s wall clock runs from its spawn line to its end line, so it includes the
        orchestrator&apos;s setup for it.
      </p>
      <ScrollTable label="Sessions">
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Session</th>
              <th scope="col">Subtask</th>
              <th scope="col">Attempt</th>
              <th scope="col">Outcome</th>
              <th scope="col" className="numeric">
                Wall clock
              </th>
              {USAGE_HEAD}
            </tr>
          </thead>
          <tbody>
            {sessions.map((s) => (
              <tr key={s.sessionId}>
                <td className="mono">{s.sessionId}</td>
                <td className="mono">{s.subtask ?? "left over"}</td>
                <td className="mono">{s.attempt ?? "—"}</td>
                <td>
                  {s.outcome}
                  {s.cause === null ? "" : ` · ${s.cause}`}
                  {s.partial ? " · partial" : ""}
                </td>
                <td className="numeric">
                  {s.wallClockS === null ? (
                    <span className="muted">not recorded</span>
                  ) : (
                    <Quantity q={{ value: s.wallClockS, unit: "s" }} />
                  )}
                </td>
                <UsageCells usage={s.tokens} />
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollTable>
    </section>
  );
}

/**
 * What the run spent: per model at the price sheet's prices, and per attribution and per kind of
 * spender from the token account, with the account's own total. Routing is shown, at zero.
 */
export function TokensCard({
  tokens,
  cost,
  source,
}: {
  tokens: Tokens;
  cost: CostRecord | null;
  source: Source;
}) {
  return (
    <section className="card" aria-label="Tokens and cost" data-source={sourceAttribute(source)}>
      <div className="card-head">
        <h2 className="card-title">Tokens and cost</h2>
        {cost !== null && (
          <span className="label">
            prices of <span className="mono">{cost.pricesDate}</span>
          </span>
        )}
      </div>
      {cost !== null && (
        <>
          <p className="view-note">
            {cost.basis === "list_price_estimate"
              ? "A list-price estimate: the subscription is not billed per token."
              : "The tokens at the sheet's list prices."}
            {cost.partial ? " Partial: some usage was read from an unfinished stream." : ""}
          </p>
          <ScrollTable label="By model">
            <table className="table" aria-label="By model">
              <thead>
                <tr>
                  <th scope="col">Model</th>
                  <th scope="col" className="numeric">
                    Output
                  </th>
                  <th scope="col" className="numeric">
                    Cost
                  </th>
                </tr>
              </thead>
              <tbody>
                {cost.rows.map((row) => (
                  <tr key={row.model}>
                    <td className="mono">{row.model}</td>
                    <td className="numeric">
                      <Quantity q={row.outputTokens} />
                    </td>
                    <td className="numeric">
                      <Quantity q={row.usd} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollTable>
        </>
      )}
      <ScrollTable label="By attribution">
        <table className="table" aria-label="By attribution">
          <thead>
            <tr>
              <th scope="col">Attribution</th>
              {USAGE_HEAD}
            </tr>
          </thead>
          <tbody>
            {Object.entries(tokens.byAttribution).map(([attribution, usage]) => (
              <tr key={attribution}>
                <td className="mono">{attribution}</td>
                <UsageCells usage={usage} />
              </tr>
            ))}
            {Object.entries(tokens.byKind).map(([kind, usage]) => (
              <tr key={`kind-${kind}`} className="row-subtotal">
                <th scope="row">all {kind}</th>
                <UsageCells usage={usage} />
              </tr>
            ))}
            <tr className="row-total">
              <th scope="row">the run</th>
              <UsageCells usage={tokens.total} />
            </tr>
          </tbody>
        </table>
      </ScrollTable>
      <SourceChip source={{ ...source, id: `${source.id} · token account` }} />
    </section>
  );
}

/** Each review: its verdict, its reviewer's model, and whether its reading was verified. */
export function ReviewsCard({
  reviews,
  source,
}: {
  reviews: TimelineEvents["reviews"];
  source: Source;
}) {
  const models = [...new Set(reviews.map((r) => r.reviewerModel))];
  return (
    <section className="card" aria-label="Reviewer verdicts" data-source={sourceAttribute(source)}>
      <div className="card-head">
        <h2 className="card-title">Reviewer verdicts</h2>
        <span className="label mono">{models.join(", ")}</span>
      </div>
      {reviews.length === 0 ? (
        <p className="view-note">No reviewer ran in this run.</p>
      ) : (
        <ul className="reviews">
          {reviews.map((r) => (
            <li key={r.seq} className="review">
              <span>
                <span className="mono">{r.subtask}</span>{" "}
                <span className="label">attempt {r.attempt}</span>
                <span className="label">
                  {" "}
                  · reading verified:{" "}
                  {r.readingVerified === null ? "not recorded" : r.readingVerified ? "yes" : "no"}
                </span>
              </span>
              {r.verdict === "pass" || r.verdict === "fail" ? (
                <VerdictBadge verdict={r.verdict} />
              ) : (
                <span className="badge review-other">{r.verdict}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
