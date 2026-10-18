/**
 * Every screen the app has: the navigation group it is listed in, its address, its title and
 * icon, and whether it opens the shell's inspector. The shell renders the navigation from this
 * list and never imports a screen itself, so a later screen is one folder and one line here.
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
  /** It shows its selection in the shell's inspector region. */
  readonly inspector?: boolean;
}

export const VIEWS: readonly ViewDef[] = [
  {
    group: "home",
    area: "home",
    slug: "overview",
    title: "Home",
    icon: "layout-dashboard",
    component: lazy(() => import("./home/Home")),
  },
  {
    group: "home",
    area: "collaboration",
    slug: "approval-queue",
    title: "Queue",
    icon: "inbox",
    component: lazy(() => import("../views/approval-queue/ApprovalQueue")),
  },
  {
    group: "run",
    area: "orchestration",
    slug: "run-timeline",
    title: "Run timeline",
    icon: "activity",
    component: lazy(() => import("./run-timeline/RunTimeline")),
    inspector: true,
  },
  {
    group: "run",
    area: "orchestration",
    slug: "design-graph",
    title: "Design graph",
    icon: "network",
    component: lazy(() => import("./design-graph/DesignGraph")),
    inspector: true,
  },
  {
    group: "run",
    area: "orchestration",
    slug: "gate-checks",
    title: "Gate checks",
    icon: "shield-check",
    component: lazy(() => import("../views/gate-checks/GateChecks")),
  },
  {
    group: "run",
    area: "home",
    slug: "run-records",
    title: "Run records",
    icon: "file-text",
    component: lazy(() => import("../views/run-records/RunRecords")),
  },
];
