/**
 * Every view the app has, and the area it belongs to. The shell renders the navigation from
 * this list and never imports a view itself, so a later view is one folder and one line here.
 */
import { type ComponentType, lazy } from "react";

import type { AreaId } from "../shell/areas";
import type { ViewProps } from "../shell/header";

export interface ViewDef {
  readonly area: AreaId;
  readonly slug: string;
  readonly title: string;
  readonly component: ComponentType<ViewProps>;
}

export const VIEWS: readonly ViewDef[] = [
  {
    area: "home",
    slug: "run-records",
    title: "Run records",
    component: lazy(() => import("./run-records/RunRecords")),
  },
  {
    area: "orchestration",
    slug: "design-graph",
    title: "Design graph",
    component: lazy(() => import("./design-graph/DesignGraph")),
  },
  {
    area: "orchestration",
    slug: "run-timeline",
    title: "Run timeline",
    component: lazy(() => import("./run-timeline/RunTimeline")),
  },
  {
    area: "orchestration",
    slug: "gate-checks",
    title: "Gate checks",
    component: lazy(() => import("./gate-checks/GateChecks")),
  },
];
