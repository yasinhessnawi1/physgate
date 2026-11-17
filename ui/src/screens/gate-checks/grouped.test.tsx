// @vitest-environment happy-dom
/**
 * Records of one check over one subject in one gate call, with one outcome, read as one row with
 * their count, each record's own words kept under it; and the counts a person cannot read alone,
 * unchecked and a pass over nothing, are said in a sentence each.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { GateCheck } from "../../api/run";
import { ChecksTable, CountsExplained } from "./ChecksTable";

const SOURCE = { id: "run r-1", commit: "0123456789abcdef" };
const NAMES = new Map([["s1", "Subtask 1"]]);

function unchecked(quantities: readonly string[], seq = 50): GateCheck {
  return {
    seq,
    subtask: "s1",
    attempt: 1,
    name: "units",
    check: 1,
    ts: null,
    scope: "subtask",
    mode: "on",
    outcome: "unchecked",
    blocking: false,
    value: null,
    node: "drivetrain.plant_interface",
    evaluated: null,
    reviewerHadPassed: true,
    expected: null,
    message: `drivetrain.plant_interface carries quantities the catalogue does not know (${quantities.join(", ")})`,
    details: { form: "unchecked", evaluated: null, quantities, low: null, high: null },
  };
}

function shown(checks: readonly GateCheck[]): HTMLElement {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(
    <ChecksTable checks={checks} names={NAMES} source={SOURCE} />,
  );
  return host;
}

describe("records alike in a gate call read as one row with their count", () => {
  const five = [
    unchecked(["command_limit"]),
    unchecked(["cell_pack_mass"]),
    unchecked(["wheel_radius"]),
    unchecked(["stall_current"]),
    unchecked(["no_load_current"]),
  ];

  it("five unchecked records of one check over one subject: one row, its count said", () => {
    const host = shown(five);
    const rows = host.querySelectorAll("tbody tr:not(.pg-group-row)");
    expect(rows).toHaveLength(1);
    expect(rows[0]?.querySelector(".pg-check-count")?.textContent).toBe("5 records");
  });

  it("keeps every record's own words, each on its line", () => {
    const host = shown(five);
    const lines = [...host.querySelectorAll(".pg-why-list li")].map((li) => li.textContent);
    expect(lines).toHaveLength(5);
    for (const q of ["command_limit", "cell_pack_mass", "wheel_radius"])
      expect(lines.some((l) => l.includes(q))).toBe(true);
  });

  it("a record in another gate call, or with another outcome, stays its own row", () => {
    const host = shown([unchecked(["a"]), unchecked(["b"], 51)]);
    expect(host.querySelectorAll("tbody tr:not(.pg-group-row)")).toHaveLength(2);
    expect(host.querySelector(".pg-check-count")).toBeNull();
  });
});

describe("the counts a person cannot read alone are said in words", () => {
  it("unchecked and a pass over nothing, each in a sentence, when there are any", () => {
    const text = renderToStaticMarkup(<CountsExplained unchecked={44} overNothing={12} />);
    expect(text).toContain(
      "Unchecked (44): the gate could not judge these values, for example a quantity its catalogue does not know, so they are neither passed nor failed.",
    );
    expect(text).toContain(
      "A pass over nothing (12): the check ran but found no value to look at; it is a pass as the gate wrote it, not a value shown to be right.",
    );
  });

  it("says nothing of a count that is zero", () => {
    expect(renderToStaticMarkup(<CountsExplained unchecked={0} overNothing={0} />)).toBe("");
  });
});
