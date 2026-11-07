/** Not built yet: a stub, so the tests that hold it have something to import. */
export type Field<T> =
  | { readonly kind: "read"; readonly value: T }
  | { readonly kind: "absent"; readonly missing: boolean }
  | { readonly kind: "refused"; readonly reason: string };
