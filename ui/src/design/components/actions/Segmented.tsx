import { Icon, type IconName } from "../icons/Icon";

export interface SegmentedOption<V extends string> {
  readonly value: V;
  readonly label: string;
  readonly icon?: IconName;
}

/** A single choice among two to four options, as pressed buttons in a labelled group. */
export function Segmented<V extends string>({
  options,
  value,
  onChange,
  label,
  disabled = false,
}: {
  readonly options: readonly SegmentedOption<V>[];
  readonly value: V;
  readonly onChange?: (value: V) => void;
  readonly label: string;
  readonly disabled?: boolean;
}) {
  return (
    <span className="pg-seg" role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={option.value === value}
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
