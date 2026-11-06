/** Simulation: what a run's simulations recorded. Not built yet. */
import type { ViewProps } from "../../shell/header";
import type { ToolViewDef } from "./toolViews";

export function SimulationScreen(
  _props: ViewProps & { readonly toolViews?: readonly ToolViewDef[] },
) {
  return null;
}

export default function Simulation(props: ViewProps) {
  return <SimulationScreen {...props} />;
}
