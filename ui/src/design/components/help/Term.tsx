import { type ReactNode, useId, useState } from "react";

import { GLOSSARY, type TermKey } from "./glossary";

/**
 * A harness term with its one-line explanation, from the one glossary table. The explanation
 * shows on hover, on keyboard focus and on a tap, and is the term's accessible description.
 */
export function Term({
  term,
  children,
}: {
  readonly term: TermKey;
  readonly children?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const entry = GLOSSARY[term];
  return (
    <span className={open ? "pg-term pg-term-open" : "pg-term"}>
      <button
        type="button"
        className="pg-term-word pg-hit"
        aria-describedby={id}
        aria-expanded={open}
        onClick={() => {
          setOpen((o) => !o);
        }}
        onKeyDown={(event) => {
          if (event.key === "Escape") setOpen(false);
        }}
      >
        {children ?? entry.term}
      </button>
      <span role="tooltip" id={id} className="pg-term-tip">
        {entry.means}
      </span>
    </span>
  );
}
