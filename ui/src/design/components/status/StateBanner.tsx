import type { ReactNode } from "react";

import { Icon, type IconName } from "../icons/Icon";

export type BannerKind = "whatif" | "observe" | "progress" | "queued" | "research" | "error";

const ICON: Readonly<Record<BannerKind, IconName>> = {
  whatif: "flask-conical",
  observe: "eye",
  progress: "activity",
  queued: "clock",
  research: "circle-dot",
  error: "octagon-x",
};

/**
 * A full-width banner for a view in a special state: a what-if overlay, observe mode, a live run,
 * a queued change, research mode, or a refusal.
 */
export function StateBanner({
  kind,
  title,
  children,
  action,
}: {
  readonly kind: BannerKind;
  readonly title: string;
  readonly children?: ReactNode;
  readonly action?: ReactNode;
}) {
  return (
    <div className={`pg-banner pg-banner-${kind}`} role={kind === "error" ? "alert" : "status"}>
      <Icon name={ICON[kind]} />
      <span className="pg-banner-title">{title}</span>
      {children !== undefined && <span className="pg-banner-body">{children}</span>}
      {action !== undefined && <span className="pg-banner-action">{action}</span>}
    </div>
  );
}
