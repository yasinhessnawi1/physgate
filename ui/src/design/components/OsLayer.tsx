/** Whether a run's role sessions ran their shell commands inside the OS layer. */
export type OsLayer =
  | { readonly state: "present"; readonly mechanism: "seatbelt" | "bubblewrap" }
  | { readonly state: "absent"; readonly reason: string; readonly noOsProtection: boolean };

const MECHANISM = { seatbelt: "Seatbelt", bubblewrap: "bubblewrap" } as const;

/**
 * Present names its mechanism; absent says so, with its reason on hover and in the
 * accessible name; native Windows says there is no OS protection at all; a run recorded
 * before the layer was measured says it was not recorded, never that it was present.
 */
export function OsLayerBadge({ layer }: { layer: OsLayer | null }) {
  if (layer === null) {
    return <span className="badge os-layer os-layer-unrecorded">OS layer not recorded</span>;
  }
  if (layer.state === "present") {
    return (
      <span className="badge os-layer os-layer-present">
        <span aria-hidden="true">▣</span> OS layer · {MECHANISM[layer.mechanism]}
      </span>
    );
  }
  const word = layer.noOsProtection ? "No OS protection" : "OS layer absent";
  return (
    <span
      className="badge os-layer os-layer-absent"
      title={layer.reason}
      aria-label={`${word}: ${layer.reason}`}
    >
      <span aria-hidden="true">▢</span> {word}
    </span>
  );
}
