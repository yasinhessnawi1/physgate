/**
 * The system the chosen run recorded: its engine facts, its builder and reviewer pairs, its gate
 * and queue, its OS layer and network, and its session limits, under the run's own source. Every
 * value is that run's, read field by field; a field the run did not record says so, and a field
 * that could not be read says so in its own row, never emptying the rest.
 */
import type { RecordedModels, RecordedOsLayer, RecordedSystem } from "../../api/settings";
import { Id } from "../../design/components/data/Id";
import { Quantity } from "../../design/components/data/Quantity";
import { SourceChip } from "../../design/components/data/SourceChip";
import { type Source, sourceAttribute } from "../../design/components/data/source";
import { Term } from "../../design/components/help/Term";
import { DataTable } from "../../design/components/layout/DataTable";
import { EmptyState, ErrorState, LoadingState } from "../../design/components/status/States";
import { StatusTag } from "../../design/components/status/StatusTag";
import { OsLayerBadge } from "../../design/components/system/OsLayerBadge";
import { type GateMode, GateModeBadge } from "../../design/components/verdict/GateMode";
import { hrefFor } from "../../shell/route";
import { quantityLabel } from "../../words/humanise";
import {
  AUTH_WORDS,
  DESIGN_REVIEW_WORDS,
  EFFORT_WORDS,
  NETWORK_WORDS,
  networkWords,
  OS_LAYER_ABSENT_WORDS,
  OS_LAYER_STATE_WORDS,
  QUEUE_DECISION_WORDS,
  SETTINGS_COPY as C,
  THINKING_WORDS,
  wordsFor,
} from "../../words/settings";
import { EngineWords } from "../common/engine";
import { RunSwitcher } from "../common/RunSwitcher";
import { runKey } from "../common/runs";
import { Fact, Refused, Shown, Words } from "./FieldView";
import { pairKind, type PairRow, pairRows } from "./pairs";
import type { RecordedRun } from "./useRecordedRun";

const AREA = "home";
const SLUG = "settings";

export function isGateMode(value: string): value is GateMode {
  return value === "on" || value === "observe" || value === "off";
}

/** The run's source: its id and its harness commit, each left out where it was not read. */
export function sourceOf(system: RecordedSystem): Source | null {
  if (system.runId.kind !== "read") return null;
  return {
    id: `run ${system.runId.value}`,
    commit: system.harnessCommit.kind === "read" ? system.harnessCommit.value : null,
  };
}

function Mono({ children }: { readonly children: string }) {
  return <span className="mono">{children}</span>;
}

function OsLayerValue({ layer }: { readonly layer: RecordedOsLayer }) {
  if (layer.kind === "present")
    return layer.mechanism === "seatbelt" || layer.mechanism === "bubblewrap" ? (
      <OsLayerBadge layer={{ state: "present", mechanism: layer.mechanism }} />
    ) : (
      <>
        {OS_LAYER_STATE_WORDS.present} ·{" "}
        <span className="mono pg-as-written">{layer.mechanism}</span>
      </>
    );
  if (layer.kind === "absent")
    return (
      <>
        <OsLayerBadge
          layer={{ state: "absent", reason: layer.reason, noOsProtection: layer.noOsProtection }}
        />{" "}
        <span className="pg-os-reason">{layer.reason}</span>
      </>
    );
  return <span className="mono pg-as-written">{layer.state}</span>;
}

function EngineFacts({ system }: { readonly system: RecordedSystem }) {
  return (
    <section className="pg-card pg-panel" aria-label={C.engineGroup}>
      <h3 className="pg-panel-title">{C.engineGroup}</h3>
      <dl className="pg-facts">
        <Fact field="auth" label={C.credential}>
          <Shown field={system.auth}>{(v) => <Words worded={wordsFor(AUTH_WORDS, v)} />}</Shown>
        </Fact>
        <Fact field="endpoint" label={<Term term="endpoint">{C.endpoint}</Term>}>
          <Shown field={system.endpoint}>
            {(v) =>
              v === "default" ? C.endpointDefault : <span className="mono pg-as-written">{v}</span>
            }
          </Shown>
        </Fact>
        <Fact field="claude-version" label={C.claudeVersion}>
          <Shown field={system.claudeVersion}>{(v) => <Mono>{v}</Mono>}</Shown>
        </Fact>
        <Fact field="effort" label={<Term term="effort">{C.effort}</Term>}>
          <Shown field={system.effort}>{(v) => <Words worded={wordsFor(EFFORT_WORDS, v)} />}</Shown>
        </Fact>
        <Fact field="max-output-tokens" label={C.outputLimit}>
          <Shown field={system.maxOutputTokens}>{(q) => <Quantity {...q} />}</Shown>
        </Fact>
        <Fact field="thinking-display" label={C.thinking}>
          <Shown field={system.thinkingDisplay}>
            {(v) => <Words worded={wordsFor(THINKING_WORDS, v)} />}
          </Shown>
        </Fact>
        <Fact field="git-binary" label={C.git}>
          <Shown field={system.gitBinary}>
            {(git) => (
              <>
                <Mono>{git.version}</Mono> · <Mono>{git.path}</Mono>
              </>
            )}
          </Shown>
        </Fact>
        <Fact field="role-python" label={C.python}>
          <Shown field={system.rolePython} none={C.pythonNone}>
            {(python) => (
              <>
                <Mono>{python.path}</Mono> · <Mono>{python.version}</Mono>
                {python.resolved !== python.path && (
                  <>
                    {" "}
                    · {C.resolvesTo} <Mono>{python.resolved}</Mono>
                  </>
                )}
              </>
            )}
          </Shown>
        </Fact>
        <Fact field="engine" label={<Term term="engine">{C.engineItself}</Term>}>
          {system.auth.kind === "read" ? (
            <EngineWords auth={system.auth.value} />
          ) : (
            <span className="pg-muted">{C.notRecorded}</span>
          )}
        </Fact>
      </dl>
    </section>
  );
}

function ModelCell({ model, none }: { readonly model: PairRow["builder"]; readonly none: string }) {
  if (model === null) return <span className="pg-muted">{none}</span>;
  return <Shown field={model}>{(m) => <Mono>{m}</Mono>}</Shown>;
}

function PairCell({ row }: { readonly row: PairRow }) {
  const { builder, reviewer } = row;
  if (builder?.kind !== "read" || reviewer?.kind !== "read")
    return <span className="pg-muted">{C.nothingToCompare}</span>;
  return <StatusTag status={pairKind(builder.value, reviewer.value)} />;
}

function Pairs({ models }: { readonly models: RecordedModels }) {
  return (
    <>
      {models.roles.kind === "refused" && <Refused reason={models.roles.reason} />}
      {models.roles.kind === "absent" && (
        <p className="pg-muted">
          {C.columnRole}: {C.notRecorded}
        </p>
      )}
      <DataTable<PairRow>
        label={C.pairsTitle}
        rows={pairRows(models)}
        rowKey={(row) => row.key}
        columns={[
          {
            key: "role",
            label: C.columnRole,
            wrap: true,
            render: (row) =>
              row.kind === "decomposition" ? (
                C.decomposition
              ) : row.kind === "role" ? (
                <>
                  {quantityLabel(row.name)} <Id value={row.name} copy={false} />
                </>
              ) : (
                <Id value={row.name} copy={false} />
              ),
          },
          {
            key: "builder",
            label: C.columnBuilder,
            render: (row) =>
              row.builder === null ? "" : <ModelCell model={row.builder} none="" />,
          },
          {
            key: "reviewer",
            label: C.columnReviewer,
            wrap: true,
            render: (row) => (
              <>
                <ModelCell
                  model={row.reviewer}
                  none={row.kind === "decomposition" ? C.noPlanReviewer : C.noReviewer}
                />
                {row.kind === "unpaired" && (
                  <>
                    {" "}
                    <span className="pg-muted">{C.unknownReviewerKey}</span>
                  </>
                )}
              </>
            ),
          },
          { key: "pair", label: C.columnPair, wrap: true, render: (row) => <PairCell row={row} /> },
        ]}
      />
    </>
  );
}

function PairsCard({ system }: { readonly system: RecordedSystem }) {
  return (
    <section className="pg-card pg-panel pg-pairs" aria-label={C.pairsTitle}>
      <h3 className="pg-panel-title">{C.pairsTitle}</h3>
      <p className="pg-panel-note pg-pairs-note">{C.pairsNote}</p>
      <Shown field={system.models}>{(models) => <Pairs models={models} />}</Shown>
    </section>
  );
}

function GateFacts({ system }: { readonly system: RecordedSystem }) {
  return (
    <section className="pg-card pg-panel" aria-label={C.gateGroup}>
      <h3 className="pg-panel-title">{C.gateGroup}</h3>
      <dl className="pg-facts">
        <Fact field="gate-mode" label={C.gateMode}>
          <Shown field={system.gateMode}>
            {(mode) =>
              isGateMode(mode) ? (
                <>
                  <GateModeBadge mode={mode} />
                  {mode === "observe" && (
                    <>
                      {" "}
                      <Term term="observe">{C.observeMeans}</Term>
                    </>
                  )}
                </>
              ) : (
                <span className="mono pg-as-written">{mode}</span>
              )
            }
          </Shown>
        </Fact>
        <Fact field="design-review" label={<Term term="plan-reviewer">{C.planReview}</Term>}>
          <Shown field={system.designReview}>
            {(v) => <Words worded={wordsFor(DESIGN_REVIEW_WORDS, v)} />}
          </Shown>
        </Fact>
        <Fact field="queue-decisions" label={C.queueDecisions}>
          <Shown field={system.queueDecisions}>
            {(v) => <Words worded={wordsFor(QUEUE_DECISION_WORDS, v)} />}
          </Shown>
        </Fact>
        <Fact field="escalation" label={C.escalation}>
          <Shown field={system.escalationBackend}>{(v) => <Mono>{v}</Mono>}</Shown>
        </Fact>
      </dl>
    </section>
  );
}

function NetworkValue({ system }: { readonly system: RecordedSystem }) {
  const enforced = system.networkEnforced;
  return (
    <Shown field={system.network}>
      {(network) =>
        enforced.kind === "refused" ? (
          <>
            <Words worded={wordsFor(NETWORK_WORDS, network)} /> <Refused reason={enforced.reason} />
          </>
        ) : (
          <Words
            worded={networkWords(
              network,
              enforced.kind === "read" ? enforced.value : enforced.missing ? undefined : null,
            )}
          />
        )
      }
    </Shown>
  );
}

function LayerFacts({ system }: { readonly system: RecordedSystem }) {
  return (
    <section className="pg-card pg-panel" aria-label={C.osLayerGroup}>
      <h3 className="pg-panel-title">{C.osLayerGroup}</h3>
      <dl className="pg-facts">
        <Fact field="os-layer" label={<Term term="os-layer">{C.osLayer}</Term>}>
          {system.osLayer.kind === "absent" && !system.osLayer.missing ? (
            <OsLayerBadge layer={null} />
          ) : (
            <Shown field={system.osLayer}>{(layer) => <OsLayerValue layer={layer} />}</Shown>
          )}
        </Fact>
        <Fact field="os-layer-absent" label={C.withoutLayer}>
          <Shown field={system.osLayerAbsent}>
            {(v) => <Words worded={wordsFor(OS_LAYER_ABSENT_WORDS, v)} />}
          </Shown>
        </Fact>
        <Fact field="network" label={C.network}>
          <NetworkValue system={system} />
        </Fact>
      </dl>
    </section>
  );
}

function LimitFacts({ system, run }: { readonly system: RecordedSystem; readonly run: string }) {
  const { bounds } = system;
  return (
    <section className="pg-card pg-panel" aria-label={C.limitsGroup}>
      <h3 className="pg-panel-title">
        <Term term="session-limits">{C.limitsGroup}</Term>
      </h3>
      <dl className="pg-facts">
        <Fact field="token-ceiling" label={<Term term="token-ceiling">{C.tokenCeiling}</Term>}>
          <Shown field={system.tokenCeiling}>{(q) => <Quantity {...q} />}</Shown>
        </Fact>
        <Fact field="wall-clock" label={C.wallClock}>
          <Shown field={bounds}>
            {(b) => <Shown field={b.wallClock}>{(q) => <Quantity {...q} />}</Shown>}
          </Shown>
        </Fact>
        <Fact field="turns" label={C.turns}>
          <Shown field={bounds}>
            {(b) => <Shown field={b.maxTurns}>{(q) => <Quantity {...q} />}</Shown>}
          </Shown>
        </Fact>
        <Fact field="retries" label={C.retries}>
          <Shown field={bounds}>
            {(b) => <Shown field={b.maxRetries}>{(q) => <Quantity {...q} />}</Shown>}
          </Shown>
        </Fact>
        <Fact field="delays" label={C.delays}>
          <Shown field={bounds}>
            {(b) => (
              <Shown field={b.retryDelays}>
                {(delays) =>
                  delays.length === 0 ? (
                    <span className="pg-muted">{C.noDelays}</span>
                  ) : (
                    <span className="pg-delays">
                      {delays.map((delay, i) => (
                        <span key={String(i)}>
                          {i > 0 && ", "}
                          <Shown field={delay}>{(q) => <Quantity {...q} />}</Shown>
                        </span>
                      ))}
                    </span>
                  )
                }
              </Shown>
            )}
          </Shown>
        </Fact>
        <Fact field="reportable" label={C.reportable}>
          <Shown field={system.reportable}>{(v) => (v ? C.reportableYes : C.reportableNo)}</Shown>
        </Fact>
      </dl>
      <p className="pg-panel-note">
        <a
          className="pg-full-record"
          href={hrefFor("home", "run-records", new URLSearchParams({ run }))}
        >
          {C.fullRecord}
        </a>
      </p>
    </section>
  );
}

function Recorded({ system, run }: { readonly system: RecordedSystem; readonly run: string }) {
  const source = sourceOf(system);
  return (
    <div
      className="pg-system"
      data-source={source === null ? "no source" : sourceAttribute(source)}
    >
      <SourceChip id={source?.id ?? null} commit={source?.commit ?? null} />
      <EngineFacts system={system} />
      <PairsCard system={system} />
      <GateFacts system={system} />
      <LayerFacts system={system} />
      <LimitFacts system={system} run={run} />
    </div>
  );
}

export function SystemSection({ run }: { readonly run: RecordedRun }) {
  const { runs, chosen, config } = run;
  let body;
  if (runs === null) body = <LoadingState reading={C.runListLoading} />;
  else if (!runs.ok)
    body = <ErrorState title={C.runListError} {...runs.refusal} route="/api/runs" />;
  else if (runs.value.length === 0)
    body = <EmptyState title={C.systemEmpty}>{C.systemEmptyBody}</EmptyState>;
  else if (run.choosing) body = <LoadingState reading={C.systemLoading} />;
  else
    body = (
      <>
        <RunSwitcher
          runs={runs.value}
          chosen={chosen}
          labels={run.labels}
          area={AREA}
          slug={SLUG}
          allShown={run.allShown}
          showAll={run.showAll}
        />
        {chosen === undefined ? (
          <EmptyState title={C.noReadableRun}>{C.noReadableRunBody}</EmptyState>
        ) : config.result === null ? (
          <LoadingState reading={C.systemLoading} />
        ) : !config.result.ok ? (
          <ErrorState
            title={C.systemError}
            {...config.result.refusal}
            route={config.route}
            onRetry={config.again}
          />
        ) : (
          <Recorded system={config.result.value} run={runKey(chosen)} />
        )}
      </>
    );
  return (
    <section className="pg-card pg-panel pg-system-section" aria-label={C.systemTitle}>
      <h2 className="pg-panel-title">{C.systemTitle}</h2>
      {body}
    </section>
  );
}
