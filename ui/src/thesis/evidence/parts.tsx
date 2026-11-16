/**
 * The pieces every tab of the Evidence screen shares: a run's kind tag, the chip naming where a
 * figure came from, a short manifest id one copy away, a value marked as a lower bound, and the
 * list of runs that could not be read.
 */
import { useState } from "react";

import { SourceChip } from "../../design/components/data/SourceChip";
import { type Source, sourceAttribute } from "../../design/components/data/source";
import { Icon } from "../../design/components/icons/Icon";
import {
  commitOf,
  type EvidenceSource,
  type Kind,
  type Place,
  type ReadRun,
  type UnreadRun,
} from "./api";
import { EVIDENCE_COPY, KIND_TAGS, unreadWords } from "./words";

/** How many of a manifest id's characters are shown; the whole id is copied. */
const SHORT = 12;

/** A run's kind, in words, on every run wherever it is shown. Never a verdict's colour. */
export function KindTag({ kind }: { readonly kind: Kind }) {
  return (
    <span className="pg-status evidence-kind-tag" data-kind={kind}>
      <Icon name={kind === "ablation" ? "shield-off" : "microscope"} size={12} />
      {KIND_TAGS[kind]}
    </span>
  );
}

/** A run as a source: its place and run id, and the harness commit it recorded. */
export function runSource(place: Place, runId: string, commit: string | null): Source {
  return { id: `${place.name} · run ${runId}`, commit };
}

export function readSource(run: ReadRun): Source {
  return runSource(run, run.runId, commitOf(run));
}

export function answerSource(source: EvidenceSource): Source {
  return runSource(source, source.runId, source.commit);
}

/** The chip and the kind tag a run's figures carry, with its manifest id. */
export function RunMark({ source }: { readonly source: EvidenceSource }) {
  const chip = answerSource(source);
  return (
    <span className="evidence-mark" data-source={sourceAttribute(chip)}>
      <SourceChip id={chip.id} commit={chip.commit} />
      <KindTag kind={source.kind} />
      <ShortId value={source.manifestId} />
    </span>
  );
}

/** A manifest id: its first characters, the whole one in its name and one copy away. */
export function ShortId({ value }: { readonly value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <span className="pg-id-wrap">
      <span className="pg-id" title={value}>
        {value.slice(0, SHORT)}
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

/** "at least" before a value that is a lower bound, as text, never as decoration. */
export function AtLeast({ shown }: { readonly shown: boolean }) {
  if (!shown) return null;
  return <span className="evidence-at-least">{EVIDENCE_COPY.atLeast} </span>;
}

/** The runs that could not be read, each with its sentence; nothing when every run was read. */
export function UnreadList({
  title,
  rows,
}: {
  readonly title: string;
  readonly rows: readonly UnreadRun[];
}) {
  if (rows.length === 0) return null;
  return (
    <section className="pg-card pg-panel evidence-unread" aria-label={title}>
      <h2 className="pg-panel-title">{title}</h2>
      <ul className="evidence-list">
        {rows.map((row) => (
          <li key={`${String(row.root)}/${row.name}`} data-run={row.name}>
            <span className="evidence-run-name">{row.name}</span>
            <span className="evidence-reason">{unreadWords(row)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
