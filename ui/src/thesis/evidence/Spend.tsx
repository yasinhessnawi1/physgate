/**
 * A run's spend: its cost line as the product's cost route prices it, at the newest price sheet
 * the server holds, named; then each role's sessions, each session's priced call beside the
 * role's sum, the sum labelled with the server's own words for what it is (a view); then the
 * calls apart from the roles. Every figure is the server's; a lower bound reads "at least", and
 * a group with no call says so in words, never a zero.
 */
import { priceDates } from "../../api/records";
import { Figure } from "../../design/components/data/Figure";
import { Quantity } from "../../design/components/data/Quantity";
import { sourceAttribute } from "../../design/components/data/source";
import { EmptyState, ErrorState, LoadingState } from "../../design/components/status/States";
import { useJson } from "../../screens/common/read";
import {
  APART,
  type Apart,
  byKind,
  evidenceSpend,
  newestDate,
  parsePlace,
  placeKey,
  PRICES_ROUTE,
  type PricedCall,
  type ReadRun,
  type Reconciliation,
  type RoleSpend,
  type RunRow,
  type Spend,
  spendRoute,
  type Sum,
  type Tokens,
} from "./api";
import { evidenceAddress, go } from "./address";
import { RunChooser } from "./Chooser";
import { answerSource, AtLeast, RunMark } from "./parts";
import { APART_WORDS, basisWords, EVIDENCE_COPY, pricedAtWords, spendRefusedWords } from "./words";

/** The run whose spend is shown: the one the address names, or the first read, kind by kind. */
export function chosenRun(runs: readonly ReadRun[], key: string | null): ReadRun | undefined {
  const wanted = parsePlace(key);
  const named =
    wanted === null ? undefined : runs.find((run) => placeKey(run) === placeKey(wanted));
  return named ?? runs[0];
}

function TokenCells({ tokens }: { readonly tokens: Tokens }) {
  return (
    <>
      <td className="pg-num">
        <Quantity value={tokens.input} unit="tok" />
      </td>
      <td className="pg-num">
        <Quantity value={tokens.output} unit="tok" />
      </td>
      <td className="pg-num">
        <Quantity value={tokens.cacheRead} unit="tok" />
      </td>
      <td className="pg-num">
        <Quantity value={tokens.cacheCreation} unit="tok" />
      </td>
    </>
  );
}

function Usd({ usd, lowerBound }: { readonly usd: string; readonly lowerBound: boolean }) {
  return (
    <td className="pg-num">
      <AtLeast shown={lowerBound} />
      <Quantity value={usd} unit="USD" decimals={2} />
    </td>
  );
}

function Notes({ call }: { readonly call: PricedCall }) {
  if (call.sealBroken) return <td className="evidence-reason">{EVIDENCE_COPY.sealBroken}</td>;
  if (call.lowerBound) return <td>{EVIDENCE_COPY.lowerBound}</td>;
  return <td />;
}

const TOKEN_HEADS = [
  EVIDENCE_COPY.input,
  EVIDENCE_COPY.output,
  EVIDENCE_COPY.cacheRead,
  EVIDENCE_COPY.cacheWritten,
];

function Heads({ leading }: { readonly leading: readonly string[] }) {
  return (
    <thead>
      <tr>
        {leading.map((label) => (
          <th key={label} scope="col">
            {label}
          </th>
        ))}
        {TOKEN_HEADS.map((label) => (
          <th key={label} scope="col" className="pg-num">
            {label}
          </th>
        ))}
        <th scope="col" className="pg-num">
          {EVIDENCE_COPY.usd}
        </th>
        <th scope="col">{EVIDENCE_COPY.notes}</th>
      </tr>
    </thead>
  );
}

function SumRow({ sum, span, view }: { sum: Sum; span: number; view: string | null }) {
  return (
    <tfoot>
      <tr className="evidence-sum">
        <th scope="row" colSpan={span}>
          <span className="evidence-label">{EVIDENCE_COPY.sum}</span>
          {view !== null && <span className="evidence-view">{view}</span>}
        </th>
        <TokenCells tokens={sum.tokens} />
        <Usd usd={sum.usd} lowerBound={sum.lowerBound} />
        <td>{sum.lowerBound ? EVIDENCE_COPY.lowerBound : ""}</td>
      </tr>
    </tfoot>
  );
}

const SESSION_HEADS = [
  EVIDENCE_COPY.session,
  EVIDENCE_COPY.subtask,
  EVIDENCE_COPY.attempt,
  EVIDENCE_COPY.outcome,
  EVIDENCE_COPY.model,
];

function RoleTable({ role, view }: { readonly role: RoleSpend; readonly view: string }) {
  return (
    <div className="pg-table-wrap" role="region" aria-label={role.role} tabIndex={0}>
      <table className="pg-table evidence-spend-table" data-role={role.role}>
        <caption>{role.role}</caption>
        <Heads leading={SESSION_HEADS} />
        <tbody>
          {role.sessions.map((session) => (
            <tr key={session.attribution} data-session={session.sessionId}>
              <td className="pg-id">{session.sessionId}</td>
              <td className="pg-id">{session.subtaskId}</td>
              <td>{String(session.attempt)}</td>
              <td>{session.outcome}</td>
              <td className="pg-id">{session.model}</td>
              <TokenCells tokens={session.tokens} />
              <Usd usd={session.usd} lowerBound={session.lowerBound} />
              <Notes call={session} />
            </tr>
          ))}
        </tbody>
        <SumRow sum={role.sum} span={SESSION_HEADS.length} view={view} />
      </table>
    </div>
  );
}

const CALL_HEADS = [EVIDENCE_COPY.call, EVIDENCE_COPY.model];

function ApartGroup({ title, none, group }: { title: string; none: string; group: Apart }) {
  return (
    <section className="evidence-apart" aria-label={title}>
      <h3 className="evidence-subtitle">{title}</h3>
      {group.sum === null ? (
        <p className="evidence-note">{none}</p>
      ) : (
        <div className="pg-table-wrap" role="region" aria-label={title} tabIndex={0}>
          <table className="pg-table evidence-spend-table">
            <Heads leading={CALL_HEADS} />
            <tbody>
              {group.calls.map((call) => (
                <tr key={call.attribution}>
                  <td className="pg-id">{call.attribution}</td>
                  <td className="pg-id">{call.model}</td>
                  <TokenCells tokens={call.tokens} />
                  <Usd usd={call.usd} lowerBound={call.lowerBound} />
                  <Notes call={call} />
                </tr>
              ))}
            </tbody>
            <SumRow sum={group.sum} span={CALL_HEADS.length} view={null} />
          </table>
        </div>
      )}
    </section>
  );
}

function Calls({ calls }: { readonly calls: readonly string[] }) {
  if (calls.length === 0) return <>{EVIDENCE_COPY.none}</>;
  return (
    <>
      {calls.map((call) => (
        <span key={call} className="pg-id">
          {call}
        </span>
      ))}
    </>
  );
}

function Against({ held }: { readonly held: Reconciliation | null }) {
  if (held === null) return <p className="evidence-note">{EVIDENCE_COPY.noReconciliation}</p>;
  const lists: readonly (readonly [string, readonly string[]])[] = [
    [EVIDENCE_COPY.differs, held.differs],
    [EVIDENCE_COPY.unreadCalls, held.unread],
    [EVIDENCE_COPY.ttlUnread, held.ttlUnread],
    [EVIDENCE_COPY.sealBrokenCalls, held.sealBroken],
  ];
  return (
    <dl className="evidence-pairs">
      <div>
        <dt>{EVIDENCE_COPY.reportedUsd}</dt>
        <dd>
          <Quantity value={held.binaryUsd} unit="USD" decimals={2} />
        </dd>
      </div>
      <div>
        <dt>{EVIDENCE_COPY.pricedUsd}</dt>
        <dd>
          <Quantity value={held.pricedUsd} unit="USD" decimals={2} />
        </dd>
      </div>
      {lists.map(([label, calls]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>
            <Calls calls={calls} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

function SpendBody({ spend }: { readonly spend: Spend }) {
  const source = answerSource(spend.source);
  const { line } = spend;
  return (
    <div className="evidence-spend" data-source={sourceAttribute(source)}>
      <RunMark source={spend.source} />
      <section className="pg-card pg-panel" aria-label={EVIDENCE_COPY.cost}>
        <h2 className="pg-panel-title">{EVIDENCE_COPY.cost}</h2>
        <p className="evidence-note">{basisWords(line.basis, line.pricesDate)}</p>
        {line.partial && <p className="evidence-note">{EVIDENCE_COPY.partial}</p>}
        {line.lowerBound && (line.unpriced.length > 0 || line.cutShort.length === 0) && (
          <p className="evidence-note">{EVIDENCE_COPY.lowerBoundLine}</p>
        )}
        {line.cutShort.length > 0 && <p className="evidence-note">{EVIDENCE_COPY.cutOff}</p>}
        <div className="pg-figure-line">
          <span>
            <AtLeast shown={line.lowerBound} />
            <Figure {...line.usd} decimals={2} source={source} partial={line.partial} />
          </span>
          <span>
            <AtLeast shown={line.lowerBound} />
            <Figure {...line.nok} decimals={2} source={source} partial={line.partial} />
          </span>
        </div>
        <h3 className="evidence-subtitle">{EVIDENCE_COPY.reconciliation}</h3>
        <Against held={spend.reconciliation} />
      </section>
      <section className="pg-card pg-panel" aria-label={EVIDENCE_COPY.perRole}>
        <h2 className="pg-panel-title">{EVIDENCE_COPY.perRole}</h2>
        {spend.roles.length === 0 ? (
          <p className="evidence-note">{EVIDENCE_COPY.noRoles}</p>
        ) : (
          spend.roles.map((role) => <RoleTable key={role.role} role={role} view={spend.view} />)
        )}
      </section>
      <section className="pg-card pg-panel" aria-label={EVIDENCE_COPY.apart}>
        <h2 className="pg-panel-title">{EVIDENCE_COPY.apart}</h2>
        {APART.map((group) => (
          <ApartGroup
            key={group}
            title={APART_WORDS[group].title}
            none={APART_WORDS[group].none}
            group={spend.apart[group]}
          />
        ))}
      </section>
    </div>
  );
}

export function SpendTab({
  rows,
  query,
}: {
  readonly rows: readonly RunRow[];
  readonly query: URLSearchParams;
}) {
  const runs = byKind(rows);
  const chosen = chosenRun(runs, query.get("run"));
  const prices = useJson(PRICES_ROUTE, priceDates);
  const date = prices.result?.ok === true ? newestDate(prices.result.value) : null;
  const route = chosen === undefined || date === null ? null : spendRoute(chosen, date);
  const spend = useJson(route, evidenceSpend);
  if (chosen === undefined) return <EmptyState title={EVIDENCE_COPY.noReadable} icon="wallet" />;
  const chooser = (
    <RunChooser
      label={EVIDENCE_COPY.run}
      runs={runs}
      value={placeKey(chosen)}
      onChoose={(key) => {
        go(evidenceAddress(query, { run: key }));
      }}
    />
  );
  if (prices.result === null) return <LoadingState reading={EVIDENCE_COPY.readingPrices} />;
  if (!prices.result.ok)
    return (
      <ErrorState
        title={EVIDENCE_COPY.pricesRefused}
        {...prices.result.refusal}
        route={prices.route}
        onRetry={prices.again}
      />
    );
  if (date === null)
    return (
      <>
        {chooser}
        <EmptyState title={EVIDENCE_COPY.noSheet} icon="wallet" />
      </>
    );
  return (
    <>
      {chooser}
      <p className="evidence-note">{pricedAtWords(date)}</p>
      {spend.result === null ? (
        <LoadingState reading={EVIDENCE_COPY.readingSpend} />
      ) : spend.result.ok ? (
        <SpendBody spend={spend.result.value} />
      ) : (
        <ErrorState
          title={spendRefusedWords(chosen.name)}
          {...spend.result.refusal}
          route={spend.route}
          onRetry={spend.again}
        />
      )}
    </>
  );
}
