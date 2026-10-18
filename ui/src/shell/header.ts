import type { GateMode } from "../design/components/verdict/GateMode";
import type { OsLayer } from "../design/components/system/OsLayerBadge";
import type { Source } from "../design/components/data/source";

/** A run as the top bar names it: its label, and the detail behind it. */
export interface RunName {
  readonly label: string;
  readonly detail: string;
}

/** What a view puts in the top bar: its title, and the record its figures come from. */
export interface Header {
  readonly title: string;
  readonly source?: Source;
  readonly gateMode?: GateMode;
  /** Whether the run's role sessions ran inside the OS layer (``null``: not recorded). */
  readonly osLayer?: OsLayer | null;
  readonly inProgress?: boolean;
  /** The run shown, by its label; the chip leads with it. */
  readonly run?: RunName;
  /** No run exists yet, or the run could not be read: the chip says which, in words. */
  readonly runState?: "none" | "unread";
}

/** What the shell hands every view. */
export interface ViewProps {
  readonly setHeader: (header: Header) => void;
  readonly query: URLSearchParams;
}
