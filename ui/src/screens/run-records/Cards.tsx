/**
 * What a run spent: per model at a price sheet's list prices, and per attribution and per kind of
 * spender from the token account, with the account's own total. Routing is shown, at zero when it
 * is zero. No figure here is summed in the view.
 */
import type { CostRecord } from "../../api/records";
import type { Tokens, Usage } from "../../api/run";
import { Quantity } from "../../design/components/data/Quantity";
import { SourceChip } from "../../design/components/data/SourceChip";
import { type Source, sourceAttribute } from "../../design/components/data/source";
import { Term } from "../../design/components/help/Term";
import { CostCaveat } from "../common/cost";

function tok(value: number) {
  return <Quantity value={value} unit="tok" />;
}

function UsageCells({ usage }: { readonly usage: Usage }) {
  return (
    <>
      <td className="pg-num">{tok(usage.input)}</td>
      <td className="pg-num">{tok(usage.output)}</td>
      <td className="pg-num">{tok(usage.cacheRead)}</td>
      <td className="pg-num">{tok(usage.cacheWrite)}</td>
    </>
  );
}

const USAGE_HEAD = (
  <>
    <th scope="col" className="pg-num">
      Input
    </th>
    <th scope="col" className="pg-num">
      Output
    </th>
    <th scope="col" className="pg-num">
      Cache read
    </th>
    <th scope="col" className="pg-num">
      Cache write
    </th>
  </>
);

/** An attribution as recorded, read: a session, a reviewer, the decomposition, routing. */
function attributionWords(key: string): string {
  const [kind = key, id] = key.split(":");
  const words: Record<string, string> = {
    session: "An agent's session",
    reviewer: "A review",
    decomposition: "The decomposition",
    routing: "Routing",
  };
  return id === undefined ? (words[kind] ?? key) : `${words[kind] ?? kind} · ${id}`;
}

export function TokensCard({
  tokens,
  cost,
  source,
}: {
  readonly tokens: Tokens;
  readonly cost: CostRecord | null;
  readonly source: Source;
}) {
  return (
    <section
      className="pg-card pg-panel"
      aria-label="Tokens and cost"
      data-source={sourceAttribute(source)}
    >
      <header className="pg-panel-head">
        <h2 className="pg-panel-title">Tokens and cost</h2>
        {cost !== null && <span className="pg-panel-note">price sheet of {cost.pricesDate}</span>}
      </header>
      {cost !== null && (
        <>
          <p className="pg-panel-note">
            {cost.basis === "list_price_estimate" ? (
              <>
                A <Term term="list-price">list-price estimate</Term>: the subscription is not billed
                per token.
              </>
            ) : (
              "The tokens at the sheet's list prices."
            )}
            {cost.partial ? " Partial: some usage was read from an unfinished stream." : ""}
            <CostCaveat cost={cost} />
          </p>
          <div className="pg-table-wrap" role="region" aria-label="Cost by model" tabIndex={0}>
            <table className="pg-table" aria-label="By model">
              <thead>
                <tr>
                  <th scope="col">Model</th>
                  <th scope="col" className="pg-num">
                    Output
                  </th>
                  <th scope="col" className="pg-num">
                    Cost
                  </th>
                </tr>
              </thead>
              <tbody>
                {cost.rows.map((row) => (
                  <tr key={row.model}>
                    <td className="mono">{row.model}</td>
                    <td className="pg-num">
                      <Quantity {...row.outputTokens} />
                    </td>
                    <td className="pg-num">
                      <Quantity {...row.usd} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      <div className="pg-table-wrap" role="region" aria-label="Tokens by attribution" tabIndex={0}>
        <table className="pg-table" aria-label="By attribution">
          <thead>
            <tr>
              <th scope="col">Spent by</th>
              {USAGE_HEAD}
            </tr>
          </thead>
          <tbody>
            {Object.entries(tokens.byAttribution).map(([attribution, usage]) => (
              <tr key={attribution}>
                <td>{attributionWords(attribution)}</td>
                <UsageCells usage={usage} />
              </tr>
            ))}
            {Object.entries(tokens.byKind).map(([kind, usage]) => (
              <tr key={`kind-${kind}`} className="pg-subtotal">
                <th scope="row">all {kind}</th>
                <UsageCells usage={usage} />
              </tr>
            ))}
            <tr className="pg-total">
              <th scope="row">the run</th>
              <UsageCells usage={tokens.total} />
            </tr>
          </tbody>
        </table>
      </div>
      <SourceChip {...{ ...source, id: `${source.id} · token account` }} />
    </section>
  );
}
