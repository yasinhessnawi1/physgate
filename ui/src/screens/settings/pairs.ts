/**
 * A run's models as builder and reviewer pairs, from what it recorded. A pair is two recorded
 * strings set side by side and compared as strings: the screen never decides that two spellings
 * name one model, and never says a review ran. The harness holds the rule itself, when each
 * reviewer starts.
 */
import type { Field } from "../../api/fields";
import type { PinnedModel, RecordedModels } from "../../api/settings";

/** The reviewer key the plan's reviewer is pinned under: it pairs with the decomposition. */
export const PLAN_REVIEWER = "design";

/** Two recorded model strings, compared exactly as they were written. */
export function pairKind(
  builder: string,
  reviewer: string,
): "pair-same-string" | "pair-different-strings" {
  return builder === reviewer ? "pair-same-string" : "pair-different-strings";
}

export interface PairRow {
  readonly key: string;
  /** A role's pair, the brief's split and the plan's reviewer, or a reviewer pinned to no role. */
  readonly kind: "role" | "decomposition" | "unpaired";
  readonly name: string;
  /** ``null``: the row has no builder (a reviewer pinned under a key that names no role). */
  readonly builder: Field<string> | null;
  /** ``null``: no reviewer is pinned for the row. */
  readonly reviewer: Field<string> | null;
}

/** The reviewer pinned under ``key``, as recorded, or ``null`` when none is pinned there. */
function reviewerOf(reviewers: Field<readonly PinnedModel[]>, key: string): Field<string> | null {
  if (reviewers.kind !== "read") return reviewers;
  return reviewers.value.find((r) => r.key === key)?.model ?? null;
}

/**
 * One row per role, in the record's order; then the brief's split, with the plan's reviewer; then
 * any reviewer pinned under a key that names no role, as written. Roles that could not be read
 * make no rows, and the split's row still stands.
 */
export function pairRows(models: RecordedModels): readonly PairRow[] {
  const roles = models.roles.kind === "read" ? models.roles.value : [];
  const named = new Set(roles.map((r) => r.key));
  const unpaired =
    models.roles.kind === "read" && models.reviewers.kind === "read"
      ? models.reviewers.value.filter((r) => !named.has(r.key) && r.key !== PLAN_REVIEWER)
      : [];
  return [
    ...roles.map((r): PairRow => ({
      key: `role:${r.key}`,
      kind: "role",
      name: r.key,
      builder: r.model,
      reviewer: reviewerOf(models.reviewers, r.key),
    })),
    {
      key: "decomposition",
      kind: "decomposition",
      name: "",
      builder: models.decomposition,
      reviewer: reviewerOf(models.reviewers, PLAN_REVIEWER),
    },
    ...unpaired.map((r): PairRow => ({
      key: `reviewer:${r.key}`,
      kind: "unpaired",
      name: r.key,
      builder: null,
      reviewer: r.model,
    })),
  ];
}
