/**
 * The viewer's own theme and density: the top bar's choices, read and changed through the shell's
 * one display state, so both places change together. Kept in this browser only. A theme the
 * page's address fixes holds the theme control disabled, and says so.
 */
import { useId } from "react";

import { Segmented } from "../../design/components/actions/Segmented";
import { useDisplayChoices } from "../../shell/display";
import type { DensityChoice, ThemeChoice } from "../../shell/prefs";
import { DENSITY_WORDS, fixedBy, SETTINGS_COPY as C, THEME_WORDS } from "../../words/settings";
import { Fact } from "./FieldView";

const THEMES: readonly ThemeChoice[] = ["light", "dark", "system"];
const DENSITIES: readonly DensityChoice[] = ["compact", "comfortable"];

export function Appearance() {
  const display = useDisplayChoices();
  const id = useId();
  const kept = `${id}-kept`;
  const fixed = `${id}-fixed`;
  return (
    <section className="pg-card pg-panel" aria-label={C.appearanceTitle}>
      <h2 className="pg-panel-title">{C.appearanceTitle}</h2>
      <dl className="pg-facts">
        <Fact field="theme" label={C.theme}>
          <Segmented
            options={THEMES.map((t) => ({ value: t, label: THEME_WORDS[t] ?? t }))}
            value={display.theme}
            onChange={display.setTheme}
            label={C.theme}
            disabled={display.override !== null}
            describedBy={display.override === null ? kept : fixed}
          />
          {display.override !== null && (
            <p className="pg-panel-note" id={fixed}>
              {fixedBy(display.override)}
            </p>
          )}
        </Fact>
        <Fact field="density" label={C.density}>
          <Segmented
            options={DENSITIES.map((d) => ({ value: d, label: DENSITY_WORDS[d] ?? d }))}
            value={display.density}
            onChange={display.setDensity}
            label={C.density}
            describedBy={kept}
          />
        </Fact>
      </dl>
      <p className="pg-panel-note" id={kept}>
        {C.keptHere}
      </p>
    </section>
  );
}
