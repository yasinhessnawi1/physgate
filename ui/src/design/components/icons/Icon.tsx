/**
 * A Lucide icon (v0.460, ISC), vendored as an SVG file beside its licence. Each file is imported
 * as a file, so the build emits it under a hashed name the server's `/assets/{name}` serves, and
 * nothing is fetched from elsewhere. The icon is drawn as a mask over `currentColor`, so it takes
 * the colour of the text around it.
 */
import type { CSSProperties } from "react";

const FILES = import.meta.glob<string>("../../icons/*.svg", {
  eager: true,
  query: "?url",
  import: "default",
});

/** Every vendored icon's name. A test holds this list to the files. */
export const ICON_NAMES = [
  "activity",
  "arrow-down",
  "arrow-right",
  "arrow-up-from-line",
  "arrow-up",
  "badge-check",
  "ban",
  "bell",
  "book-open",
  "bot",
  "box",
  "check",
  "chevrons-up-down",
  "circle-dot",
  "clock",
  "cog",
  "cpu",
  "crosshair",
  "database",
  "download",
  "external-link",
  "eye",
  "file-json",
  "file-plus",
  "file-text",
  "filter",
  "flask-conical",
  "folder-kanban",
  "folder-plus",
  "git-commit-horizontal",
  "git-compare-arrows",
  "git-compare",
  "git-pull-request-arrow",
  "hammer",
  "inbox",
  "layout-dashboard",
  "library",
  "list-checks",
  "lock",
  "messages-square",
  "microscope",
  "minus",
  "moon",
  "network",
  "octagon-x",
  "package-check",
  "package",
  "panel-right-close",
  "panel-right",
  "paperclip",
  "pause",
  "pencil",
  "play",
  "plus",
  "rotate-ccw",
  "rotate-cw",
  "scan",
  "search",
  "settings",
  "shield-check",
  "shield-off",
  "sun",
  "table",
  "user-round",
  "wallet",
  "x",
] as const;

export type IconName = (typeof ICON_NAMES)[number];

/** The built URL of an icon's file. */
export function iconUrl(name: IconName): string {
  const url = FILES[`../../icons/${name}.svg`];
  if (url === undefined) throw new Error(`no icon file for ${name}`);
  return url;
}

/** The names of the icon files that exist, for the test that holds the list to them. */
export function iconFiles(): string[] {
  return Object.keys(FILES).map((path) => path.replace(/^.*\/([^/]+)\.svg$/, "$1"));
}

export interface IconProps {
  readonly name: IconName;
  /** Pixel size; 14 by default, 12 in dense rows, 16 in the nav. */
  readonly size?: number;
  /** The accessible name; without one the icon is decoration and hidden from assistive tech. */
  readonly label?: string;
}

export function Icon({ name, size, label }: IconProps) {
  const style: CSSProperties & Record<`--${string}`, string> = {
    "--pg-icon": `url("${iconUrl(name)}")`,
  };
  if (size !== undefined) style["--pg-icon-size"] = `${String(size)}px`;
  return label === undefined ? (
    <span className="pg-icon" data-icon={name} aria-hidden="true" style={style} />
  ) : (
    <span className="pg-icon" data-icon={name} role="img" aria-label={label} style={style} />
  );
}
