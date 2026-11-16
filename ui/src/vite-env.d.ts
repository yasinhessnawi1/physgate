/// <reference types="vite/client" />

declare module "virtual:physgate-tokens.css";

/**
 * The thesis-only views, through the build's slot: the thesis folder's list, or none. The list's
 * own type is the registry's view type; this declaration cannot name it, so the registry does.
 */
declare module "virtual:physgate-thesis-views" {
  export const THESIS_VIEWS: readonly unknown[];
}
