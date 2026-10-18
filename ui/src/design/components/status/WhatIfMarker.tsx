import { Icon } from "../icons/Icon";

/** Orange, dashed, with a flask: marks a value or a view as a what-if, never a result. */
export function WhatIfMarker({ label = "What-if" }: { readonly label?: string }) {
  return (
    <span className="pg-badge pg-whatif">
      <Icon name="flask-conical" size={11} />
      {label}
    </span>
  );
}
