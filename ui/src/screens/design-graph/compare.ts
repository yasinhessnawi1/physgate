/**
 * Marking the rows of a diff where the recorded pair differs. This is a view over two records the
 * server sent, labelled as one where it is shown; the change list itself is the store's own. A
 * pair differs when its value or its unit differs as recorded: no unit is converted, so
 * 2000 mV and 2 V differ here, as they differ in the record.
 */
import type { NodeRecord } from "../../api/graph";
import type { Quantity } from "../../design/quantity";

export function recordedPairDiffers(a: Quantity | undefined, b: Quantity | undefined): boolean {
  if (a === undefined || b === undefined) return a !== b;
  return a.value !== b.value || a.unit !== b.unit;
}

export interface QuantityRow {
  readonly name: string;
  readonly before: Quantity | undefined;
  readonly after: Quantity | undefined;
  readonly differs: boolean;
}

/** Every quantity either side holds, by name, each with both sides and whether they differ. */
export function quantityRows(before: NodeRecord | null, after: NodeRecord | null): QuantityRow[] {
  const was = new Map(before?.quantities ?? []);
  const now = new Map(after?.quantities ?? []);
  const names = [...new Set([...was.keys(), ...now.keys()])].sort();
  return names.map((name) => {
    const b = was.get(name);
    const a = now.get(name);
    return { name, before: b, after: a, differs: recordedPairDiffers(b, a) };
  });
}
