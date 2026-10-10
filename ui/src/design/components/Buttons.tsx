import { type ReactNode, useId, useRef } from "react";

/** Browsing: an outlined button or a link. It changes nothing. */
export function BrowseButton({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  return (
    <button type="button" className="button button-browse" onClick={onClick}>
      {children}
    </button>
  );
}

export interface Act {
  /** The button's words, without the glyph. */
  readonly label: string;
  /** Exactly what gets written if the person confirms, named in the confirmation. */
  readonly writes: string;
  /** The written record itself and what follows from it, shown under ``writes``. */
  readonly detail?: ReactNode;
  readonly onConfirm: () => void;
}

/**
 * Acting: solid action blue with a leading glyph, or a red outline to reject. Never acts on a
 * click: the click opens a confirmation naming exactly what gets written, which traps focus
 * while open and gives it back to the button when it closes.
 */
export function ActButton({
  act,
  reject = false,
  glyph,
  disabledBecause,
}: {
  act: Act;
  reject?: boolean;
  /** The leading glyph; a check or a cross where the design draws one. */
  glyph?: string;
  /** Why the action cannot be taken now; the button is then disabled and says why. */
  disabledBecause?: string | null;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const reasonId = useId();
  const disabled = disabledBecause !== undefined && disabledBecause !== null;
  const close = () => {
    dialog.current?.close();
    trigger.current?.focus();
  };
  return (
    <>
      <button
        ref={trigger}
        type="button"
        className={reject ? "button button-reject" : "button button-act"}
        disabled={disabled}
        aria-describedby={disabled ? reasonId : undefined}
        onClick={() => {
          if (!disabled) dialog.current?.showModal();
        }}
      >
        <span aria-hidden="true">{glyph ?? (reject ? "✕" : "▶")}</span> {act.label}…
      </button>
      {disabled && (
        <span id={reasonId} className="act-reason">
          {disabledBecause}
        </span>
      )}
      <dialog
        ref={dialog}
        className="confirm"
        aria-labelledby={titleId}
        onClose={() => trigger.current?.focus()}
      >
        <h2 id={titleId} className="confirm-title">
          {act.label}?
        </h2>
        <p className="confirm-writes">
          This writes: <strong>{act.writes}</strong>
        </p>
        {act.detail !== undefined && <div className="confirm-detail">{act.detail}</div>}
        <div className="confirm-actions">
          <button type="button" className="button button-browse" onClick={close}>
            Cancel
          </button>
          <button
            type="button"
            className={reject ? "button button-reject" : "button button-act"}
            onClick={() => {
              act.onConfirm();
              close();
            }}
          >
            {act.label}
          </button>
        </div>
      </dialog>
    </>
  );
}
