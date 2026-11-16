/**
 * Two runs compared: a baseline and a candidate, chosen by the person, and the comparison's own
 * side by side, field by field, with the reported settings that differ marked. When a pinned
 * setting differs the comparison is refused, and the screen says so and names each setting in
 * words; it draws no number of either run then, so nothing reads as a difference the settings
 * made.
 */
import { Quantity } from "../../design/components/data/Quantity";
import { sourceAttribute } from "../../design/components/data/source";
import { Icon } from "../../design/components/icons/Icon";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  type Refusal,
} from "../../design/components/status/States";
import { useJson } from "../../screens/common/read";
import {
  byKind,
  type Cell,
  type Comparison,
  compareRoute,
  driftedOf,
  evidenceComparison,
  NUMBER_FIELDS,
  type NumberField,
  parsePlace,
  placeKey,
  type ReadRun,
  RUN_NUMBERS,
  type RunNumbers,
  type RunRow,
} from "./api";
import { evidenceAddress, go } from "./address";
import { RunChooser } from "./Chooser";
import { answerSource, RunMark } from "./parts";
import { driftWords, EVIDENCE_COPY, settingLabel, valueWords } from "./words";

function named(runs: readonly ReadRun[], key: string | null): ReadRun | undefined {
  const wanted = parsePlace(key);
  if (wanted === null) return undefined;
  return runs.find((run) => placeKey(run) === placeKey(wanted));
}

/** One of a run's numbers as shown: tokens and seconds as quantities, the rest as recorded. */
function CellView({ field, value }: { readonly field: NumberField; readonly value: Cell }) {
  if (RUN_NUMBERS[field] === "seconds" && typeof value === "number")
    return <Quantity value={value} unit="s" />;
  if (typeof value === "number") return <>{String(value)}</>;
  if (typeof value === "boolean") return <>{String(value)}</>;
  return <>{valueWords(value)}</>;
}

/** A row of the side by side: a field, or one kind of token of the tokens field. */
interface Line {
  readonly key: string;
  readonly field: NumberField;
  readonly token: string | null;
}

/** The rows of the side by side: each field, and each kind of token on a row of its own. */
function rowsOf(baseline: RunNumbers, candidate: RunNumbers): Line[] {
  return NUMBER_FIELDS.flatMap((field): Line[] => {
    if (RUN_NUMBERS[field] !== "tokens") return [{ key: field, field, token: null }];
    const kinds = new Set([...tokenKeys(baseline[field]), ...tokenKeys(candidate[field])]);
    return [...kinds].map((token) => ({ key: `${field}.${token}`, field, token }));
  });
}

function tokenKeys(value: Cell): string[] {
  return typeof value === "object" && value !== null ? Object.keys(value) : [];
}

function Value({
  run,
  field,
  token,
}: {
  run: RunNumbers;
  field: NumberField;
  token: string | null;
}) {
  const value = run[field];
  if (token === null) return <CellView field={field} value={value} />;
  const n = typeof value === "object" && value !== null ? value[token] : undefined;
  if (n === undefined) return <>{EVIDENCE_COPY.notRecorded}</>;
  return <Quantity value={n} unit="tok" />;
}

function SideBySide({ compared }: { readonly compared: Comparison }) {
  const a = sourceAttribute(answerSource(compared.a));
  const b = sourceAttribute(answerSource(compared.b));
  return (
    <>
      <div className="evidence-marks">
        <span className="evidence-label">{EVIDENCE_COPY.baseline}</span>
        <RunMark source={compared.a} />
        <span className="evidence-label">{EVIDENCE_COPY.candidate}</span>
        <RunMark source={compared.b} />
      </div>
      <p className="evidence-note" data-note="differs">
        {compared.differsIn.length === 0
          ? EVIDENCE_COPY.differsNone
          : `${EVIDENCE_COPY.differsIn} ${compared.differsIn.map(settingLabel).join(", ")}.`}
      </p>
      <div
        className="pg-table-wrap"
        role="region"
        aria-label={EVIDENCE_COPY.compareTab}
        tabIndex={0}
      >
        <table className="pg-table evidence-compare">
          <thead>
            <tr>
              <th scope="col">{EVIDENCE_COPY.setting}</th>
              <th scope="col">{`${EVIDENCE_COPY.baseline}: ${compared.a.name}`}</th>
              <th scope="col">{`${EVIDENCE_COPY.candidate}: ${compared.b.name}`}</th>
            </tr>
          </thead>
          <tbody>
            {rowsOf(compared.baseline, compared.candidate).map(({ key, field, token }) => {
              const differs = compared.differsIn.includes(field);
              return (
                <tr key={key} data-field={key} data-differs={differs ? "true" : undefined}>
                  <th scope="row">
                    <span className="evidence-label">{settingLabel(key)}</span>
                    <span className="pg-id">{key}</span>
                    {differs && <span className="pg-status">{EVIDENCE_COPY.differsTag}</span>}
                  </th>
                  <td data-source={a}>
                    <Value run={compared.baseline} field={field} token={token} />
                  </td>
                  <td data-source={b}>
                    <Value run={compared.candidate} field={field} token={token} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

/** A comparison refused over drifted settings: the sentence and the settings in words, no number. */
function Drifted({ refusal, drifted }: { refusal: Refusal; drifted: readonly string[] }) {
  return (
    <section
      className="pg-state pg-state-error evidence-drifted"
      role="alert"
      aria-label={EVIDENCE_COPY.driftTitle}
    >
      <h2 className="pg-state-title">
        <Icon name="ban" />
        {EVIDENCE_COPY.driftTitle}
      </h2>
      <p className="pg-state-body">{EVIDENCE_COPY.driftLead}</p>
      <ul className="evidence-list">
        {drifted.map((path) => (
          <li key={path} data-drifted={path}>
            {driftWords(path)}
          </li>
        ))}
      </ul>
      <p className="pg-state-body">{refusal.error}</p>
    </section>
  );
}

export function CompareTab({
  rows,
  query,
}: {
  readonly rows: readonly RunRow[];
  readonly query: URLSearchParams;
}) {
  const runs = byKind(rows);
  const a = named(runs, query.get("a"));
  const b = named(runs, query.get("b"));
  const route = a === undefined || b === undefined ? null : compareRoute(a, b);
  const compared = useJson(route, evidenceComparison);
  if (runs.length === 0) return <EmptyState title={EVIDENCE_COPY.noReadable} icon="git-compare" />;
  const choosers = (
    <div className="evidence-choosers">
      <RunChooser
        label={EVIDENCE_COPY.baseline}
        runs={runs}
        value={a === undefined ? null : placeKey(a)}
        onChoose={(key) => {
          go(evidenceAddress(query, { a: key }));
        }}
      />
      <RunChooser
        label={EVIDENCE_COPY.candidate}
        runs={runs}
        value={b === undefined ? null : placeKey(b)}
        onChoose={(key) => {
          go(evidenceAddress(query, { b: key }));
        }}
      />
    </div>
  );
  if (compared.result === null)
    return (
      <>
        {choosers}
        {route === null ? (
          <p className="evidence-note">{EVIDENCE_COPY.chooseTwo}</p>
        ) : (
          <LoadingState reading={EVIDENCE_COPY.readingComparison} />
        )}
      </>
    );
  if (compared.result.ok)
    return (
      <>
        {choosers}
        <SideBySide compared={compared.result.value} />
      </>
    );
  const refusal = compared.result.refusal;
  const drifted = driftedOf(refusal);
  return (
    <>
      {choosers}
      {drifted === null ? (
        <ErrorState
          title={EVIDENCE_COPY.comparisonRefused}
          {...refusal}
          route={compared.route}
          onRetry={compared.again}
        />
      ) : (
        <Drifted refusal={refusal} drifted={drifted} />
      )}
    </>
  );
}
