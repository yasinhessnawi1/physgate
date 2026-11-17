import { useContext, useId } from "react";

import { placeKey, type ReadRun } from "./api";
import { RunNamesContext } from "./names";
import { EVIDENCE_COPY, KIND_CHOICES } from "./words";

/**
 * A choice of one run among the runs read, each named with its kind. With nothing chosen it
 * offers no run until the person picks one; a choice changes the address and nothing else.
 */
export function RunChooser({
  label,
  runs,
  value,
  onChoose,
}: {
  readonly label: string;
  readonly runs: readonly ReadRun[];
  /** The chosen run's ``root/name``, or ``null`` when none is chosen. */
  readonly value: string | null;
  readonly onChoose: (key: string) => void;
}) {
  const id = useId();
  const names = useContext(RunNamesContext);
  return (
    <span className="evidence-field">
      <label htmlFor={id}>{label}</label>
      <select
        id={id}
        value={value ?? ""}
        onChange={(event) => {
          onChoose(event.target.value);
        }}
      >
        {value === null && <option value="">{EVIDENCE_COPY.chooseRun}</option>}
        {runs.map((run) => (
          <option key={placeKey(run)} value={placeKey(run)}>
            {`${names.get(placeKey(run)) ?? run.name}, ${KIND_CHOICES[run.kind]}`}
          </option>
        ))}
      </select>
    </span>
  );
}
