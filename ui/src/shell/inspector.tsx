/**
 * The inspector region: 360 px on the right of the content. A page puts its inspector here
 * through ``InspectorPortal``; the region is open while one is mounted, and the person can close
 * it. Only the component gallery uses it for now: today's views keep their own inspectors.
 */
import { createContext, type ReactNode, useContext, useEffect } from "react";
import { createPortal } from "react-dom";

export interface InspectorSlot {
  readonly element: HTMLElement | null;
  readonly setShown: (shown: boolean) => void;
}

export const InspectorContext = createContext<InspectorSlot>({
  element: null,
  setShown: () => undefined,
});

/** Show ``children`` in the shell's inspector region; nothing when the view has none. */
export function InspectorPortal({ children }: { readonly children: ReactNode }) {
  const slot = useContext(InspectorContext);
  useEffect(() => {
    slot.setShown(true);
    return () => {
      slot.setShown(false);
    };
  }, [slot]);
  return slot.element === null ? null : createPortal(children, slot.element);
}
