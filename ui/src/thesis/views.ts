/**
 * The thesis-only views, as the build's slot hands them to the product's view registry. The
 * product never imports this file: the build resolves the slot to it when this folder ships.
 */
import { lazy } from "react";

import type { ViewDef } from "../screens/registry";

export const THESIS_VIEWS: readonly ViewDef[] = [
  // What the recorded runs measured, under Analyse beside Simulation.
  {
    group: "analyse",
    area: "home",
    slug: "evidence",
    title: "Evidence",
    icon: "microscope",
    component: lazy(() => import("./evidence/Evidence")),
  },
];
