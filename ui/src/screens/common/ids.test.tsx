// @vitest-environment happy-dom
/**
 * A timeline row's internal ids (a subtask's id, a session's id, the run's id) stay out of the
 * way until a person asks for them: one toggle shows them on every row, and hides them again.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { IdsShownContext, metaShown, RowView } from "./RowView";
import type { Row } from "./rows";

const SESSION = "9b3f8894-01dc-4f1e-ab52-8546c615ec95";

const row = (meta: string, subtask: string | null = "balance-control-dba29f"): Row =>
  ({
    key: "k",
    seq: 1,
    ts: "2026-11-16T20:30:35.000000Z",
    actor: null,
    depth: 1,
    sentence: "Attempt 1: the agent's session ended",
    value: null,
    meta,
    end: null,
    subtask,
    attempt: 1,
    more: null,
  }) as unknown as Row;

describe("a row's ids are hidden until asked for", () => {
  it("drops a session's id and the subtask's own id, keeps the words", () => {
    expect(metaShown(row(`Subtask 2 · session ${SESSION}`), false)).toBe("Subtask 2");
    expect(metaShown(row("balance-control-dba29f"), false)).toBe("");
    expect(metaShown(row("balance-control-dba29f · attempt 3"), false)).toBe("attempt 3");
    expect(metaShown(row("run a2-g11-12", null), false)).toBe("");
  });

  it("keeps what is not an id: a node, a count, a cause", () => {
    expect(
      metaShown(row("Subtask 2 · attempt 2 · drivetrain.sizing_record · command_limit"), false),
    ).toBe("Subtask 2 · attempt 2 · drivetrain.sizing_record · command_limit");
  });

  it("asked for, every id is shown as recorded", () => {
    const meta = `Subtask 2 · session ${SESSION}`;
    expect(metaShown(row(meta), true)).toBe(meta);
  });

  it("a row drawn hides its ids by default, and shows them when the toggle is on", () => {
    const meta = `Subtask 2 · session ${SESSION}`;
    expect(renderToStaticMarkup(<RowView row={row(meta)} />)).not.toContain(SESSION);
    expect(
      renderToStaticMarkup(
        <IdsShownContext.Provider value={true}>
          <RowView row={row(meta)} />
        </IdsShownContext.Provider>,
      ),
    ).toContain(SESSION);
  });
});
