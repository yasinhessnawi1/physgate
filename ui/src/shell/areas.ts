/** The operator UI's top level: Home and the four focus areas, in this order. */
export type AreaId = "home" | "concept" | "orchestration" | "simulation" | "collaboration";

export interface Area {
  readonly id: AreaId;
  readonly number: string;
  readonly name: string;
}

export const AREAS: readonly Area[] = [
  { id: "home", number: "0", name: "Home" },
  { id: "concept", number: "1", name: "Concept & architecture" },
  { id: "orchestration", number: "2", name: "Agentic orchestration" },
  { id: "simulation", number: "3", name: "Simulation" },
  { id: "collaboration", number: "4", name: "Human–AI collaboration" },
];

export function areaById(id: string): Area | undefined {
  return AREAS.find((area) => area.id === id);
}
