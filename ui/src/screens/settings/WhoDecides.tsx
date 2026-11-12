/**
 * Who decisions taken in this window are recorded under, and whether this window can decide at
 * all. That it holds the operator's token is said in a sentence; the token itself, and any part
 * of it, is never shown.
 */
import { actToken, pageOperator } from "../../api/client";
import { recordedAs, SETTINGS_COPY as C } from "../../words/settings";

export function WhoDecides() {
  const operator = pageOperator();
  const canDecide = actToken() !== null;
  return (
    <section className="pg-card pg-panel" aria-label={C.whoTitle}>
      <h2 className="pg-panel-title">{C.whoTitle}</h2>
      {operator === null ? (
        <p className="pg-settings-line">{C.noOperator}</p>
      ) : (
        <>
          <p className="pg-settings-line">{recordedAs(operator)}.</p>
          <p className="pg-settings-line">{canDecide ? C.canDecide : C.cannotDecide}</p>
        </>
      )}
      <p className="pg-panel-note">{C.operatorWhere}</p>
    </section>
  );
}
