/** A count and its noun, in the right number: "1 edge", "4 nodes", "0 records". */
export function countOf(n: number, noun: string): string {
  return `${String(n)} ${noun}${n === 1 ? "" : "s"}`;
}
