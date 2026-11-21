/**
 * Following a run's log from the last line a page holds: whole lines only, the overlap compared
 * byte for byte, and a log that is not the one held read again from its start.
 */
import { describe, expect, it } from "vitest";

import { type Followed, follow, logTail, wholeLines } from "./tail";

function line(seq: number, kind = "stage_entered_elsewhere"): string {
  return `${JSON.stringify({ seq, ts: `2026-11-20T12:00:${String(seq).padStart(2, "0")}Z`, kind })}\n`;
}

function tail(from: number, lines: readonly string[], count?: number) {
  return { from, count: count ?? from + lines.length, text: lines.join("") };
}

function held(n: number): Followed {
  const first = follow(
    null,
    tail(
      0,
      Array.from({ length: n }, (_, i) => line(i)),
    ),
  );
  if (first.kind !== "grown") throw new Error("the first read did not grow");
  return first.followed;
}

describe("only whole lines are taken from an answer", () => {
  it("a last piece without its newline is withheld", () => {
    expect(wholeLines(`${line(0)}${line(1)}{"seq": 2, "ts"`)).toEqual([line(0), line(1)]);
  });

  it("an answer with no newline at all holds no line", () => {
    expect(wholeLines('{"seq": 0')).toEqual([]);
    expect(wholeLines("")).toEqual([]);
  });

  it("a torn last line is never parsed, so it can never refuse or render", () => {
    const first = follow(null, tail(0, [line(0), line(1), '{"seq": 2, "kin']));
    expect(first.kind).toBe("grown");
    if (first.kind !== "grown") return;
    expect(first.followed.events.map((e) => e.seq)).toEqual([0, 1]);
    expect(first.followed.raw).toEqual([line(0), line(1)]);
  });
});

describe("an answer is joined to the lines held after its overlap", () => {
  it("the first read takes every whole line from the first", () => {
    expect(held(3).events.map((e) => e.seq)).toEqual([0, 1, 2]);
  });

  it("a later read adds only the lines after the overlap, each once", () => {
    const step = follow(held(3), tail(2, [line(2), line(3), line(4)]));
    expect(step.kind).toBe("grown");
    if (step.kind !== "grown") return;
    expect(step.followed.events.map((e) => e.seq)).toEqual([0, 1, 2, 3, 4]);
  });

  it("an answer with nothing new keeps the lines held as they are", () => {
    const before = held(3);
    const step = follow(before, tail(2, [line(2)]));
    expect(step).toEqual({ kind: "grown", followed: before });
  });

  it("an overlap that is not the line held, byte for byte, reads the log again from its start", () => {
    const other = `${JSON.stringify({ seq: 2, ts: "2026-11-21T00:00:00Z", kind: "x" })}\n`;
    expect(follow(held(3), tail(2, [other, line(3)]))).toEqual({ kind: "again" });
  });

  it("an answer from another line than the last held reads the log again", () => {
    expect(follow(held(3), tail(1, [line(1), line(2), line(3)]))).toEqual({ kind: "again" });
  });

  it("a log that shrank reads again from its start", () => {
    expect(follow(held(3), tail(2, [], 2))).toEqual({ kind: "again" });
  });

  it("a gap in the sequence after the overlap reads again from its start", () => {
    expect(follow(held(3), tail(2, [line(2), line(4)]))).toEqual({ kind: "again" });
  });

  it("a first read that does not start at the first line is refused", () => {
    expect(() => follow(null, tail(1, [line(1)]))).toThrow();
  });

  it("a first read whose lines skip a number is refused", () => {
    expect(() => follow(null, tail(0, [line(0), line(2)]))).toThrow();
  });

  it("a whole line that is not a record refuses the answer", () => {
    expect(() => follow(null, tail(0, [line(0), "not json\n"]))).toThrow();
  });
});

describe("the route's answer is held to its shape", () => {
  it("takes the count, the first line asked and the lines", () => {
    expect(logTail({ count: 2, from: 1, lines: line(1) })).toEqual({
      count: 2,
      from: 1,
      text: line(1),
    });
  });

  it("refuses an answer without its lines as text", () => {
    expect(() => logTail({ count: 2, from: 1, lines: [line(1)] })).toThrow();
    expect(() => logTail({ count: -1, from: 0, lines: "" })).toThrow();
  });
});
