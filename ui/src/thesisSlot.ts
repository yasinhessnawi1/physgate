/**
 * The build-time slot the thesis-only views arrive through. The product's view registry imports
 * the slot's id once; the build resolves it to the thesis folder's list of views when that list
 * is there, and to an empty list when it is not. So the product builds, runs and lists no thesis
 * view without the folder, and no product file imports the folder itself: the build is the
 * client's composition root, as the command line is the server's.
 */
import type { Plugin } from "vite";

/** The id the view registry imports the thesis views by, and no other product file names. */
export const THESIS_VIEWS_ID = "virtual:physgate-thesis-views";
const RESOLVED_ID = "\0physgate-thesis-views";

/** The slot's module: the list at ``file``, or no view at all when ``file`` is ``null``. */
export function slotModule(file: string | null): string {
  if (file === null) return "export const THESIS_VIEWS = [];\n";
  return `export { THESIS_VIEWS } from ${JSON.stringify(file)};\n`;
}

/** The slot's resolved id for ``id`` when it is the slot's, and ``null`` for any other. */
export function resolveSlot(id: string): string | null {
  return id === THESIS_VIEWS_ID ? RESOLVED_ID : null;
}

/** The slot's module when ``id`` is the slot's resolved id, and ``null`` for any other. */
export function loadSlot(id: string, file: string | null): string | null {
  return id === RESOLVED_ID ? slotModule(file) : null;
}

/** The plugin that resolves the slot to the list at ``file``, or to none. */
export function thesisViews(file: string | null): Plugin {
  return {
    name: "physgate-thesis-views",
    resolveId(id) {
      return resolveSlot(id);
    },
    load(id) {
      return loadSlot(id, file);
    },
  };
}
