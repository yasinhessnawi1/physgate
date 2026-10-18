import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ActorBadge, ActorError } from "./ActorBadge";
import { Avatar, initialsOf } from "./Avatar";

const LooseActorBadge = ActorBadge as unknown as (props: Record<string, unknown>) => ReactNode;

describe("every change shows its actor", () => {
  it("draws the four kinds apart", () => {
    const kinds = [
      renderToStaticMarkup(<ActorBadge kind="deterministic" name="Orchestrator" />),
      renderToStaticMarkup(
        <ActorBadge kind="agent" name="Sizer" role="implementer" model="opus-5.5" />,
      ),
      renderToStaticMarkup(<ActorBadge kind="collaborator" quote="raise the bus voltage" />),
      renderToStaticMarkup(<ActorBadge kind="human" name="Yasin K." />),
    ];
    expect(kinds.map((h) => /pg-actor-(\w+)/.exec(h)?.[1])).toEqual([
      "deterministic",
      "agent",
      "collaborator",
      "human",
    ]);
    expect(kinds[1]).toContain("implementer · opus-5.5");
    expect(kinds[2]).toContain("raise the bus voltage");
    expect(kinds[3]).toContain("YK");
  });

  it("an agent names its role and its model, in the type and at run time", () => {
    // @ts-expect-error an agent without its model is not an actor.
    expect(<ActorBadge kind="agent" name="Sizer" role="implementer" />).toBeTruthy();
    expect(() =>
      renderToStaticMarkup(
        <LooseActorBadge {...{ kind: "agent", name: "Sizer", role: "implementer" }} />,
      ),
    ).toThrow(ActorError);
    expect(() =>
      renderToStaticMarkup(<ActorBadge kind="agent" name="Sizer" role=" " model="opus-5.5" />),
    ).toThrow(ActorError);
  });

  it("a human is named, in the type and at run time", () => {
    // @ts-expect-error a human without a name is not an actor.
    expect(<ActorBadge kind="human" />).toBeTruthy();
    expect(() => renderToStaticMarkup(<ActorBadge kind="human" name="" />)).toThrow(ActorError);
  });

  it("a collaborator action quotes its request, in the type and at run time", () => {
    // @ts-expect-error a collaborator action without the request that caused it.
    expect(<ActorBadge kind="collaborator" />).toBeTruthy();
    expect(() => renderToStaticMarkup(<ActorBadge kind="collaborator" quote="" />)).toThrow(
      ActorError,
    );
  });

  it("an avatar shows initials and is named in full", () => {
    expect(initialsOf("Yasin K.")).toBe("YK");
    expect(initialsOf("e2e-operator")).toBe("EO");
    expect(renderToStaticMarkup(<Avatar name="Yasin K." />)).toContain('aria-label="Yasin K."');
  });
});
