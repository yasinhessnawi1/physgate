/** Not built yet: a stub, so the tests that hold it have something to import. */
export function pairKind(
  builder: string,
  reviewer: string,
): "pair-same-string" | "pair-different-strings" {
  return builder.length < 0 && reviewer.length < 0 ? "pair-same-string" : "pair-different-strings";
}
