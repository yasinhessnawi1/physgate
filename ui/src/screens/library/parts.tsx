/**
 * What the library's sections share: the address of a record, a role as a chip or a word, a
 * digest shortened with the whole one copyable, and who promoted a file and when, as recorded.
 */
import { useCallback, useState } from "react";

import type { PromotionLine } from "../../api/library";
import { ActorBadge } from "../../design/components/actor/ActorBadge";
import { DOMAIN_KINDS, type Domain, DomainChip } from "../../design/components/data/DomainChip";
import { hrefFor } from "../../shell/route";
import { roleWord } from "../../words/library";
import { dayAndMinute, utc } from "../../words/runs";

export const AREA = "reference";
export const SLUG = "library";

/** This screen's address with ``changes`` made to its query. */
export function withQuery(query: URLSearchParams, changes: Record<string, string | null>): string {
  const next = new URLSearchParams(query);
  for (const [key, value] of Object.entries(changes)) {
    if (value === null) next.delete(key);
    else next.set(key, value);
  }
  return hrefFor(AREA, SLUG, next);
}

export function go(href: string) {
  window.location.hash = href.slice(1);
}

function isDomain(role: string): role is Domain {
  return (DOMAIN_KINDS as readonly string[]).includes(role);
}

/** A role: a domain's chip for the schema's five domains, a plain word for any other role. */
export function RoleTag({ role }: { readonly role: string }) {
  return isDomain(role) ? <DomainChip domain={role} /> : <span>{roleWord(role)}</span>;
}

/** A digest's first seven characters, the whole one on hover and copyable. */
export function ShortDigest({ value }: { readonly value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <span className="pg-id-wrap">
      <span className="pg-id pg-lib-digest" title={value}>
        {value.slice(0, 7)}
      </span>
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

/** When a promotion was made, in the viewer's time zone, the UTC time on hover. */
export function PromotedAt({ line }: { readonly line: PromotionLine | null }) {
  if (line?.promoted === null || line?.promoted === undefined)
    return <span className="pg-muted">none</span>;
  return (
    <time dateTime={line.promoted} title={utc(line.promoted)}>
      {dayAndMinute(line.promoted)}
    </time>
  );
}

/** Who promoted it: a named person, as the line names them, never merged with another name. */
export function PromotedBy({ line }: { readonly line: PromotionLine | null }) {
  const name = line?.promotedBy ?? null;
  if (name === null || name.trim() === "") return <span className="pg-muted">none</span>;
  return <ActorBadge kind="human" name={name} size="sm" />;
}

/**
 * Focus ``element``, trying again on the next frames while it cannot take focus: the shell shows
 * its inspector region only after the record is put there, and an element in a hidden region
 * takes no focus. It gives up once the element is gone or after a second's worth of frames.
 */
function focusWhenShown(element: HTMLElement, frames = 60) {
  element.focus();
  if (document.activeElement === element || frames === 0 || !element.isConnected) return;
  requestAnimationFrame(() => {
    focusWhenShown(element, frames - 1);
  });
}

/**
 * Focus moves to the inspector's heading when a record opens there, so a keyboard reaches what
 * it opened without hunting for it. The heading is focusable by script only. The ref is a new
 * function for each record, so a heading drawn once its record is read is focused then too.
 */
export function useFocusOnOpen(key: string): (element: HTMLElement | null) => void {
  return useCallback(
    (element: HTMLElement | null) => {
      if (element !== null) focusWhenShown(element);
    },
    // The key is what changes the ref: each record opened is focused once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [key],
  );
}
