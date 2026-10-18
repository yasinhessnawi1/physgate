/**
 * One attempt, inspected: who made it and with which model, its sessions with each
 * trajectory's seal as the server finds it, the gate's checks of it (unchecked after the
 * separator), its reviews, and, for each check that failed, the gate's own message with the
 * recorded value and bound. "Repairs used up" is said only where the queue recorded it.
 */
import type { Result } from "../../api/client";
import { getLines } from "../../api/client";
import type { RunEvent } from "../../api/events";
import type { QueueListing } from "../../api/queue";
import type { RunConfig } from "../../api/records";
import type { GateCheck, Trace } from "../../api/run";
import { Id } from "../../design/components/data/Id";
import { Quantity } from "../../design/components/data/Quantity";
import { SourceChip } from "../../design/components/data/SourceChip";
import { sourceAttribute } from "../../design/components/data/source";
import { Term } from "../../design/components/help/Term";
import { Inspector, InspectorSection } from "../../design/components/layout/Inspector";
import { ErrorState, LoadingState } from "../../design/components/status/States";
import { StatusTag } from "../../design/components/status/StatusTag";
import { GateOutcome } from "../../design/components/verdict/GateMode";
import { Tally } from "../../design/components/verdict/Tally";
import { VerdictBadge } from "../../design/components/verdict/VerdictBadge";
import { tallyOfChecks } from "../../design/tally";
import { agentOf } from "../../words/actors";
import { ActorTag } from "../common/ActorTag";
import { Bound, CheckName, checkId, Measured, sentenceOf } from "../common/checks";
import { useResult } from "../common/useResult";
import { runSource } from "../common/runs";
import { gateReading, readingWords } from "./gate";

function Seal({ base, session }: { readonly base: string; readonly session: string }) {
  const read = useResult(
    () => getLines(`${base}/trajectories/${encodeURIComponent(session)}`, (v) => v),
    `${base}/trajectories/${session}`,
  );
  if (read === null) return <span className="pg-muted">Checking the seal…</span>;
  if (read.ok) return <StatusTag status="seal-holds" />;
  const none = read.refusal.error.includes("no sealed trajectory");
  return (
    <span className="pg-seal-refused" title={read.refusal.error}>
      <StatusTag status={none ? "seal-none" : "seal-tampered"} />
    </span>
  );
}

export function AttemptInspector({
  base,
  config,
  subtask,
  attempt,
  name,
  role,
  runLabel,
  events,
  checks,
  trace,
  queue,
}: {
  readonly base: string;
  readonly config: RunConfig;
  readonly subtask: string;
  readonly attempt: number;
  readonly name: string;
  readonly role: string | undefined;
  readonly runLabel: string;
  readonly events: readonly RunEvent[];
  readonly checks: readonly GateCheck[];
  readonly trace: Result<Trace> | null;
  readonly queue: Result<QueueListing> | null;
}) {
  const source = runSource(config);
  const mine = checks.filter((c) => c.subtask === subtask && c.attempt === attempt);
  const judged = mine.filter((c) => c.outcome !== "unchecked");
  const unchecked = mine.filter((c) => c.outcome === "unchecked");
  const failed = mine.filter((c) => c.outcome === "fail");
  const skipped = events.some(
    (e) => e.kind === "gate_skipped" && e.subtask === subtask && e.attempt === attempt,
  );
  const reading = gateReading(config.gateMode, mine, skipped);
  const reviews = events.flatMap((e) =>
    e.kind === "review_ran" && e.subtask === subtask && e.attempt === attempt ? [e] : [],
  );
  const lastAttempt = Math.max(
    0,
    ...events.flatMap((e) =>
      "attempt" in e && "subtask" in e && e.subtask === subtask ? [e.attempt] : [],
    ),
  );
  // Said only where the queue recorded it: the budget itself is a harness constant, not a record.
  const usedUp =
    queue?.ok === true &&
    attempt === lastAttempt &&
    queue.value.open.some((i) => i.subtaskId === subtask && i.source === "repair_budget_exhausted");
  const sessions =
    trace?.ok === true
      ? trace.value.sessions.filter((s) => s.subtask === subtask && s.attempt === attempt)
      : [];
  return (
    <Inspector
      label="Attempt inspector"
      crumbs={[runLabel, name, `Attempt ${String(attempt)}`]}
      title={`${name} · attempt ${String(attempt)}${usedUp ? " · repairs used up" : ""}`}
      badges={<Id value={subtask} />}
    >
      <div data-source={sourceAttribute(source)}>
        <InspectorSection label="Attempt">
          <dl className="pg-facts">
            <dt>Agent</dt>
            <dd>
              {role === undefined ? (
                <span className="pg-muted">no role recorded</span>
              ) : (
                <ActorTag actor={agentOf(role, config.roleModels[role])} size="sm" />
              )}
            </dd>
            <dt>
              <Term term="attempt">Attempt</Term>
            </dt>
            <dd>
              Attempt {attempt}
              {usedUp ? " · repairs used up" : ""}
            </dd>
            <dt>Gate</dt>
            <dd>{readingWords(reading)}</dd>
          </dl>
        </InspectorSection>
        <InspectorSection label="Sessions">
          {trace === null ? (
            <LoadingState reading="the run's trace" rows={1} />
          ) : !trace.ok ? (
            <ErrorState title="The sessions could not be read" {...trace.refusal} />
          ) : sessions.length === 0 ? (
            <p className="pg-muted">No session of this attempt is recorded.</p>
          ) : (
            <ul className="pg-list">
              {sessions.map((s) => (
                <li key={s.sessionId} className="pg-list-row">
                  <span className="pg-list-row-main">
                    <span>
                      {s.outcome === "completed"
                        ? "Session ended"
                        : `Session ended as ${s.outcome}`}
                      {s.cause === null ? "" : ` (${s.cause})`}
                      {s.wallClockS !== null && (
                        <>
                          {" after "}
                          <Quantity value={s.wallClockS} unit="s" />
                        </>
                      )}
                    </span>
                    <Id value={s.sessionId} />
                  </span>
                  <Seal base={base} session={s.sessionId} />
                </li>
              ))}
            </ul>
          )}
          <p className="pg-panel-note">
            A <Term term="sealed">sealed</Term> transcript is read whole and matched to its digest.
          </p>
        </InspectorSection>
        <InspectorSection label="Gate checks">
          {config.gateMode === "off" || skipped ? (
            <p className="pg-muted">The gate did not run on this attempt.</p>
          ) : mine.length === 0 ? (
            <p className="pg-muted">No gate check is recorded for this attempt.</p>
          ) : (
            <>
              <Tally {...tallyOfChecks(mine)} observed={config.gateMode === "observe"} compact />
              <ul className="pg-list">
                {judged.map((c, i) => (
                  <li key={`j${String(i)}`} className="pg-list-row">
                    <span className="pg-list-row-main">
                      <CheckName check={c} />
                      <Id value={checkId(c)} copy={false} />
                    </span>
                    <GateOutcome mode={c.mode} outcome={c.outcome} />
                  </li>
                ))}
              </ul>
              {unchecked.length > 0 && (
                <>
                  <hr className="pg-sep" />
                  <ul className="pg-list" aria-label="Unchecked">
                    {unchecked.map((c, i) => (
                      <li key={`u${String(i)}`} className="pg-list-row">
                        <span className="pg-list-row-main">
                          <CheckName check={c} />
                          <Id value={checkId(c)} copy={false} />
                        </span>
                        <VerdictBadge verdict="unchecked" />
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </>
          )}
        </InspectorSection>
        <InspectorSection label="Reviews">
          {reviews.length === 0 ? (
            <p className="pg-muted">
              Not run: no reviewer saw this attempt
              {reading.kind === "judged" && reading.outcome === "fail" && reading.mode === "on"
                ? ", because the gate failed it first."
                : "."}
            </p>
          ) : (
            <ul className="pg-list">
              {reviews.map((r) => (
                <li key={r.seq} className="pg-list-row">
                  <span className="pg-list-row-main">
                    <span>{r.finding ?? "No finding recorded"}</span>
                    {r.reviewerModel !== null && (
                      <span className="pg-panel-note mono">{r.reviewerModel}</span>
                    )}
                  </span>
                  {r.verdict === "pass" || r.verdict === "fail" ? (
                    <VerdictBadge verdict={r.verdict} />
                  ) : (
                    <span className="pg-status">Review: {r.verdict}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </InspectorSection>
        {failed.length > 0 && (
          <InspectorSection
            label={config.gateMode === "observe" ? "Why it would have failed" : "Why it failed"}
          >
            <ul className="pg-list">
              {failed.map((c, i) => (
                <li key={`f${String(i)}`} className="pg-why-item">
                  <p className="pg-why">{sentenceOf(c.message)}</p>
                  <dl className="pg-facts">
                    <dt>Check</dt>
                    <dd>
                      <CheckName check={c} />
                    </dd>
                    <dt>Measured</dt>
                    <dd>
                      <Measured check={c} />
                    </dd>
                    <dt>Bound</dt>
                    <dd>
                      <Bound check={c} />
                    </dd>
                  </dl>
                  <span className="pg-figure-line">
                    <Id value={checkId(c)} copy={false} />
                    <SourceChip {...source} />
                  </span>
                </li>
              ))}
            </ul>
          </InspectorSection>
        )}
      </div>
    </Inspector>
  );
}
