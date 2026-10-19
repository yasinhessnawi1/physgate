import { getJson, type Result } from "../../api/client";
import { type RunConfig, runConfig, type RunListing } from "../../api/records";
import { runBase, runKey } from "./runs";
import { useResult } from "./useResult";

/** Every readable run's configuration, by run key; a run whose configuration is refused is left out. */
export function useConfigs(
  runs: readonly RunListing[] | null,
): Result<ReadonlyMap<string, RunConfig>> | null {
  const readable = (runs ?? []).filter((run) => run.error === null);
  const key = `configs:${readable.map(runKey).join(",")}`;
  return useResult(
    runs === null
      ? null
      : async () => {
          const answers = await Promise.all(
            readable.map(
              async (run) =>
                [runKey(run), await getJson(`${runBase(run)}/config`, runConfig)] as const,
            ),
          );
          const found = new Map<string, RunConfig>();
          for (const [k, answer] of answers) if (answer.ok) found.set(k, answer.value);
          return { ok: true, value: found };
        },
    key,
  );
}
