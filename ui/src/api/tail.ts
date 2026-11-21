/**
 * Following a run's log as it grows. The server answers from the line a page asks for, with how
 * many whole lines the log holds; the page asks again from the last line it holds, which comes
 * back too. That overlap, compared byte for byte, and the unbroken run of sequence numbers after
 * it, are how a page knows it is still following the log it read: then it adds each new line
 * once. Anything else (the log shrank, the overlap differs, a number is skipped) means the log is
 * not the one held, and it is read again from its first line.
 *
 * Only whole lines are taken. The server already stops before a line the writer has not ended;
 * here a last piece without its newline is withheld as well, never parsed, so a half-written line
 * can neither render nor refuse the answer.
 */
import { count, object, text } from "./check";
import { ShapeError } from "./client";
import { type RunEvent, runEvent } from "./events";

/** One answer of the route a page follows a log by. */
export interface LogTail {
  /** How many whole lines the log holds. */
  readonly count: number;
  /** The line the answer starts at. */
  readonly from: number;
  /** The lines from there on, one record per line, each ending in a newline. */
  readonly text: string;
}

export function logTail(value: unknown): LogTail {
  const v = object(value, "a part of a run's log");
  return {
    count: count(v.count, "a count of lines"),
    from: count(v.from, "the line it starts at"),
    text: text(v.lines, "the log's lines"),
  };
}

/** The whole lines of ``body``, each with its newline; a last piece without one is withheld. */
export function wholeLines(body: string): readonly string[] {
  const end = body.lastIndexOf("\n");
  if (end < 0) return [];
  return body
    .slice(0, end + 1)
    .split(/(?<=\n)/)
    .filter((line) => line !== "");
}

/** The lines a page holds: each as served, for the overlap, and as read. */
export interface Followed {
  readonly raw: readonly string[];
  readonly events: readonly RunEvent[];
}

/** What an answer does to the lines held: they grow (perhaps by nothing), or the log is read again. */
export type Step =
  { readonly kind: "grown"; readonly followed: Followed } | { readonly kind: "again" };

/** The record on ``line``, or ``null`` when it is not line number ``seq``. */
function numbered(line: string, seq: number): RunEvent | null {
  let value: unknown;
  try {
    value = JSON.parse(line);
  } catch {
    throw new ShapeError("a run-event line");
  }
  const event = runEvent(value);
  return event.seq === seq ? event : null;
}

/**
 * Join ``tail`` to the lines ``held``: a first read (``held`` null or empty) takes every whole
 * line from the first; a later one, asked from the last line held, adds what follows it.
 *
 * Throws a ``ShapeError`` when a whole line is not a record, or a first read does not start at
 * the first line and run on unbroken: no screen is shown a log in part.
 */
export function follow(held: Followed | null, tail: LogTail): Step {
  const lines = wholeLines(tail.text);
  if (held === null || held.raw.length === 0) {
    if (tail.from !== 0) throw new ShapeError("a run's log from its first line");
    const events = lines.map((line, i) => {
      const event = numbered(line, i);
      if (event === null) throw new ShapeError("a run's log numbered from its first line");
      return event;
    });
    return { kind: "grown", followed: { raw: lines, events } };
  }
  const last = held.raw.length - 1;
  if (tail.from !== last || tail.count < held.raw.length || lines[0] !== held.raw[last])
    return { kind: "again" };
  const added = lines.slice(1);
  if (added.length === 0) return { kind: "grown", followed: held };
  const events: RunEvent[] = [];
  for (const [i, line] of added.entries()) {
    const event = numbered(line, held.raw.length + i);
    if (event === null) return { kind: "again" };
    events.push(event);
  }
  return {
    kind: "grown",
    followed: { raw: [...held.raw, ...added], events: [...held.events, ...events] },
  };
}
