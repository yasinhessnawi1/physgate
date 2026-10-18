/**
 * The first segment of today's addresses (`#/<area>/<view>`), kept as they were so a link, a
 * remembered location or the desktop app's walkthrough still lands where it did. The navigation
 * no longer groups by these: it groups by the design's groups (`groups.ts`).
 */
export type AreaId = "home" | "concept" | "orchestration" | "simulation" | "collaboration";

export const AREA_IDS: readonly AreaId[] = [
  "home",
  "concept",
  "orchestration",
  "simulation",
  "collaboration",
];
