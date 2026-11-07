/**
 * The navigation's groups, in order, as the design's shell draws them. A group lists only the
 * views registered under it; a group with none is not shown.
 */
export type GroupId = "home" | "run" | "analyse" | "reference" | "settings";

export interface Group {
  readonly id: GroupId;
  readonly name: string;
  /** Drawn at the navigation's foot, below the scrolled list, rather than in it. */
  readonly foot?: true;
}

export const GROUPS: readonly Group[] = [
  { id: "home", name: "Home and Queue" },
  { id: "run", name: "This run" },
  { id: "analyse", name: "Analyse" },
  { id: "reference", name: "Reference" },
];

export function groupById(id: string): Group | undefined {
  return GROUPS.find((group) => group.id === id);
}
