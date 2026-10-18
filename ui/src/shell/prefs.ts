/**
 * The viewer's display choices: theme (light, dark, or the system's) and density (compact or
 * comfortable). Kept in this browser only, per viewer. Every storage call is guarded: a private
 * window, blocked site data or a throwing accessor leaves the page rendering exactly the same,
 * on the defaults.
 */
export type ThemeChoice = "light" | "dark" | "system";
export type DensityChoice = "compact" | "comfortable";

export const THEME_KEY = "physgate.theme";
export const DENSITY_KEY = "physgate.density";

/** A stored value, or ``null`` when there is none or the storage cannot be read. */
export function readStored(
  key: string,
  store: () => Storage = () => window.localStorage,
): string | null {
  try {
    return store().getItem(key);
  } catch {
    return null;
  }
}

/** Store a value; a storage that refuses leaves the choice for this page's life only. */
export function writeStored(
  key: string,
  value: string,
  store: () => Storage = () => window.localStorage,
): void {
  try {
    store().setItem(key, value);
  } catch {
    // Nothing to do: the choice still holds until the page closes.
  }
}

export function themeChoice(stored: string | null): ThemeChoice {
  return stored === "light" || stored === "dark" ? stored : "system";
}

export function densityChoice(stored: string | null): DensityChoice {
  return stored === "comfortable" ? "comfortable" : "compact";
}

/** The theme drawn: the choice, or the system's preference until one is made. */
export function resolvedTheme(choice: ThemeChoice, prefersDark: boolean): "light" | "dark" {
  return choice === "system" ? (prefersDark ? "dark" : "light") : choice;
}

/** `?theme=dark` or `?theme=light` in the address: a fixed theme for this page, never stored. */
export function themeOverride(search: string): "light" | "dark" | null {
  const asked = new URLSearchParams(search).get("theme");
  return asked === "dark" || asked === "light" ? asked : null;
}

export function prefersDark(): boolean {
  try {
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  } catch {
    return false;
  }
}

const NEXT_THEME: Readonly<Record<ThemeChoice, ThemeChoice>> = {
  light: "dark",
  dark: "system",
  system: "light",
};

export function nextTheme(choice: ThemeChoice): ThemeChoice {
  return NEXT_THEME[choice];
}
