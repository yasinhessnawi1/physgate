import { useState } from "react";

/**
 * A secondary identifier: a key, a hash or a record id, shown after the plain-words label, in
 * mono and smaller, whole, and copyable. Copying is a convenience; when the page may not write to
 * the clipboard the id is still there to select.
 */
export function Id({ value, copy = true }: { readonly value: string; readonly copy?: boolean }) {
  const [copied, setCopied] = useState(false);
  if (!copy) return <span className="pg-id">{value}</span>;
  return (
    <span className="pg-id-wrap">
      <span className="pg-id">{value}</span>
      <button
        type="button"
        className="pg-id-copy pg-hit"
        aria-label={`Copy ${value}`}
        onClick={() => {
          void navigator.clipboard
            .writeText(value)
            .then(() => {
              setCopied(true);
            })
            .catch(() => {
              setCopied(false);
            });
        }}
      >
        {copied ? "Copied" : "Copy"}
      </button>
    </span>
  );
}
