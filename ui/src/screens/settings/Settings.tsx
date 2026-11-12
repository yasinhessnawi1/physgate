/**
 * How physgate is set up, in one place: the engines this checkout offers; the defaults for new
 * runs, drawn disabled because physgate keeps none yet; the system the chosen run recorded; who
 * decisions in this window are recorded under; and the viewer's theme and density.
 *
 * Nothing here changes a run. The screen sends no request but a read, and the only choices it
 * offers are the viewer's own display choices, kept in this browser. Each section reads what it
 * shows and fails alone.
 */
import "./settings.css";

import { useEffect } from "react";

import { engineCatalogue } from "../../api/engines";
import type { OsLayer } from "../../design/components/system/OsLayerBadge";
import type { Header, ViewProps } from "../../shell/header";
import { SETTINGS_COPY as C } from "../../words/settings";
import type { RecordedSystem } from "../../api/settings";
import { useJson } from "../common/read";
import { inProgress } from "../common/runs";
import { Appearance } from "./Appearance";
import { DefaultsSection } from "./Defaults";
import { ENGINES_ROUTE, EnginesSection } from "./Engines";
import { isGateMode, sourceOf, SystemSection } from "./System";
import { type RecordedRun, useRecordedRun } from "./useRecordedRun";
import { WhoDecides } from "./WhoDecides";

/** The OS layer as the top bar's badge draws it, or nothing where the record gives no state. */
function headerLayer(system: RecordedSystem): OsLayer | null | undefined {
  const field = system.osLayer;
  if (field.kind === "absent") return null;
  if (field.kind === "refused") return undefined;
  const layer = field.value;
  if (layer.kind === "absent")
    return { state: "absent", reason: layer.reason, noOsProtection: layer.noOsProtection };
  if (
    layer.kind === "present" &&
    (layer.mechanism === "seatbelt" || layer.mechanism === "bubblewrap")
  )
    return { state: "present", mechanism: layer.mechanism };
  return undefined;
}

/**
 * The top bar's chip, from what the chosen run recorded, each part read alone: a part the record
 * does not give is left out, and the rest stands.
 */
export function settingsHeader(run: RecordedRun): Header {
  const header: Header = { title: C.title };
  if (run.runs?.ok === true && run.runs.value.length === 0) return { ...header, runState: "none" };
  if (run.runs?.ok === false || run.config.result?.ok === false)
    return { ...header, runState: "unread" };
  if (run.config.result?.ok !== true) return header;
  const system = run.config.result.value;
  const source = sourceOf(system);
  const layer = headerLayer(system);
  const mode = system.gateMode.kind === "read" ? system.gateMode.value : "";
  return {
    ...header,
    ...(source === null ? {} : { source }),
    ...(isGateMode(mode) ? { gateMode: mode } : {}),
    ...(layer === undefined ? {} : { osLayer: layer }),
    inProgress: run.status.result?.ok === true && inProgress(run.status.result.value),
    ...(run.label === undefined ? {} : { run: run.label }),
  };
}

export default function Settings({ setHeader, query }: ViewProps) {
  const run = useRecordedRun(query);
  const catalogue = useJson(ENGINES_ROUTE, engineCatalogue);
  const header = settingsHeader(run);
  const key = JSON.stringify(header);
  useEffect(() => {
    setHeader(header);
    // The key is the header's content; the object is rebuilt every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, setHeader]);
  return (
    <div className="pg-screen pg-settings">
      <p className="pg-screen-lead">{C.lede}</p>
      <EnginesSection read={catalogue} />
      <DefaultsSection catalogue={catalogue.result} />
      <SystemSection run={run} />
      <WhoDecides />
      <Appearance />
    </div>
  );
}
