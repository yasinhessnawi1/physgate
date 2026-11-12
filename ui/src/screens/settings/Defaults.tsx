/**
 * The defaults a new run would take, drawn as the design draws them and every one disabled:
 * physgate keeps no defaults yet, so no control holds a value or presses an option, and each says,
 * through its description, what sets the value today. None of them can write anything.
 */
import { useId } from "react";

import type { Result } from "../../api/client";
import {
  type CatalogueModel,
  type Engine,
  type EngineCatalogue,
  isAvailable,
} from "../../api/engines";
import { Segmented } from "../../design/components/actions/Segmented";
import { Term } from "../../design/components/help/Term";
import { GATE_MODE_WORDS, SETTINGS_COPY as C } from "../../words/settings";
import { Fact } from "./FieldView";

const GATE_MODES = ["on", "observe", "off"] as const;

/** The engines the catalogue lists as available, the only ones a choice could name. */
function availableEngines(catalogue: Result<EngineCatalogue> | null): readonly Engine[] {
  if (catalogue?.ok !== true) return [];
  return catalogue.value.engines.flatMap((e) =>
    e.kind === "read" && isAvailable(e.engine) ? [e.engine] : [],
  );
}

/** The models the available engines list, each once, in the catalogue's order. */
function modelsOf(engines: readonly Engine[]) {
  const seen = new Set<string>();
  return engines.flatMap((engine) =>
    engine.models.kind === "read"
      ? engine.models.value.flatMap((m): Extract<CatalogueModel, { kind: "read" }>[] => {
          if (m.kind !== "read" || seen.has(m.id)) return [];
          seen.add(m.id);
          return [m];
        })
      : [],
  );
}

function ModelSelect({
  id,
  said,
  models,
}: {
  readonly id: string;
  readonly said: string;
  readonly models: readonly Extract<CatalogueModel, { kind: "read" }>[];
}) {
  return (
    <span className="pg-field pg-settings-select">
      <select id={id} disabled defaultValue="" aria-describedby={said}>
        <option value="">{C.noDefaultKept}</option>
        {models.map((m) => (
          <option key={m.id} value={m.id}>
            {m.label}
          </option>
        ))}
      </select>
    </span>
  );
}

export function DefaultsSection({
  catalogue,
}: {
  readonly catalogue: Result<EngineCatalogue> | null;
}) {
  const id = useId();
  const engines = availableEngines(catalogue);
  const models = modelsOf(engines);
  const said = (row: string) => `${id}-${row}-said`;
  return (
    <section className="pg-card pg-panel" aria-label={C.defaultsTitle}>
      <h2 className="pg-panel-title">
        <Term term="default-for-new-runs">{C.defaultsTitle}</Term>
      </h2>
      <p className="pg-panel-note">{C.defaultsLead}</p>
      <dl className="pg-facts pg-settings-defaults">
        <Fact field="engine" label={C.rowEngine}>
          {engines.length === 0 ? (
            <p className="pg-muted">{C.noEngineToChoose}</p>
          ) : (
            <div
              className="pg-radio-cards"
              role="radiogroup"
              aria-label={C.rowEngine}
              aria-describedby={said("engine")}
              aria-disabled="true"
            >
              {engines.map((engine) => (
                <label key={engine.id} className="pg-radio-card">
                  <input
                    type="radio"
                    name={`${id}-engine`}
                    value={engine.id}
                    disabled
                    aria-describedby={said("engine")}
                  />
                  <span>{engine.name}</span>
                </label>
              ))}
            </div>
          )}
          <p className="pg-panel-note" id={said("engine")}>
            {C.defaultEngine}
          </p>
        </Fact>
        <Fact field="builder" label={<label htmlFor={`${id}-builder`}>{C.rowBuilder}</label>}>
          <ModelSelect id={`${id}-builder`} said={said("builder")} models={models} />
          <p className="pg-panel-note" id={said("builder")}>
            {C.defaultBuilder}
          </p>
        </Fact>
        <Fact field="reviewer" label={<label htmlFor={`${id}-reviewer`}>{C.rowReviewer}</label>}>
          <ModelSelect id={`${id}-reviewer`} said={said("reviewer")} models={models} />{" "}
          <span className="pg-panel-note">{C.reviewerMustDiffer}</span>
          <p className="pg-panel-note" id={said("reviewer")}>
            {C.defaultReviewer}
          </p>
        </Fact>
        <Fact field="gate-mode" label={C.rowGateMode}>
          <Segmented
            options={GATE_MODES.map((mode) => ({
              value: mode,
              label: GATE_MODE_WORDS[mode] ?? mode,
            }))}
            value={null}
            label={C.rowGateMode}
            disabled
            describedBy={said("gate-mode")}
          />
          <p className="pg-panel-note" id={said("gate-mode")}>
            {C.defaultGateMode}
          </p>
        </Fact>
        <Fact
          field="token-ceiling"
          label={<label htmlFor={`${id}-ceiling`}>{C.tokenCeiling}</label>}
        >
          <span className="pg-field pg-settings-number">
            <input
              id={`${id}-ceiling`}
              type="number"
              inputMode="numeric"
              disabled
              aria-describedby={said("token-ceiling")}
            />
          </span>{" "}
          <span className="pg-unit">{C.tokens}</span>
          <p className="pg-panel-note" id={said("token-ceiling")}>
            {C.defaultTokenCeiling}
          </p>
        </Fact>
      </dl>
    </section>
  );
}
