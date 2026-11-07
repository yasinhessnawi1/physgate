import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { InProgressBadge } from "./InProgressBadge";
import { StateBanner } from "./StateBanner";
import { EmptyState, ErrorState, LoadingState } from "./States";
import { STATUS_KINDS, type StatusKind, StatusTag } from "./StatusTag";
import { WhatIfMarker } from "./WhatIfMarker";
import { ENGINE_STATUS_WORDS, PAIR_WORDS } from "../../../words/settings";

const CSS = readFileSync(fileURLToPath(new URL("../../components.css", import.meta.url)), "utf8");

/** Every rule of the stylesheet whose selector names ``className``, with its declarations. */
function rulesFor(className: string): string[] {
  return [...CSS.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
    .filter((m) =>
      (m[1] ?? "").split(",").some((s) => new RegExp(`\\.${className}(?![\\w-])`).test(s)),
    )
    .map((m) => m[2] ?? "");
}

describe("an error names what was refused and shows nothing partial", () => {
  const html = renderToStaticMarkup(
    <ErrorState
      title="Task ledger: not shown"
      status={422}
      error="the ledger disagrees with the run-event log"
      context={{ ledger: "ledger.jsonl" }}
    />,
  );

  it("is an alert carrying the title, the server's reason, its status and its context", () => {
    expect(html).toContain('role="alert"');
    expect(html).toContain("Task ledger: not shown");
    expect(html).toContain("the ledger disagrees with the run-event log");
    expect(html).toContain("422");
    expect(html).toContain("ledger.jsonl");
  });

  it("opens with its sentence, and puts the status, reason and context under Details", () => {
    expect(html.indexOf("Task ledger: not shown")).toBeLessThan(html.indexOf("<details"));
    const details = html.slice(html.indexOf("<details"));
    expect(details).toContain("<summary>Details</summary>");
    expect(details).toContain("422");
    expect(details).toContain("ledger.jsonl");
    expect(details).toContain("the ledger disagrees with the run-event log");
  });

  it("holds no table: nothing of the refused record is shown", () => {
    expect(html).not.toContain("<table");
  });
});

describe("every view has its empty, loading and error states", () => {
  it("empty is dashed and says so in words", () => {
    const html = renderToStaticMarkup(<EmptyState title="No runs yet">Start one.</EmptyState>);
    expect(html).toContain("pg-state-empty");
    expect(html).toContain("No runs yet");
  });

  it("loading says what it reads and is busy, with no number", () => {
    const html = renderToStaticMarkup(<LoadingState reading="run-on" />);
    expect(html).toContain('aria-busy="true"');
    expect(html).toContain("Reading <span");
  });
});

describe("states that are not verdicts are neutral", () => {
  const kinds = Object.keys(STATUS_KINDS) as StatusKind[];

  it.each(kinds)("%s never draws a check or a cross, nor a verdict's class", (status) => {
    const html = renderToStaticMarkup(<StatusTag status={status} />);
    expect(html).not.toMatch(/[✓✕]/);
    expect(html).not.toMatch(/pg-verdict|pg-observed/);
    expect(html).toContain("pg-status");
    expect(html).not.toMatch(/data-icon="(check|x)"/);
  });

  it("the neutral style uses none of the pass, fail or warn colours", () => {
    const rules = [...rulesFor("pg-status"), ...rulesFor("pg-status-strong")];
    expect(rules.length).toBeGreaterThan(0);
    for (const rule of rules) expect(rule).not.toMatch(/--color-(pass|fail|warn)/);
  });

  it("covers the seal states and the change states", () => {
    for (const k of [
      "applied",
      "refused",
      "declined",
      "resolved",
      "waiting",
      "frozen",
      "confirmed",
      "complete",
    ])
      expect(kinds).toContain(k);
    expect(kinds.filter((k) => k.startsWith("seal-")).length).toBe(6);
  });
});

describe("what-if and in-progress", () => {
  it("the what-if marker carries the flask and its word; the banner exists", () => {
    const html = renderToStaticMarkup(<WhatIfMarker />);
    expect(html).toContain('data-icon="flask-conical"');
    expect(html).toContain("What-if");
    expect(html).toContain("pg-whatif");
    const banner = renderToStaticMarkup(<StateBanner kind="whatif" title="What-if overlay" />);
    expect(banner).toContain("pg-banner-whatif");
  });

  it("the what-if style is dashed in its own colour", () => {
    const rules = rulesFor("pg-whatif").join(";");
    expect(rules).toContain("dashed");
    expect(rules).toContain("--color-whatif");
  });

  it("in progress reads 'In progress · partial'", () => {
    expect(renderToStaticMarkup(<InProgressBadge />)).toContain("In progress · partial");
  });
});

describe("the Settings screen's states are neutral, and an engine not offered yet is dashed", () => {
  const table = STATUS_KINDS as Readonly<Record<string, readonly [string, string]>>;

  it("covers an engine's status and a pair's comparison, in the Settings words", () => {
    expect(table["engine-available"]?.[1]).toBe(ENGINE_STATUS_WORDS.available);
    expect(table["engine-not-yet"]?.[1]).toBe(ENGINE_STATUS_WORDS["not-yet"]);
    expect(table["pair-different-strings"]?.[1]).toBe(PAIR_WORDS.different);
    expect(table["pair-same-string"]?.[1]).toBe(PAIR_WORDS.same);
  });

  it("draws Not yet dashed, and no other of them", () => {
    const kinds = [
      "engine-available",
      "engine-not-yet",
      "pair-different-strings",
      "pair-same-string",
    ];
    for (const kind of kinds) expect(Object.keys(STATUS_KINDS)).toContain(kind);
    const tag = (status: string) =>
      renderToStaticMarkup(<StatusTag status={status as StatusKind} />);
    expect(tag("engine-not-yet")).toContain('class="pg-status pg-status-dashed"');
    for (const status of ["engine-available", "pair-different-strings", "pair-same-string"])
      expect(tag(status)).not.toContain("pg-status-dashed");
  });

  it("the dashed style is a dashed neutral outline, never the unchecked verdict's colours", () => {
    const rules = rulesFor("pg-status-dashed");
    expect(rules.length).toBeGreaterThan(0);
    const all = rules.join(";");
    expect(all).toContain("dashed");
    expect(all).toContain("--color-border-strong");
    expect(all).not.toMatch(/--color-(unchecked|pass|fail|warn)/);
  });
});
