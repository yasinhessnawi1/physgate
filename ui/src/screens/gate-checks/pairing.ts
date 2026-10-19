import type { RunConfig } from "../../api/records";

/**
 * The runs a gated run can be read against: the same brief, by digest, and the same seed, in a
 * different gate mode. Only these are offered, and the operator picks one; nothing is paired
 * silently, because two runs that differ in more than the mode say nothing about the mode.
 */
export function pairable(
  chosen: RunConfig,
  configs: ReadonlyMap<string, RunConfig>,
): readonly (readonly [string, RunConfig])[] {
  return [...configs.entries()]
    .filter(
      ([, c]) =>
        c.runId !== chosen.runId &&
        c.briefSha256 === chosen.briefSha256 &&
        c.seed === chosen.seed &&
        c.gateMode !== chosen.gateMode,
    )
    .sort(([a], [b]) => a.localeCompare(b));
}
