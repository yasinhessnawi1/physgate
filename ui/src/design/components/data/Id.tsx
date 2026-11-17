import { useState } from "react";

/**
 * A secondary identifier: a key, a hash or a record id, shown after the plain-words label, in
 * mono and smaller, whole (or, given ``short``, its first characters with the whole one button
 * away), and copyable, always whole. Copying is a convenience; when the page may not write to
 * the clipboard the id is still there to select.
 */
export function Id({
  value,
  copy = true,
  short,
  name,
}: {
  readonly value: string;
  readonly copy?: boolean;
  /** Show only this many characters, the whole value on demand. */
  readonly short?: number;
  /** What the id is ("manifest id"), so its toggle's name says what it shows whole. */
  readonly name?: string;
}) {
  const [copied, setCopied] = useState(false);
  const [whole, setWhole] = useState(false);
  const cut = short !== undefined && value.length > short;
  const shown = (
    <span className="pg-id" title={cut ? value : undefined}>
      {cut && !whole ? `${value.slice(0, short)}…` : value}
    </span>
  );
  const open = cut && (
    <button
      type="button"
      className="pg-id-whole pg-hit"
      aria-expanded={whole}
      {...(name === undefined
        ? {}
        : { "aria-label": whole ? `Show less of the ${name}` : `Show whole ${name}` })}
      onClick={() => {
        setWhole((was) => !was);
      }}
    >
      {whole ? "Show less" : "Show whole"}
    </button>
  );
  if (!copy)
    return cut ? (
      <span className="pg-id-wrap">
        {shown}
        {open}
      </span>
    ) : (
      shown
    );
  return (
    <span className="pg-id-wrap">
      {shown}
      {open}
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
