import { type ReactNode, useId, useRef, useState } from "react";

import { Icon, type IconName } from "../icons/Icon";
import { ConfirmDialog, type ConfirmDialogProps } from "./ConfirmDialog";

/** What an act's confirmation shows. Its title, line, attribution and labels are required. */
export type Confirmation = Omit<ConfirmDialogProps, "open" | "onCancel" | "reject">;

interface Browsing {
  /** browse reads (outlined); ghost is a toolbar or icon control. Neither writes anything. */
  readonly variant?: "browse" | "ghost";
  readonly size?: "sm" | "md";
  readonly icon?: IconName;
  /** Without children the button is icon-only, and its title is its accessible name. */
  readonly children?: ReactNode;
  readonly title?: string;
  readonly onClick?: () => void;
  readonly disabled?: boolean;
  readonly pressed?: boolean;
  /** For a button that shows or hides a region: whether it is shown. */
  readonly expanded?: boolean;
  readonly type?: "button" | "submit";
}

interface Acting {
  /** act writes (solid); reject refuses a write (red outline). Both always confirm first. */
  readonly variant: "act" | "reject";
  readonly size?: "sm" | "md";
  readonly icon?: IconName;
  /** The button's words. They end with "…": a click opens a confirmation, never the write. */
  readonly label: `${string}…`;
  /** The confirmation the click opens, naming exactly what gets written and who it is recorded as. */
  readonly confirm: Confirmation;
  /** Why the act cannot be taken now: the button is then disabled and says why beside it. */
  readonly disabledBecause?: string | null;
  /** Held by the caller when something else (the command palette) opens the same confirmation. */
  readonly open?: boolean;
  readonly onOpenChange?: (open: boolean) => void;
}

export type ButtonProps = Browsing | Acting;

export class ActLabelError extends Error {
  constructor(label: string) {
    super(`an act's label ends with "…", because a click only opens its confirmation: "${label}"`);
    this.name = "ActLabelError";
  }
}

function classes(variant: string, size: "sm" | "md" | undefined, iconOnly: boolean): string {
  return [
    "pg-btn",
    `pg-btn-${variant}`,
    size === "sm" ? "pg-btn-sm" : null,
    iconOnly ? "pg-btn-icon" : null,
  ]
    .filter((c) => c !== null)
    .join(" ");
}

function ActButton(props: Acting) {
  const { variant, size, icon, label, confirm, disabledBecause, open, onOpenChange } = props;
  const [ownOpen, setOwnOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const reasonId = useId();
  if (!label.endsWith("…")) throw new ActLabelError(label);
  const showing = open ?? ownOpen;
  const setShowing = (next: boolean) => {
    if (open === undefined) setOwnOpen(next);
    onOpenChange?.(next);
    if (!next) trigger.current?.focus();
  };
  const disabled = disabledBecause !== undefined && disabledBecause !== null;
  const reject = variant === "reject";
  return (
    <>
      <button
        ref={trigger}
        type="button"
        className={classes(variant, size, false)}
        disabled={disabled}
        aria-describedby={disabled ? reasonId : undefined}
        aria-haspopup="dialog"
        onClick={() => {
          if (!disabled) setShowing(true);
        }}
      >
        <Icon name={icon ?? (reject ? "x" : "check")} />
        {label}
      </button>
      {disabled && (
        <span id={reasonId} className="pg-act-reason">
          {disabledBecause}
        </span>
      )}
      <ConfirmDialog
        {...confirm}
        open={showing && !disabled}
        reject={reject}
        onCancel={() => {
          setShowing(false);
        }}
        onConfirm={(reason) => {
          confirm.onConfirm(reason);
          setShowing(false);
        }}
      />
    </>
  );
}

/**
 * Every button. Browsing reads; acting writes, and so never acts on a click: an act or reject
 * button's label ends with "…" and its click opens the confirmation it carries, which names
 * exactly what gets written.
 */
function acting(props: ButtonProps): props is Acting {
  return props.variant === "act" || props.variant === "reject";
}

export function Button(props: ButtonProps) {
  if (acting(props)) return <ActButton {...props} />;
  const {
    variant = "browse",
    size,
    icon,
    children,
    title,
    onClick,
    disabled,
    pressed,
    expanded,
  } = props;
  const iconOnly = children === undefined;
  return (
    <button
      type={props.type === "submit" ? "submit" : "button"}
      className={classes(variant, size, iconOnly)}
      onClick={onClick}
      disabled={disabled}
      title={title}
      aria-label={iconOnly ? title : undefined}
      aria-pressed={pressed}
      aria-expanded={expanded}
    >
      {icon !== undefined && <Icon name={icon} />}
      {children}
    </button>
  );
}
