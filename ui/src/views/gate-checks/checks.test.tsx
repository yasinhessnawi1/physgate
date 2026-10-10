import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { RunConfig } from "../../api/records";
import type { GateCheck } from "../../api/run";
import type { GateMode } from "../../design/components/GateMode";
import { GateChecksSummary } from "./GateChecksSummary";
import { GateChecksTable } from "./GateChecksTable";
import { PairedBody, pairedWhere } from "./PairedRun";
import { pairable } from "./pairing";

const SOURCE = { id: "run r-1", commit: "0123456789abcdef" };

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

function summary(mode: GateMode, checks: GateCheck[]) {
  return renderToStaticMarkup(
    <GateChecksSummary checks={checks} mode={mode} source={SOURCE} manifestId={"m".repeat(64)}>
      <GateChecksTable checks={checks} />
    </GateChecksSummary>,
  );
}

describe("unchecked is its own category", () => {
  const html = summary("on", every("on"));

  it("is counted after the separator and never inside the evaluated", () => {
    const evaluated = html.slice(html.indexOf("tally-evaluated"), html.indexOf("tally-separator"));
    expect(evaluated).toContain('data-evaluated="4"');
    expect(evaluated).not.toContain("verdict-unchecked");
    const after = html.slice(
      html.indexOf("tally-separator"),
      html.indexOf("</span></span>", html.indexOf("tally-unchecked")) + 14,
    );
    expect(after).toContain("verdict-unchecked");
    expect(after).toContain('<span class="mono">2</span>');
  });

  it("never reads as a pass, and says why it was left unchecked", () => {
    const rows = html
      .split("<tr")
      .filter((r) => r.includes("verdict-unchecked") && !r.includes("tally"));
    expect(rows).toHaveLength(2);
    for (const row of rows) expect(row).not.toContain("verdict-pass");
    expect(html).toContain(
      "Why: </span>mass, power_draw of electrical.drive have no sourced range",
    );
  });

  it("a pass over nothing says so", () => {
    expect(html).toContain("0 evaluated · a pass over nothing");
    expect(html).toContain('<span class="mono">2</span> evaluated');
  });
});

describe("every gate figure shows its mode", () => {
  it("under on: the badge says gate on, and a fail is a filled fail", () => {
    const html = summary("on", every("on"));
    expect(html).toContain("gate-mode-on");
    expect(html).toContain("verdict-fail");
  });

  it("under observe: the badge says not gated, and nothing is a filled pass, fail or warn", () => {
    const html = summary("observe", every("observe"));
    expect(html).toContain("Observe · not gated");
    expect(html).toContain("Would fail · not enforced");
    expect(html).toContain("not enforced");
    expect(html).not.toMatch(/verdict-(pass|fail|warn)/);
  });

  it("under off: no result is shown, and the badge says the gate was off", () => {
    const html = summary("off", []);
    expect(html).toContain("gate-mode-off");
    expect(html).toContain("The gate did not run");
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
    };
  }
  const chosen = config("on", "on");
  const all = new Map<string, RunConfig>([
    ["0/on", chosen],
    ["0/observe", config("observe", "observe")],
    ["0/off", config("off", "off")],
    ["0/other-brief", config("other-brief", "observe", "b")],
    ["0/other-seed", config("other-seed", "observe", "a", 8)],
    ["0/same-mode", config("same-mode", "on")],
  ]);

  it("offers the same brief and seed in another mode, and nothing else", () => {
    expect(pairable(chosen, all).map(([key]) => key)).toEqual(["0/observe", "0/off"]);
  });
});

describe("an unchecked row never reads as a pass", () => {
  it("its Measured cell names what was left unchecked, and says nothing of passing", () => {
    const html = renderToStaticMarkup(<GateChecksTable checks={[check("unchecked", "on")]} />);
    const row = html.slice(html.indexOf("verdict-unchecked"));
    const measured = row.slice(0, row.indexOf("bound-cell"));
    expect(measured).toContain("mass, power_draw");
    expect(measured).not.toMatch(/pass|evaluated/);
  });
});

describe("the tally says how many passes looked at nothing", () => {
  it("next to the evaluated count, from the records", () => {
    const html = summary("on", every("on"));
    expect(html).toContain("tally-over-nothing");
    expect(html).toMatch(/<span class="mono">1<\/span> pass over nothing/);
  });
});

describe("the paired run is drawn in its own mode", () => {
  function config(runId: string, gateMode: GateMode): RunConfig {
    return {
      manifestId: "m",
      runId,
      gateMode,
      harnessCommit: null,
      auth: "api_key",
      briefSha256: "a",
      seed: 7,
      roleModels: {},
    };
  }

  it("an observe run's counts and outcomes are would-be, never a filled verdict", () => {
    const html = renderToStaticMarkup(
      <PairedBody config={config("drive-observe", "observe")} checks={every("observe")} />,
    );
    expect(html).toContain("Observe · not gated");
    expect(html).toContain("not enforced");
    expect(html).toContain("Would fail");
    expect(html).not.toMatch(/verdict-(pass|fail|warn)/);
  });

  it("a gated run's are filled", () => {
    const html = renderToStaticMarkup(
      <PairedBody config={config("drive-on", "on")} checks={every("on")} />,
    );
    expect(html).toContain("verdict-fail");
  });

  it("candidates that share an id say where each is", () => {
    const candidates = [
      ["0/drive-on", config("drive-on", "on")],
      ["1/drive-on", config("drive-on", "on")],
      ["0/drive-off", config("drive-off", "off")],
    ] as const;
    expect(candidates.map(([key, c]) => pairedWhere(key, c, candidates))).toEqual([
      "root 0 · drive-on",
      "root 1 · drive-on",
      null,
    ]);
  });
});
