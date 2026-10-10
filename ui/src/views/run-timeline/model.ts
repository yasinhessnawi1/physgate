/**
 * The run timeline's lanes, built from the run's own records: the trace (stages and sessions,
 * in the log's order), the decision sequence and a few event lines. Nothing is re-ordered here:
 * lanes and segments come in the order the records give them. The only arithmetic is where a
 * segment sits on the screen, from the log's own timestamps; no figure is computed.
 */
import type { Decision, SessionTrace, StepTiming, TimelineEvents, Trace } from "../../api/run";
import type { GateMode } from "../../design/components/GateMode";

export type SegmentKind = "session" | "infrastructure" | "gate" | "review";

export interface Segment {
  readonly kind: SegmentKind;
  /** The class the design draws it with: by kind, and for a gate or a review by its result. */
  readonly tone: string;
  readonly start: string;
  /** From the record: the stage's or the session's own duration. ``null`` when none is recorded. */
  readonly seconds: number | null;
  readonly label: string;
  /** More than the label has room for: the session's id, for one. Shown in the title. */
  readonly title?: string;
}

export interface Marker {
  readonly at: string;
  readonly label: string;
  readonly tone: string;
}

export interface Lane {
  readonly key: string;
  readonly title: string;
  readonly subtitle: string;
  readonly segments: readonly Segment[];
  readonly markers: readonly Marker[];
}

/** Milliseconds since the epoch of a log timestamp (``2026-10-10T12:00:00.123456Z``). */
export function at(ts: string): number {
  return Date.parse(ts.replace(/(\.\d{3})\d*Z$/, "$1Z"));
}

/** A finding key (``source|subject|check``) as words: who refused it, and by which check. */
export function findingLabel(key: string): string {
  const [source = key, subject = "-", check = "-"] = key.split("|");
  return check !== "-"
    ? `${source} · ${check}`
    : subject !== "-"
      ? `${source} · ${subject}`
      : source;
}

function gateTone(mode: GateMode, verdict: string | null, skipped: boolean): [string, string] {
  if (skipped || mode === "off") return ["segment-gate-off", "gate skipped · gate off"];
  if (mode === "observe")
    return [
      "segment-gate-observe",
      verdict === "fail" ? "would fail · not enforced" : "would pass · not enforced",
    ];
  return ["segment-gate-on", verdict === "fail" ? "gate · fail" : "gate · pass"];
}

/** The lanes of a run: decomposition, then each attempt in the log's order, then integration. */
export function lanes(
  trace: Trace,
  decisions: readonly Decision[],
  events: TimelineEvents,
  mode: GateMode,
  roleModels: Readonly<Record<string, string>>,
): readonly Lane[] {
  const found: Lane[] = [];
  if (events.decomposed !== null) {
    const d = events.decomposed;
    found.push({
      key: "decomposition",
      title: "Decomposition",
      subtitle: `brief → ${String(d.subtasks)} ${d.subtasks === 1 ? "subtask" : "subtasks"} · ${d.model}`,
      segments: [],
      markers: [{ at: d.ts, label: "decompose", tone: "marker-decompose" }],
    });
  }
  const attempts: [string, number][] = [];
  for (const step of trace.steps) {
    if (!attempts.some(([s, a]) => s === step.subtask && a === step.attempt))
      attempts.push([step.subtask, step.attempt]);
  }
  for (const [subtask, attempt] of attempts) {
    const steps: StepTiming[] = trace.steps.filter(
      (s) => s.subtask === subtask && s.attempt === attempt,
    );
    const spawns = steps.filter((s) => s.stage === "spawn");
    const sessions: SessionTrace[] = trace.sessions.filter(
      (s) => s.subtask === subtask && s.attempt === attempt,
    );
    const segments: Segment[] = sessions.map((session, i) => {
      const spawn = spawns[i];
      const infrastructure = session.outcome === "infrastructure";
      return {
        kind: infrastructure ? "infrastructure" : "session",
        tone: infrastructure ? "segment-infrastructure" : "segment-session",
        start: spawn?.entered ?? steps[0]?.entered ?? trace.started,
        seconds: session.wallClockS,
        label: infrastructure
          ? `infrastructure · ${session.cause ?? "no cause recorded"}`
          : `session ${String(i + 1)}`,
        title: session.sessionId,
      };
    });
    const ofAttempt = (d: Decision) => d.subtask === subtask && d.attempt === attempt;
    for (const step of steps.filter((s) => s.stage === "gate")) {
      const decided = decisions.find((d) => ofAttempt(d) && d.step === "gate" && d.seq > step.seq);
      const skipped = events.gateSkipped.some(
        (g) => g.subtask === subtask && g.attempt === attempt,
      );
      const [tone, label] = gateTone(mode, decided?.verdict ?? null, skipped);
      segments.push({ kind: "gate", tone, start: step.entered, seconds: step.seconds, label });
    }
    for (const step of steps.filter((s) => s.stage === "review")) {
      const review = events.reviews.find(
        (r) => r.subtask === subtask && r.attempt === attempt && r.seq > step.seq,
      );
      const verdict = review?.verdict ?? "no verdict";
      segments.push({
        kind: "review",
        tone: `segment-review-${verdict === "pass" || verdict === "fail" ? verdict : "other"}`,
        start: step.entered,
        seconds: step.seconds,
        label: `review · ${verdict}`,
      });
    }
    const role = events.roles[subtask];
    const model = role === undefined ? undefined : roleModels[role];
    const before = events.rejections.find(
      (r) => r.subtask === subtask && r.attempt === attempt - 1,
    );
    const ended = decisions.filter(
      (d) => d.subtask === subtask && (d.attempt === attempt || d.attempt === null),
    );
    const end =
      ended.find((d) => d.step === "merged" && d.attempt === attempt) ??
      ended.find((d) => d.step === "rejected" && d.attempt === attempt) ??
      ended.find((d) => d.step === "escalated");
    const outcome =
      end === undefined
        ? ""
        : end.step === "rejected"
          ? ` · rejected: ${findingLabel(end.findingKey ?? "")}`
          : ` · ${end.step}`;
    found.push({
      key: `${subtask}/${String(attempt)}`,
      title: subtask,
      subtitle:
        `attempt ${String(attempt)}${model === undefined ? "" : ` · ${model}`}` +
        (before === undefined ? "" : ` · repair of ${findingLabel(before.findingKey)}`) +
        outcome,
      segments,
      markers: [],
    });
  }
  if (events.integration !== null) {
    const i = events.integration;
    found.push({
      key: "integration",
      title: "Integration",
      subtitle:
        i.kind === "ran"
          ? `gate on the whole design · ${mode === "observe" ? `would ${i.verdict ?? ""} · not enforced` : (i.verdict ?? "")}`
          : `not gated · ${i.reason ?? ""}`,
      segments: [],
      markers: [{ at: i.ts, label: "integrate", tone: "marker-integrate" }],
    });
  }
  return found;
}

/** Where ``ts`` sits between the run's first and last line, as a share of the width. */
export function position(ts: string, started: string, last: string): number {
  const span = at(last) - at(started);
  if (span <= 0) return 0;
  return Math.min(Math.max((at(ts) - at(started)) / span, 0), 1);
}
