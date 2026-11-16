import type { Standing } from "../../../words/standing";
import { RunPhaseBadge } from "./RunPhaseBadge";

/** The record's own words behind a short sentence, opened on demand: "Details". */
export function Detail({ text }: { readonly text: string | null }) {
  if (text === null) return null;
  return (
    <details className="pg-standing-detail">
      <summary className="pg-hit">Details</summary>
      <p className="pg-standing-full">{text}</p>
    </details>
  );
}

/**
 * A run's standing on its own screens: its badge, one short sentence, and the record's own words
 * behind "Details", for a run that is not going.
 */
export function RunStanding({ standing }: { readonly standing: Standing }) {
  if (standing.sentence === null) return null;
  return (
    <section className="pg-standing" aria-label="Where this run stands">
      <RunPhaseBadge
        phase={standing.phase}
        {...(standing.word === null ? {} : { word: standing.word })}
      />
      <span className="pg-standing-sentence">{standing.sentence}</span>
      <Detail text={standing.detail} />
    </section>
  );
}
