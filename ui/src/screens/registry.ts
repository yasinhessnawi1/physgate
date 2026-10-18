/**
 * Every view the app has: the navigation group it is listed in, its address, its title and icon. The shell renders the navigation from this list and
 * never imports a view itself, so a later view is one folder and one line here.
 */
import { type ComponentType, lazy } from "react";

import type { IconName } from "../design/components/icons/Icon";
import type { AreaId } from "../shell/areas";
import type { GroupId } from "../shell/groups";
import type { ViewProps } from "../shell/header";

export interface ViewDef {
  /** The navigation group it is listed under. */
  readonly group: GroupId;
  /** The first segment of its address, as today's addresses have it. */
  readonly area: AreaId;
  readonly slug: string;
  readonly title: string;
  readonly icon: IconName;
  readonly component: ComponentType<ViewProps>;
}

export const VIEWS: readonly ViewDef[] = [
  {
    group: "home",
    area: "home",
    slug: "run-records",
    title: "Run records",
    icon: "file-text",
    component: lazy(() => import("./run-records/RunRecords")),
  },
  {
    group: "run",
    area: "orchestration",
    slug: "design-graph",
    title: "Design graph",
    icon: "network",
    component: lazy(() => import("./design-graph/DesignGraph")),
  },
  {
    group: "run",
    area: "orchestration",
    slug: "run-timeline",
    title: "Run timeline",
    icon: "activity",
    component: lazy(() => import("./run-timeline/RunTimeline")),
  },
  {
    group: "run",
    area: "orchestration",
    slug: "gate-checks",
    title: "Gate checks",
    icon: "shield-check",
    component: lazy(() => import("./gate-checks/GateChecks")),
  },
  {
    group: "home",
    area: "collaboration",
    slug: "approval-queue",
    title: "Approval queue",
    icon: "inbox",
    component: lazy(() => import("./approval-queue/ApprovalQueue")),
  },
];
