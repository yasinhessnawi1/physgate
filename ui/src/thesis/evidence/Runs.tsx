/**
 * The runs side by side: each kind of run its own section, reportable first, then development,
 * then ablation, never an ablation run first. Each run is a column holding its kind, its seed,
 * its manifest id held to its first log line, and every setting it recorded and pinned, as the
 * comparison classes them. A run that could not be read is listed apart with its sentence.
 */
import { useState } from "react";

import { Button } from "../../design/components/actions/Button";
import { SourceChip } from "../../design/components/data/SourceChip";
import { sourceAttribute } from "../../design/components/data/source";
import { Icon } from "../../design/components/icons/Icon";
import { KINDS, type Kind, placeKey, type ReadRun, type RunRow, type UnreadRun } from "./api";
import { KindTag, readSource, ShortId, UnreadList } from "./parts";
import {
  EVIDENCE_COPY,
  KIND_HEADINGS,
  rootWords,
  runName,
  settingLabel,
  valueWords,
} from "./words";

/** A setting map flattened to its leaves: a nested map's keys are joined by dots. */
export function leaves(
  record: Readonly<Record<string, unknown>>,
  prefix = "",
): [string, unknown][] {
  return Object.entries(record).flatMap(([key, value]): [string, unknown][] => {
    const path = prefix === "" ? key : `${prefix}.${key}`;
    if (typeof value === "object" && value !== null && !Array.isArray(value))
      return leaves(value as Record<string, unknown>, path);
    return [[path, value]];
  });
}

/** Every path any of the runs recorded, in the order they first appear. */
function paths(runs: readonly ReadRun[], of: (run: ReadRun) => Readonly<Record<string, unknown>>) {
  const found: string[] = [];
  for (const run of runs)
    for (const [path] of leaves(of(run))) if (!found.includes(path)) found.push(path);
  return found;
}

/** The settings whose recorded value is not the same in every one of ``runs``, by path. */
export function differing(
  runs: readonly ReadRun[],
  of: (run: ReadRun) => Readonly<Record<string, unknown>>,
): readonly string[] {
  const values = runs.map((run) => new Map(leaves(of(run))));
  return paths(runs, of).filter(
    (path) => new Set(values.map((held) => JSON.stringify(held.get(path) ?? null))).size > 1,
  );
}

/** A run's column head: its name as every screen gives it, its root, and its source. */
function RunHead({ run }: { readonly run: ReadRun }) {
  const name = runName(run);
  return (
    <th scope="col" data-source={sourceAttribute(readSource(run))} data-run={placeKey(run)}>
      <span className="evidence-run-name" title={`folder ${run.name}`}>
        {name}
      </span>
      <span className="evidence-root">{rootWords(run.root)}</span>
      <SourceChip id={readSource(run).id} commit={readSource(run).commit} compact />
    </th>
  );
}

function SettingRows({
  title,
  runs,
  of,
}: {
  readonly title: string;
  readonly runs: readonly ReadRun[];
  readonly of: (run: ReadRun) => Readonly<Record<string, unknown>>;
}) {
  const values = runs.map((run) => new Map(leaves(of(run))));
  return (
    <>
      <tr className="evidence-group">
        <td colSpan={runs.length + 1}>{title}</td>
      </tr>
      {paths(runs, of).map((path) => (
        <tr key={path}>
          <th scope="row">
            <span className="evidence-label">{settingLabel(path)}</span>
            <span className="pg-id">{path}</span>
          </th>
          {values.map((held, i) => (
            <td key={runs[i] === undefined ? i : placeKey(runs[i])} className="evidence-value">
              {valueWords(held.get(path))}
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}

const flagsOf = (run: ReadRun) => run.flags;
const pinsOf = (run: ReadRun) => run.pins;

function KindSection({ kind, runs }: { readonly kind: Kind; readonly runs: readonly ReadRun[] }) {
  const heading = KIND_HEADINGS[kind];
  // The settings are folded until asked for: what differs between the runs is said above them,
  // where there are two runs or more to differ.
  const [open, setOpen] = useState(false);
  const differ = [...differing(runs, flagsOf), ...differing(runs, pinsOf)].map(settingLabel);
  return (
    <section className="pg-card pg-panel evidence-kind" aria-label={heading} data-kind={kind}>
      <h2 className="pg-panel-title">{heading}</h2>
      <KindTag kind={kind} />
      {runs.length === 0 ? (
        <p className="evidence-note">{EVIDENCE_COPY.noneOfKind}</p>
      ) : (
        <>
          {runs.length > 1 && (
            <p className="evidence-note evidence-differ">
              {differ.length === 0 ? EVIDENCE_COPY.differNone : EVIDENCE_COPY.differSome(differ)}
            </p>
          )}
          <Button
            variant="ghost"
            size="sm"
            expanded={open}
            onClick={() => {
              setOpen((was) => !was);
            }}
          >
            {open
              ? EVIDENCE_COPY.hideSettings
              : EVIDENCE_COPY.showSettings(paths(runs, flagsOf).length, paths(runs, pinsOf).length)}
          </Button>
          <div className="pg-table-wrap" role="region" aria-label={heading} tabIndex={0}>
            <table className="pg-table evidence-matrix">
              <thead>
                <tr>
                  <th scope="col">{EVIDENCE_COPY.setting}</th>
                  {runs.map((run) => (
                    <RunHead key={placeKey(run)} run={run} />
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th scope="row">{EVIDENCE_COPY.kind}</th>
                  {runs.map((run) => (
                    <td key={placeKey(run)}>
                      <KindTag kind={run.kind} />
                    </td>
                  ))}
                </tr>
                <tr>
                  <th scope="row">{EVIDENCE_COPY.runId}</th>
                  {runs.map((run) => (
                    <td key={placeKey(run)} className="evidence-value">
                      {run.runId}
                    </td>
                  ))}
                </tr>
                <tr>
                  <th scope="row">{EVIDENCE_COPY.seed}</th>
                  {runs.map((run) => (
                    <td key={placeKey(run)} className="evidence-value">
                      {String(run.seed)}
                    </td>
                  ))}
                </tr>
                <tr>
                  <th scope="row">{EVIDENCE_COPY.manifestId}</th>
                  {runs.map((run) => (
                    <td key={placeKey(run)}>
                      <ShortId value={run.manifestId} />
                    </td>
                  ))}
                </tr>
                <tr>
                  <th scope="row">{EVIDENCE_COPY.configCheck}</th>
                  {runs.map((run) => (
                    <td key={placeKey(run)}>
                      <span className="pg-status" data-status-kind="config-holds">
                        <Icon name="lock" size={12} />
                        {EVIDENCE_COPY.configHolds}
                      </span>
                    </td>
                  ))}
                </tr>
                {open && (
                  <>
                    <SettingRows title={EVIDENCE_COPY.recorded} runs={runs} of={flagsOf} />
                    <SettingRows title={EVIDENCE_COPY.pinned} runs={runs} of={pinsOf} />
                  </>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

export function RunsTab({ rows }: { readonly rows: readonly RunRow[] }) {
  const read = rows.filter((row): row is ReadRun => row.read);
  const unread = rows.filter((row): row is UnreadRun => !row.read);
  return (
    <>
      <p className="evidence-note" data-note="gaps">
        {EVIDENCE_COPY.gaps}
      </p>
      {KINDS.map((kind) => (
        <KindSection key={kind} kind={kind} runs={read.filter((run) => run.kind === kind)} />
      ))}
      <UnreadList title={EVIDENCE_COPY.unread} rows={unread} />
    </>
  );
}
