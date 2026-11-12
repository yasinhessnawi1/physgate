/**
 * The navigation's groups, in order, as the design's shell draws them. A group lists only the
 * views registered under it; a group with none is not shown. A foot group is drawn at the
 * navigation's foot, below the scrolled list, and is listed last everywhere else too.
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
  // How this app is set up: at the foot, as the design draws Settings.
  { id: "settings", name: "This app", foot: true },
];

export function groupById(id: string): Group | undefined {
  return GROUPS.find((group) => group.id === id);
}
