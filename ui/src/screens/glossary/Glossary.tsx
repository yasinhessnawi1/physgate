/**
 * The words physgate uses for its own parts, in five groups, from the one table the inline
 * explanations read. The gate's seven checks and the queue's reasons for asking a person are
 * listed in their groups from their own tables. Engineering terms are not here: they mean what
 * they mean in any textbook.
 */
import { useEffect } from "react";

import { SOURCES } from "../../api/queue";
import { CHECK_NAMES } from "../../api/run";
import {
  GLOSSARY,
  GLOSSARY_GROUPS,
  type GlossaryEntry,
} from "../../design/components/help/glossary";
import type { ViewProps } from "../../shell/header";
import { CHECK_WORDS } from "../../words/checks";
import { SOURCE_WORDS } from "../../words/queue";

const ENTRIES: readonly GlossaryEntry[] = Object.values(GLOSSARY);

export default function Glossary({ setHeader }: ViewProps) {
  useEffect(() => {
    setHeader({ title: "Glossary" });
  }, [setHeader]);
  return (
    <div className="pg-screen pg-glossary">
      <p className="pg-screen-lead">
        The words physgate uses for its own parts. Engineering terms such as phase margin or stall
        current are used as in any textbook.
      </p>
      {GLOSSARY_GROUPS.map((group) => (
        <section key={group} className="pg-card pg-panel" aria-label={group}>
          <h2 className="pg-panel-title">{group}</h2>
          <dl className="pg-glossary-list">
            {ENTRIES.filter((e) => e.group === group).map((entry) => (
              <div key={entry.term} className="pg-glossary-entry">
                <dt>{entry.term}</dt>
                <dd>{entry.means}</dd>
              </div>
            ))}
            {group === "The gate and its verdicts" &&
              CHECK_NAMES.map((name) => (
                <div key={name} className="pg-glossary-entry">
                  <dt>{CHECK_WORDS[name].name}</dt>
                  <dd>{CHECK_WORDS[name].explains}</dd>
                </div>
              ))}
            {group === "The queue" &&
              SOURCES.map((source) => (
                <div key={source} className="pg-glossary-entry">
                  <dt>{SOURCE_WORDS[source].kind}</dt>
                  <dd>{SOURCE_WORDS[source].why}</dd>
                </div>
              ))}
          </dl>
        </section>
      ))}
    </div>
  );
}
