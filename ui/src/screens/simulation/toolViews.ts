/**
 * The 3D and multi-domain tool views the Simulation screen shows beside a record's plots: a CAD
 * viewer, a circuit-board viewer or a co-simulation, each registered here as one entry. None is
 * registered yet, and the screen says so. A tool view registers with this shape and the screen
 * gives it a tab of its own.
 */
import type { ComponentType } from "react";

import type { IconName } from "../../design/components/icons/Icon";

/** What a tool view is given: the run and the record the screen shows. */
export interface ToolViewProps {
  /** The run's ``root/name``. */
  readonly run: string;
  readonly subtask: string;
  readonly attempt: number;
  readonly record: string | null;
}

export interface ToolViewDef {
  readonly id: string;
  /** The tab's words. */
  readonly title: string;
  readonly icon: IconName;
  readonly component: ComponentType<ToolViewProps>;
}

/** Every tool view the screen offers. Empty until one is added. */
export const TOOL_VIEWS: readonly ToolViewDef[] = [];
