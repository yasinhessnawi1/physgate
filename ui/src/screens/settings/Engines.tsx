/**
 * The engines the desktop app's engine step offers, as this checkout's catalogue lists them, with
 * the file and digest they were read from. An engine the catalogue does not list as available is
 * drawn and inert: nothing on any engine's row is a control. A model the catalogue marks as a
 * default is the catalogue's default, never a run's.
 */
import type { Result } from "../../api/client";
import type { Engine, EngineCatalogue, LocalModel } from "../../api/engines";
import { Id } from "../../design/components/data/Id";
import { Quantity } from "../../design/components/data/Quantity";
import { Term } from "../../design/components/help/Term";
import { DataTable } from "../../design/components/layout/DataTable";
import { EmptyState, ErrorState, LoadingState } from "../../design/components/status/States";
import { StatusTag } from "../../design/components/status/StatusTag";
import {
  AUTH_WORDS,
  catalogueSource,
  refusedEntry,
  SETTINGS_COPY as C,
  wordsFor,
} from "../../words/settings";
import type { Read } from "../common/read";
import { Fact, Refused, Shown, Words } from "./FieldView";

export const ENGINES_ROUTE = "/api/engines";

function EngineStatus({ engine }: { readonly engine: Engine }) {
  return (
    <Shown field={engine.status} none={C.noStatus}>
      {(status) =>
        status === "available" ? (
          <StatusTag status="engine-available" />
        ) : status === "not-yet" ? (
          <StatusTag status="engine-not-yet" />
        ) : (
          <span className="mono pg-as-written">{status}</span>
        )
      }
    </Shown>
  );
}

/** The catalogue's own default marks for a model: "default builder", "default reviewer". */
function marks(engine: Engine, id: string): string {
  if (engine.defaults.kind !== "read") return "";
  const { implementer, reviewer } = engine.defaults.value;
  const found = [
    implementer.kind === "read" && implementer.value === id ? C.defaultBuilderMark : null,
    reviewer.kind === "read" && reviewer.value === id ? C.defaultReviewerMark : null,
  ].filter((m) => m !== null);
  return found.length === 0 ? "" : ` · ${found.join(" · ")}`;
}

function EngineRow({ engine }: { readonly engine: Engine }) {
  return (
    <li
      className="pg-engine"
      data-engine={engine.id}
      data-status={engine.status.kind === "read" ? engine.status.value : ""}
    >
      <div className="pg-engine-head">
        <span className="pg-engine-name">{engine.name}</span> <Id value={engine.id} copy={false} />
        <span className="pg-engine-status">
          {engine.status.kind === "absent" ? (
            <span className="pg-muted">{C.noStatus}</span>
          ) : (
            <EngineStatus engine={engine} />
          )}
        </span>
      </div>
      {engine.detail.kind !== "absent" && (
        <p className="pg-engine-detail">
          <Shown field={engine.detail}>{(detail) => detail}</Shown>
        </p>
      )}
      {engine.auth.kind !== "absent" && (
        <p className="pg-engine-auth">
          <Shown field={engine.auth}>
            {(auth) => <Words worded={wordsFor(AUTH_WORDS, auth)} />}
          </Shown>
        </p>
      )}
      {engine.models.kind === "refused" && <Refused reason={engine.models.reason} />}
      {engine.models.kind === "read" && engine.models.value.length > 0 && (
        <ul className="pg-engine-models" aria-label={`${C.models}: ${engine.name}`}>
          {engine.models.value.map((model, i) =>
            model.kind === "read" ? (
              <li key={model.id} className="pg-engine-model">
                {model.label} <Id value={model.id} copy={false} />
                {marks(engine, model.id)}
              </li>
            ) : (
              <li key={`refused-${String(i)}`} className="pg-engine-model">
                <Refused reason={model.reason} />
              </li>
            ),
          )}
        </ul>
      )}
      {engine.defaults.kind === "refused" && <Refused reason={engine.defaults.reason} />}
      {engine.localModels.kind === "refused" && <Refused reason={engine.localModels.reason} />}
    </li>
  );
}

/**
 * An engine's local models, folded, outside its row so the row holds no control. The sizes are
 * the catalogue's, in GB as its keys name them, and approximate as it says; the source is text,
 * never a link: this page makes no request elsewhere.
 */
function LocalModels({
  engine,
  models,
}: {
  readonly engine: Engine;
  readonly models: readonly LocalModel[];
}) {
  return (
    <details className="pg-details pg-local-models">
      <summary>{C.localModels}</summary>
      <DataTable<LocalModel>
        label={`${C.localModelsTable}: ${engine.name}`}
        rows={models}
        rowKey={(m) => (m.kind === "read" ? m.name : m.reason)}
        columns={[
          {
            key: "model",
            label: C.columnModel,
            wrap: true,
            render: (m) => (m.kind === "read" ? m.name : refusedEntry(m.reason)),
          },
          {
            key: "memory",
            label: C.columnMemory,
            numeric: true,
            render: (m) =>
              m.kind === "read" && <Shown field={m.memory}>{(q) => <Quantity {...q} />}</Shown>,
          },
          {
            key: "disk",
            label: C.columnDisk,
            numeric: true,
            render: (m) =>
              m.kind === "read" && <Shown field={m.disk}>{(q) => <Quantity {...q} />}</Shown>,
          },
          {
            key: "licence",
            label: C.columnLicence,
            wrap: true,
            render: (m) => m.kind === "read" && <Shown field={m.licence}>{(l) => l}</Shown>,
          },
          {
            key: "source",
            label: C.columnSource,
            wrap: true,
            render: (m) =>
              m.kind === "read" && (
                <Shown field={m.source}>{(s) => <span className="mono">{s}</span>}</Shown>
              ),
          },
        ]}
      />
    </details>
  );
}

function Catalogue({ catalogue }: { readonly catalogue: EngineCatalogue }) {
  const read = catalogue.engines.flatMap((e) => (e.kind === "read" ? [e.engine] : []));
  return (
    <>
      <dl className="pg-facts">
        <Fact field="source" label={C.catalogueSourceLabel}>
          <span
            className="pg-source pg-catalogue-source"
            role="note"
            aria-label={`Source: ${catalogueSource(catalogue.file)}`}
          >
            <span className="pg-source-id">{catalogueSource(catalogue.file)}</span>
          </span>
        </Fact>
        <Fact field="digest" label={C.catalogueDigest}>
          <Id value={catalogue.sha256} copy={false} />
        </Fact>
        <Fact field="size" label={C.catalogueSize}>
          <Quantity {...catalogue.length} />
        </Fact>
      </dl>
      <ul className="pg-engines">
        {catalogue.engines.map((entry, i) =>
          entry.kind === "read" ? (
            <EngineRow key={`${entry.engine.id}-${String(i)}`} engine={entry.engine} />
          ) : (
            <li key={`refused-${String(i)}`} className="pg-engine pg-engine-refused">
              {refusedEntry(entry.reason)}
            </li>
          ),
        )}
      </ul>
      {read.map(
        (engine) =>
          engine.localModels.kind === "read" &&
          engine.localModels.value.length > 0 && (
            <LocalModels key={engine.id} engine={engine} models={engine.localModels.value} />
          ),
      )}
      <p className="pg-panel-note">{C.engineChosenWhere}</p>
    </>
  );
}

/** Where a figure in the section comes from: the checkout's file, at the digest it was read at. */
function sourceOf(result: Result<EngineCatalogue> | null): string | undefined {
  return result?.ok === true
    ? `${catalogueSource(result.value.file)}@${result.value.sha256.slice(0, 7)}`
    : undefined;
}

export function EnginesSection({ read }: { readonly read: Read<EngineCatalogue> }) {
  const { result } = read;
  return (
    <section
      className="pg-card pg-panel"
      aria-label={C.enginesTitle}
      data-source={sourceOf(result)}
    >
      <h2 className="pg-panel-title">
        <Term term="engine-catalogue">{C.enginesTitle}</Term>
      </h2>
      <p className="pg-panel-note">{C.enginesLead}</p>
      {result === null ? (
        <LoadingState reading={C.enginesLoading} />
      ) : result.ok ? (
        <Catalogue catalogue={result.value} />
      ) : result.refusal.status === 404 ? (
        <EmptyState title={C.enginesEmpty} icon="cpu" />
      ) : (
        <ErrorState
          title={C.enginesError}
          {...result.refusal}
          route={ENGINES_ROUTE}
          onRetry={read.again}
        />
      )}
    </section>
  );
}
