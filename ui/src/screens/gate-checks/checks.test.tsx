// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { RunConfig } from "../../api/records";
import type { GateCheck } from "../../api/run";
import type { GateMode } from "../../design/components/verdict/GateMode";
import { Tally } from "../../design/components/verdict/Tally";
import { tallyOfChecks } from "../../design/tally";
import { ChecksTable, kept } from "./ChecksTable";
import { PairedBody } from "./PairedRun";
import { pairable } from "./pairing";

const SOURCE = { id: "run r-1", commit: "0123456789abcdef" };
const NAMES = new Map([["s1", "Subtask 1"]]);

function check(
  outcome: GateCheck["outcome"],
  mode: "on" | "observe",
  extra: Partial<GateCheck> = {},
): GateCheck {
  return {
    seq: 11,
    subtask: "s1",
    attempt: 1,
    name: "magnitude",
    check: 2,
    ts: null,
    scope: "subtask",
    mode,
    outcome,
    blocking: outcome !== "warn",
    value: outcome === "fail" || outcome === "warn" ? { value: 5, unit: "W" } : null,
    node: outcome === "pass" ? null : "electrical.drive",
    evaluated: outcome === "pass" ? 2 : null,
    reviewerHadPassed: null,
    expected: outcome === "fail" ? "at most 10 W" : null,
    message:
      outcome === "unchecked"
        ? "mass, power_draw of electrical.drive have no sourced range for their domain"
        : "found",
    details: {
      form: outcome,
      evaluated: outcome === "pass" ? 2 : null,
      quantities: outcome === "unchecked" ? ["mass", "power_draw"] : [],
      low: null,
      high: null,
    },
    ...extra,
  };
}

function every(mode: "on" | "observe"): GateCheck[] {
  return [
    check("pass", mode),
    check("pass", mode, {
      name: "equilibrium",
      evaluated: 0,
      details: { form: "pass", evaluated: 0, quantities: [], low: null, high: null },
    }),
    check("fail", mode),
    check("warn", mode),
    check("unchecked", mode),
    check("unchecked", mode),
  ];
}

const table = (checks: GateCheck[]) =>
  renderToStaticMarkup(<ChecksTable checks={checks} names={NAMES} source={SOURCE} />);

describe("unchecked is its own category", () => {
  it("is counted after the separator and never inside the evaluated", () => {
    const html = renderToStaticMarkup(<Tally {...tallyOfChecks(every("on"))} />);
    const [evaluated = "", after = ""] = html.split("pg-tally-sep");
    expect(evaluated).toContain('data-evaluated="4"');
    expect(evaluated).not.toContain("verdict-unchecked");
    expect(after).toContain("verdict-unchecked");
    expect(after).toContain('<span class="pg-tally-n">2</span>');
  });

  it("never reads as a pass, and says why it was left unchecked", () => {
    const html = table([check("unchecked", "on")]);
    expect(html).not.toContain("verdict-pass");
    expect(html).toContain("Mass, power_draw of electrical.drive have no sourced range");
    expect(html).toContain("left unchecked: mass, power_draw");
    expect(html).not.toMatch(/evaluated/);
  });

  it("a pass over nothing says so", () => {
    const html = table(every("on"));
    expect(html).toContain("0 evaluated · a pass over nothing");
    expect(html).toContain('<span class="pg-count">2</span> evaluated');
    expect(renderToStaticMarkup(<Tally {...tallyOfChecks(every("on"))} />)).toMatch(
      /<span class="pg-tally-n">1<\/span> pass over nothing/,
    );
  });

  it("a filter keeps what it names and nothing else", () => {
    expect(kept(every("on"), "unchecked")).toHaveLength(2);
    expect(kept(every("on"), "not-passed")).toHaveLength(4);
    expect(kept(every("on"), "all")).toHaveLength(6);
  });
});

describe("every gate figure shows its mode", () => {
  it("under on a fail is a filled fail", () => {
    expect(table(every("on"))).toContain("pg-verdict-fail");
  });

  it("under observe nothing is a filled pass, fail or warn", () => {
    const html = table(every("observe"));
    expect(html).toContain("Would fail · not enforced");
    expect(html).not.toMatch(/verdict-(pass|fail|warn)/);
  });

  it("each row leads with the check in words, its id after it, and a source", () => {
    const html = table([check("fail", "on")]);
    expect(html.indexOf("Plausible value check")).toBeLessThan(html.indexOf("check 2 · seq 11"));
    expect(html).toContain("Subtask 1 · attempt 1");
    expect(html).toContain("pg-source");
    expect(html).toContain("Reviewer approved before the gate?");
  });
});

describe("a run is read against another only of the same brief and seed", () => {
  function config(runId: string, gateMode: GateMode, brief = "a", seed = 7): RunConfig {
    return {
      manifestId: "m",
      runId,
      gateMode,
      harnessCommit: null,
      auth: "api_key",
      briefSha256: brief,
      seed,
      roleModels: {},
      decompositionModel: null,
      reviewerModels: {},
      osLayer: null,
    };
  }
  const chosen = config("on", "on");
  const all = new Map([
    ["0/on", chosen],
    ["0/observe", config("observe", "observe")],
    ["0/off", config("off", "off")],
    ["0/other-brief", config("ob", "observe", "b")],
    ["0/other-seed", config("os", "observe", "a", 8)],
    ["0/same-mode", config("sm", "on")],
  ]);

  it("offers the same brief and seed in another mode, and nothing else", () => {
    expect(pairable(chosen, all).map(([key]) => key)).toEqual(["0/observe", "0/off"]);
  });

  it("an observe run's counts and outcomes are would-be, never a filled verdict", () => {
    const html = renderToStaticMarkup(
      <PairedBody
        label="Run 1 Oct, 10:00"
        config={config("observe", "observe")}
        checks={every("observe")}
      />,
    );
    expect(html).toContain("Observe · not gated");
    expect(html).toContain("Would fail");
    expect(html).not.toMatch(/verdict-(pass|fail|warn)/);
  });

  it("a gated run's are filled, and a gate-off run shows no result", () => {
    expect(
      renderToStaticMarkup(<PairedBody label="Run" config={chosen} checks={every("on")} />),
    ).toContain("verdict-fail");
    const off = renderToStaticMarkup(
      <PairedBody label="Run" config={config("off", "off")} checks={[]} />,
    );
    expect(off).toContain("pg-gate-off");
    expect(off).toContain("The gate did not run");
  });
});
