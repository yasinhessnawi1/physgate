/**
 * The viewer's display choices, theme and density, held once for the whole page. The shell makes
 * them and provides them; the top bar's toggles and any view that offers the same choices read
 * and change this one state, so the two can never show different choices. The choices are kept in
 * this browser only (`prefs.ts`), and a storage that refuses leaves the page on the defaults.
 */
import { createContext, type ReactNode, useContext, useEffect, useState } from "react";

import {
  DENSITY_KEY,
  type DensityChoice,
  densityChoice,
  nextTheme,
  prefersDark,
  readStored,
  resolvedTheme,
  THEME_KEY,
  type ThemeChoice,
  themeChoice,
  themeOverride,
  writeStored,
} from "./prefs";

export interface DisplayChoices {
  /** The theme chosen: light, dark, or the system's. */
  readonly theme: ThemeChoice;
  /** The theme drawn: the choice, or the system's preference. */
  readonly drawn: "light" | "dark";
  readonly density: DensityChoice;
  /** The theme this page's address fixes (`?theme=`), or ``null``; it is never stored. */
  readonly override: "light" | "dark" | null;
  readonly setTheme: (choice: ThemeChoice) => void;
  readonly setDensity: (choice: DensityChoice) => void;
  readonly cycleTheme: () => void;
  readonly toggleDensity: () => void;
}

/** The display choices, stored per viewer, following the system's theme until one is chosen. */
export function useDisplayState(): DisplayChoices {
  const override = themeOverride(window.location.search);
  const [theme, setThemeState] = useState<ThemeChoice>(
    () => override ?? themeChoice(readStored(THEME_KEY)),
  );
  const [density, setDensityState] = useState<DensityChoice>(() =>
    densityChoice(readStored(DENSITY_KEY)),
  );
  const [dark, setDark] = useState(prefersDark);
  useEffect(() => {
    let query: MediaQueryList | null = null;
    try {
      query = window.matchMedia("(prefers-color-scheme: dark)");
    } catch {
      return;
    }
    const onChange = (event: MediaQueryListEvent) => {
      setDark(event.matches);
    };
    query.addEventListener("change", onChange);
    return () => {
      query.removeEventListener("change", onChange);
    };
  }, []);
  const drawn = resolvedTheme(theme, dark);
  useEffect(() => {
    document.documentElement.dataset.theme = drawn;
  }, [drawn]);
  useEffect(() => {
    document.documentElement.dataset.density = density;
  }, [density]);
  // A theme the address fixes holds for this page only: a choice made under it is drawn, and
  // never stored.
  const setTheme = (choice: ThemeChoice) => {
    setThemeState(choice);
    if (override === null) writeStored(THEME_KEY, choice);
  };
  const setDensity = (choice: DensityChoice) => {
    setDensityState(choice);
    writeStored(DENSITY_KEY, choice);
  };
  return {
    theme,
    drawn,
    density,
    override,
    setTheme,
    setDensity,
    cycleTheme: () => {
      setTheme(nextTheme(theme));
    },
    toggleDensity: () => {
      setDensity(density === "compact" ? "comfortable" : "compact");
    },
  };
}

/** The one display state of the page, as the shell provides it. */
export const DisplayContext = createContext<DisplayChoices | null>(null);

/** Makes the display state and provides it, for a page without the shell: a screen's test. */
export function DisplayProvider({ children }: { readonly children: ReactNode }) {
  const display = useDisplayState();
  return <DisplayContext.Provider value={display}>{children}</DisplayContext.Provider>;
}

/**
 * The page's display choices. Outside a provider this throws: a view that kept a state of its
 * own would let its choices and the top bar's drift apart without a word.
 */
export function useDisplayChoices(): DisplayChoices {
  const display = useContext(DisplayContext);
  if (display === null)
    throw new Error(
      "the display choices are read outside their provider: render inside the shell or a DisplayProvider",
    );
  return display;
}
