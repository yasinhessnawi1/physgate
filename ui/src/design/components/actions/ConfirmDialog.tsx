import { type KeyboardEvent, type ReactNode, useEffect, useId, useRef, useState } from "react";

import { isBlank } from "../../../api/queue";
import { Icon } from "../icons/Icon";

export interface ConfirmDialogProps {
  /** Whether the confirmation is showing. */
  readonly open: boolean;
  readonly title: string;
  /** One plain sentence, first: what is recorded, by whom. A function receives the typed note. */
  readonly summary?: string | ((reason: string) => string);
  /**
   * Required. Exactly what gets written: the record, not the request. A function receives the
   * typed reason, so the line can echo it.
   */
  readonly writes: string | ((reason: string) => string);
  /** What the server checks before it writes. Shown as "Checked first, not written". */
  readonly check?: string;
  /**
   * What follows from the write, shown under "Then", never as a write.
   *
   * Only consequences the harness itself produces belong here. A decision is recorded and its
   * worktree is freed; nothing else happens in the run. Copy that says a decision retries,
   * resumes or merges a subtask is wrong until an architecture decision makes it true.
   */
  readonly outcome?: string;
  /** Required. Who the record is attributed to, for example "e2e-operator (human)". */
  readonly recordedAs: string;
  readonly confirmLabel: string;
  /** The confirmation refuses something: a red outline instead of the solid act. */
  readonly reject?: boolean;
  /**
   * A required note. Confirm stays disabled until it holds something other than whitespace as
   * the server judges whitespace (Python's `str.isspace`).
   */
  readonly needsReason?: boolean;
  /** A note that may be left blank: shown, echoed in the line, never required. */
  readonly takesNote?: boolean;
  readonly reasonLabel?: string;
  /** Further detail of what is written, shown after the line. */
  readonly children?: ReactNode;
  readonly onCancel: () => void;
  readonly onConfirm: (reason: string) => void;
}

export class ConfirmationError extends Error {
  constructor() {
    super("a confirmation names what it writes and who it is recorded as");
    this.name = "ConfirmationError";
  }
}

function stated(value: unknown): boolean {
  return typeof value === "function" || (typeof value === "string" && value.trim() !== "");
}

const FOCUSABLE = "button:not([disabled]), textarea, input, select, a[href], [tabindex='0']";

/**
 * Every write goes through this. One sentence first, then the exact line written, what the server
 * checks first (not written), and what follows (not written), and who it is recorded as.
 *
 * A native modal dialog: the rest of the page is inert while it is open. Focus moves into it on
 * open, Tab stays inside it, and Escape cancels.
 */
export function ConfirmDialog({
  open,
  title,
  summary,
  writes,
  check,
  outcome,
  recordedAs,
  confirmLabel,
  reject = false,
  needsReason = false,
  takesNote = false,
  reasonLabel = needsReason ? "Reason · required" : "Note · optional",
  children,
  onCancel,
  onConfirm,
}: ConfirmDialogProps) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [reason, setReason] = useState("");
  const titleId = useId();
  const reasonId = useId();
  const blank = needsReason && isBlank(reason);

  useEffect(() => {
    const node = dialog.current;
    if (node === null) return;
    if (open && !node.open) {
      setReason("");
      node.showModal();
      node.querySelector<HTMLElement>(FOCUSABLE)?.focus();
    } else if (!open && node.open) {
      node.close();
    }
  }, [open]);

  const onKeyDown = (event: KeyboardEvent<HTMLDialogElement>) => {
    if (event.key !== "Tab") return;
    const all = [...event.currentTarget.querySelectorAll<HTMLElement>(FOCUSABLE)];
    const first = all[0];
    const last = all.at(-1);
    if (first === undefined || last === undefined) return;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  // Held at run time as well as in the type: a caller casting through `unknown` cannot drop them.
  if (!stated(writes) || !stated(recordedAs)) throw new ConfirmationError();
  const line = typeof writes === "function" ? writes(reason) : writes;
  const said = typeof summary === "function" ? summary(reason) : summary;
  return (
    <dialog
      ref={dialog}
      className="pg-dialog"
      aria-labelledby={titleId}
      onCancel={(event) => {
        // Escape: the dialog closes only through the caller, so its state stays the truth.
        event.preventDefault();
        onCancel();
      }}
      onKeyDown={onKeyDown}
    >
      <div className="pg-dialog-head">
        <h2 className="pg-dialog-title" id={titleId}>
          {title}
        </h2>
        {said !== undefined && <p className="pg-dialog-summary">{said}</p>}
      </div>
      <div className="pg-dialog-body">
        <div className="pg-writes">
          <span className="pg-writes-label">This writes:</span>{" "}
          <span className="pg-writes-line">{line}</span>
        </div>
        {children}
        {check !== undefined && (
          <div className="pg-writes">
            <span className="pg-writes-label">Checked first, not written</span>
            <span className="pg-writes-aside">{check}</span>
          </div>
        )}
        {(needsReason || takesNote) && (
          <div className="pg-writes">
            <label className="pg-writes-label" htmlFor={reasonId}>
              {reasonLabel}
            </label>
            <span className="pg-field">
              <textarea
                id={reasonId}
                rows={3}
                value={reason}
                onChange={(event) => {
                  setReason(event.target.value);
                }}
              />
            </span>
          </div>
        )}
        {outcome !== undefined && (
          <div className="pg-writes">
            <span className="pg-writes-label">Then</span>
            <span className="pg-writes-aside">{outcome}</span>
          </div>
        )}
      </div>
      <div className="pg-dialog-foot">
        <span className="pg-dialog-foot-note">Recorded as {recordedAs}</span>
        <button type="button" className="pg-btn pg-btn-browse" onClick={onCancel}>
          Cancel
        </button>
        <button
          type="button"
          className={reject ? "pg-btn pg-btn-reject" : "pg-btn pg-btn-act"}
          disabled={blank}
          onClick={() => {
            if (!blank) onConfirm(reason);
          }}
        >
          <Icon name={reject ? "x" : "check"} />
          {confirmLabel}
        </button>
      </div>
    </dialog>
  );
}
