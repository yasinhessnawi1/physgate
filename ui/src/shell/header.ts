import type { GateMode } from "../design/components/GateMode";
import type { Source } from "../design/components/SourceChip";

/** What a view puts in the top bar: its title, and the record its figures come from. */
export interface Header {
  readonly title: string;
  readonly source?: Source;
  readonly gateMode?: GateMode;
  readonly inProgress?: boolean;
}

/** What the shell hands every view. */
export interface ViewProps {
  readonly setHeader: (header: Header) => void;
  readonly query: URLSearchParams;
}
