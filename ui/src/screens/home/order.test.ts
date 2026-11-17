import { describe, expect, it } from "vitest";

import type { RunListing } from "../../api/records";
import type { Phase } from "../../words/standing";
import { FIRST_RUNS } from "../common/runs";
import { homeOrder, readTargets } from "./data";

const run = (name: string, started: string | null, error: string | null = null): RunListing => ({
  root: 0,
  name,
  runId: name,
  manifestId: "m",
  gateMode: "on",
  osLayer: null,
  error,
  started,
});

/** ``n`` runs, one a day from 1 Nov, the newest last in the list as given. */
const days = (n: number, prefix = "bench-"): RunListing[] =>
  Array.from({ length: n }, (_, i) =>
    run(`${prefix}${String(i + 1)}`, `2026-11-${String(i + 1).padStart(2, "0")}T10:00:00Z`),
  );

const phases = (entries: Record<string, Phase>): ReadonlyMap<string, Phase> =>
  new Map(Object.entries(entries).map(([name, phase]) => [`0/${name}`, phase]));

describe("Home lists the runs that need attention first, then the rest newest first", () => {
  it("going runs first, then runs waiting on a person, then halted or stopped ones, newest first within each, then the rest newest first", () => {
    const runs = days(8);
    const order = homeOrder(
      runs,
      phases({
        "bench-1": "going",
        "bench-5": "going",
        "bench-2": "waiting-person",
        "bench-6": "waiting-person",
        "bench-3": "stopped",
        "bench-4": "halted",
        "bench-7": "done",
        "bench-8": "waiting-limit",
      }),
    );
    expect(order.map((r) => r.name)).toEqual([
      "bench-5",
      "bench-1",
      "bench-6",
      "bench-2",
      "bench-4",
      "bench-3",
      "bench-8",
      "bench-7",
    ]);
  });

  it("a run whose status was not read, or that could not be read, is among the rest, never first", () => {
    const runs = [...days(3), run("bench-broken", null, "its log could not be read")];
    const order = homeOrder(runs, phases({ "bench-1": "going" }));
    expect(order.map((r) => r.name)).toEqual(["bench-1", "bench-3", "bench-2", "bench-broken"]);
  });

  it("a halt owed, a halt taken and a run that appears stopped come after waiting, before the rest", () => {
    const runs = days(6);
    const order = homeOrder(
      runs,
      phases({
        "bench-1": "halt-owed",
        "bench-2": "halted",
        "bench-3": "stopped",
        "bench-4": "waiting-person",
        "bench-5": "done",
        "bench-6": "waiting-limit",
      }),
    );
    expect(order.map((r) => r.name)).toEqual([
      "bench-4",
      "bench-3",
      "bench-2",
      "bench-1",
      "bench-6",
      "bench-5",
    ]);
  });
});

describe("Home's first screen holds every run going or waiting on a person, however old", () => {
  const many = days(FIRST_RUNS + 3);
  const oldest = "bench-1";
  const second = "bench-2";

  it("reads the going run and the waiting run though twelve others started after them", () => {
    const targets = readTargets(
      many,
      false,
      phases({ [oldest]: "going", [second]: "waiting-person" }),
    );
    expect(targets).not.toBeNull();
    const names = (targets ?? []).map((r) => r.name);
    expect(names).toHaveLength(FIRST_RUNS);
    expect(names.slice(0, 2)).toEqual([oldest, second]);
    expect(names.slice(2)).toEqual(
      Array.from({ length: FIRST_RUNS - 2 }, (_, i) => `bench-${String(FIRST_RUNS + 3 - i)}`),
    );
  });

  it("with twelve runs or fewer, reads them all at once, without waiting for any status", () => {
    const few = days(FIRST_RUNS);
    expect((readTargets(few, false, null) ?? []).map((r) => r.name)).toHaveLength(FIRST_RUNS);
  });

  it("asked for all, reads every readable run, attention first", () => {
    const withBroken = [...many, run("bench-broken", null, "refused")];
    const targets = readTargets(withBroken, true, phases({ "bench-3": "going" })) ?? [];
    expect(targets).toHaveLength(many.length);
    expect(targets.slice(0, 2).map((r) => r.name)).toEqual([
      "bench-3",
      `bench-${String(many.length)}`,
    ]);
  });
});
