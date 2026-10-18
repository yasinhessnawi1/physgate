import type { ReactNode } from "react";

/** A keyboard key, for shortcut hints and the command palette. Set in mono. */
export function Kbd({ children }: { readonly children: ReactNode }) {
  return <kbd className="pg-kbd">{children}</kbd>;
}
