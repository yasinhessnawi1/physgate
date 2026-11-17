/**
 * A part of the plan, as a person decides it (ARCH-122): which part it is (its label, domain,
 * module role and the quantities a part on hand states), and three choices, never approve or
 * reject: I have it (its real values, each with its unit), I will make it (values, short texts or
 * both), or Find it, the default, stating nothing. A part the release's gate stopped shows the
 * gate's finding and offers have and make only, asking again for every name stated before.
 *
 * The page refuses what the queue would refuse and it can know before anything is sent; the
 * server checks everything again, and a refusal is shown in its own words with nothing written.
 * The choice goes through the one confirmation every decision does, naming the line it writes.
 */
import { useEffect, useId, useRef, useState } from "react";

import type { Result } from "../../api/client";
import type { PlanComponent } from "../../api/events";
import {
  type ItemView,
  type PartsPosition,
  PARTS_POSITIONS,
  type Resolved,
  type StatedPart,
} from "../../api/queue";
import { Button, type Confirmation } from "../../design/components/actions/Button";
import { Id } from "../../design/components/data/Id";
import { quantityLabel, word } from "../../words/humanise";
import { beforeWords, CHOICE_WORDS, CONFIRM_TITLE, PARTS_COPY } from "../../words/parts";
import { DECISION_COPY, effectWords } from "../../words/queue";
import { whyNot } from "./model";
import {
  addedLabel,
  checkParts,
  MAX_DECLARED,
  MAX_TEXTS,
  partRound,
  startingRows,
  uncatalogued,
  type ValueRow,
} from "./parts";
import "./parts.css";

/** A domain or a role as written, in sentence case: `electrical` reads "Electrical". */
function sentenceCase(text: string): string {
  const said = text.split("_").map(word).join(" ");
  return `${(said[0] ?? "").toUpperCase()}${said.slice(1)}`;
}

export function PartsDecide({
  view,
  component,
  total,
  earlier,
  runId,
  operator,
  holdsToken,
  send,
  onDecided,
  onRefused,
  focusOnStart = false,
}: {
  readonly view: ItemView;
  /** The plan's entry for this part, or ``null`` where the plan's line could not be read. */
  readonly component: PlanComponent | null;
  /** How many parts the plan lists, where it is read. */
  readonly total: number | null;
  /** What the round before chose and stated, for a part the release raised again. */
  readonly earlier: { readonly position: PartsPosition; readonly parts: StatedPart } | null;
  readonly runId: string;
  readonly operator: string | null;
  /** Whether this page holds the action token; without it, it can only read. */
  readonly holdsToken: boolean;
  readonly send: (position: PartsPosition, stated: StatedPart | null) => Promise<Result<Resolved>>;
  /** The queue wrote the decision: the screen reads the queue again and moves to the next part. */
  readonly onDecided: (resolved: Resolved) => void;
  /** The server refused it: the screen reads the queue again, and this panel keeps what it holds. */
  readonly onRefused: () => void;
  /** Whether the keyboard's focus starts on this part's choice, as after the part before it. */
  readonly focusOnStart?: boolean;
}) {
  const id = useId();
  const round = partRound(view.item.itemId);
  const again = (round?.round ?? 1) > 1;
  const offered = PARTS_POSITIONS.filter((p) => !(again && p === "find"));
  const [choice, setChoice] = useState<PartsPosition>(
    earlier?.position ?? (again ? "have" : "find"),
  );
  const [rows, setRows] = useState<ValueRow[]>(() =>
    startingRows(component, earlier?.parts ?? null),
  );
  const [added, setAdded] = useState(0);
  const [texts, setTexts] = useState<string[]>([""]);
  const [refusal, setRefusal] = useState<Result<Resolved> | null>(null);
  const why = whyNot(operator, holdsToken);
  const choices = useRef<HTMLFieldSetElement>(null);
  useEffect(() => {
    if (focusOnStart) choices.current?.querySelector<HTMLInputElement>("input:checked")?.focus();
    // Once, when the part is first shown: a later read of the queue moves no focus.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const checked = checkParts(choice, rows, texts, again ? (earlier?.parts ?? null) : null);
  const blocked = why ?? (checked.problems.length > 0 ? PARTS_COPY.fixProblems : null);
  const who = operator ?? "no one";
  const label = component?.label ?? view.item.itemId;
  // Beside the choices: what each choice offered here will do, from the item's own record, in
  // the command line's words. Approve and reject decide no part, and a page that cannot record a
  // choice says nothing of what one would do.
  const consequence = view.item.consequence;
  const effects = consequence === null || why !== null ? [] : effectWords(consequence);
  const said = [
    ...offered.flatMap((p) => effects.filter((e) => e.key === p)),
    ...effects.filter((e) => e.key === "note"),
  ];
  const shownEffects = said.length > 1 ? said : [];

  const setRow = (key: string, change: Partial<ValueRow>) => {
    setRows((now) => now.map((row) => (row.key === key ? { ...row, ...change } : row)));
  };

  const confirmation: Confirmation = {
    title: CONFIRM_TITLE[choice],
    summary: `This records: ${who} chose "${CHOICE_WORDS[choice].label}" for the part "${label}".`,
    writes: JSON.stringify({
      item_id: view.item.itemId,
      ts: "‹the time you confirm›",
      kind: "resolution",
      decision: `choose ${choice}`,
      resolved_by: who,
      verb: "choose",
      position: choice,
      shown_sha256: view.itemSha256,
      ...(checked.stated === null ? {} : { parts: checked.stated }),
    }),
    check:
      `that the item is still the one shown (its digest ${view.itemSha256}), that each value is ` +
      "a finite number in a unit the physics gate reads, of its quantity's kind where the gate's " +
      "catalogue names it, and that what you state goes with your choice",
    outcome:
      view.item.consequence?.onChoose?.[choice] === undefined
        ? DECISION_COPY.then
        : choice === "find"
          ? PARTS_COPY.find
          : PARTS_COPY.declare,
    recordedAs: operator === null ? "no operator: this page names none" : `${operator} (human)`,
    confirmLabel: "Record",
    children: (
      <p className="pg-dialog-note">
        One line appended to queue_decisions.jsonl in run {runId}. {PARTS_COPY.written}
      </p>
    ),
    onConfirm: () => {
      setRefusal(null);
      void send(choice, checked.stated).then((result) => {
        if (result.ok) {
          onDecided(result.value);
          return;
        }
        setRefusal(result);
        onRefused();
      });
    },
  };

  const shownRows = choice === "find" ? [] : rows;
  return (
    <section className="pg-queue-decide pg-parts-decide" aria-label="Decide this part">
      {why !== null && <p className="pg-queue-why-not">{why}</p>}
      {again && (
        <div className="pg-parts-raised" role="note">
          <p className="pg-parts-raised-title">{PARTS_COPY.raisedTitle}</p>
          <p className="pg-parts-raised-finding">{view.item.triggeringFinding}</p>
          <p>{PARTS_COPY.raisedRule}</p>
        </div>
      )}
      {component === null ? (
        <p className="pg-panel-note">{PARTS_COPY.noComponent}</p>
      ) : (
        <dl className="pg-facts pg-parts-component">
          <dt>Part</dt>
          <dd className="pg-parts-label">
            {component.label}
            {round !== null && total !== null && (
              <span className="pg-parts-of">
                {" "}
                · Part {String(round.number)} of {String(total)}
              </span>
            )}
          </dd>
          <dt>Domain</dt>
          <dd>{sentenceCase(component.domain)}</dd>
          <dt>Module role</dt>
          <dd>{sentenceCase(component.role)}</dd>
          <dt>Values it states</dt>
          <dd>
            {[...component.own, ...component.shared].length === 0
              ? "The plan names none; you may add any."
              : [...component.own, ...component.shared].map(quantityLabel).join(", ")}{" "}
            <Id value={component.node} copy={false} />
          </dd>
        </dl>
      )}
      <fieldset className="pg-parts-choice" ref={choices}>
        <legend className="pg-section-label">{PARTS_COPY.legend}</legend>
        {offered.map((position) => (
          <label key={position} className="pg-parts-option" data-checked={choice === position}>
            <input
              type="radio"
              name={`${id}-choice`}
              value={position}
              checked={choice === position}
              onChange={() => {
                setChoice(position);
              }}
            />
            <span className="pg-parts-option-text">
              <span className="pg-parts-option-label">{CHOICE_WORDS[position].label}</span>
              <span className="pg-parts-option-said">{CHOICE_WORDS[position].said}</span>
            </span>
          </label>
        ))}
      </fieldset>
      {shownEffects.length > 0 && (
        <ul className="pg-queue-effects">
          {shownEffects.map((effect) => (
            <li key={effect.key} data-verb={effect.key}>
              {effect.text}
            </li>
          ))}
        </ul>
      )}
      {choice !== "find" && (
        <div className="pg-parts-values" role="group" aria-labelledby={`${id}-values`}>
          <p className="pg-section-label" id={`${id}-values`}>
            {PARTS_COPY.values}
          </p>
          {shownRows.map((row) => (
            <div key={row.key} className="pg-parts-row">
              {row.added ? (
                <span className="pg-field pg-parts-name">
                  <input
                    aria-label={`${row.label}: name`}
                    placeholder="name, such as rated_voltage"
                    value={row.name}
                    autoComplete="off"
                    spellCheck={false}
                    onChange={(e) => {
                      setRow(row.key, { name: e.target.value });
                    }}
                  />
                </span>
              ) : (
                <span className="pg-parts-row-label">
                  {row.label} <Id value={row.name} copy={false} />
                </span>
              )}
              <span className="pg-field pg-parts-number">
                <input
                  aria-label={`${row.label}: value`}
                  inputMode="decimal"
                  placeholder="value"
                  value={row.value}
                  autoComplete="off"
                  onChange={(e) => {
                    setRow(row.key, { value: e.target.value });
                  }}
                />
              </span>
              <span className="pg-field pg-parts-unit">
                <input
                  aria-label={`${row.label}: unit`}
                  placeholder="unit"
                  value={row.unit}
                  autoComplete="off"
                  spellCheck={false}
                  onChange={(e) => {
                    setRow(row.key, { unit: e.target.value });
                  }}
                />
              </span>
              {uncatalogued(row.name) && (
                <span className="pg-parts-unchecked">{PARTS_COPY.unchecked}</span>
              )}
              {row.before !== null && (
                <span className="pg-parts-before">
                  {beforeWords(row.before.value, row.before.unit)}
                </span>
              )}
              {row.added && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setRows((now) => now.filter((r) => r.key !== row.key));
                  }}
                >
                  Remove
                </Button>
              )}
            </div>
          ))}
          {rows.length < MAX_DECLARED && (
            <Button
              variant="browse"
              size="sm"
              icon="plus"
              onClick={() => {
                const n = added + 1;
                setAdded(n);
                setRows((now) => [
                  ...now,
                  {
                    key: `added-${String(n)}`,
                    label: addedLabel(n),
                    name: "",
                    value: "",
                    unit: "",
                    added: true,
                    before: null,
                  },
                ]);
              }}
            >
              {PARTS_COPY.addQuantity}
            </Button>
          )}
          <p className="pg-panel-note">{PARTS_COPY.valuesHint}</p>
        </div>
      )}
      {choice === "make" && (
        <div className="pg-parts-texts" role="group" aria-labelledby={`${id}-texts`}>
          <p className="pg-section-label" id={`${id}-texts`}>
            {PARTS_COPY.texts}
          </p>
          {texts.map((t, i) => (
            <span key={i} className="pg-field">
              <textarea
                aria-label={`Text ${String(i + 1)}`}
                rows={2}
                value={t}
                onChange={(e) => {
                  setTexts((now) => now.map((x, j) => (j === i ? e.target.value : x)));
                }}
              />
            </span>
          ))}
          {texts.length < MAX_TEXTS && (
            <Button
              variant="browse"
              size="sm"
              icon="plus"
              onClick={() => {
                setTexts((now) => [...now, ""]);
              }}
            >
              {PARTS_COPY.addText}
            </Button>
          )}
          <p className="pg-panel-note">{PARTS_COPY.textsHint}</p>
        </div>
      )}
      {/* Always present, so a reader hears each problem as it appears and goes. */}
      <div aria-live="polite">
        {checked.problems.length > 0 && (
          <ul className="pg-parts-problems">
            {checked.problems.map((problem) => (
              <li key={problem}>{problem}</li>
            ))}
          </ul>
        )}
      </div>
      <div className="pg-parts-actions">
        <Button
          variant="act"
          label={PARTS_COPY.record}
          confirm={confirmation}
          disabledBecause={blocked}
        />
      </div>
      <p className="pg-panel-note pg-parts-find-all">{PARTS_COPY.findAll}</p>
      {refusal !== null && !refusal.ok && (
        // Said whole, never folded: the server's words are what the person corrects by.
        <div className="pg-parts-refused" role="alert">
          <p className="pg-parts-refused-title">{PARTS_COPY.refused}</p>
          <p>{refusal.refusal.error}</p>
          {Object.entries(refusal.refusal.context).map(([key, said]) => (
            <p key={key} className="pg-parts-refused-reason">
              {said}
            </p>
          ))}
          <p className="pg-panel-note">{PARTS_COPY.refusedReread}</p>
        </div>
      )}
    </section>
  );
}
