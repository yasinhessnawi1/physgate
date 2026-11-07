import { Icon, type IconName } from "../icons/Icon";

export interface SegmentedOption<V extends string> {
  readonly value: V;
  readonly label: string;
  readonly icon?: IconName;
}

/**
 * A single choice among two to four options, as pressed buttons in a labelled group. A value of
 * ``null`` presses no option: a choice nobody has made, or one nothing keeps, is never drawn as
 * made.
 */
export function Segmented<V extends string>({
  options,
  value,
  onChange,
  label,
  disabled = false,
  describedBy,
}: {
  readonly options: readonly SegmentedOption<V>[];
  readonly value: V | null;
  readonly onChange?: (value: V) => void;
  readonly label: string;
  readonly disabled?: boolean;
  /** The id of the sentence that says more about the choice, such as why it is disabled. */
  readonly describedBy?: string;
}) {
  return (
    <span className="pg-seg" role="group" aria-label={label} aria-describedby={describedBy}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={value !== null && option.value === value}
          aria-describedby={describedBy}
          disabled={disabled}
          onClick={() => {
            onChange?.(option.value);
          }}
        >
          {option.icon !== undefined && <Icon name={option.icon} />}
          {option.label}
        </button>
      ))}
    </span>
  );
}
