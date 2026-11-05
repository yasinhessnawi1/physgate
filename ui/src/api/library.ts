/** The library's records: not guarded yet. */
export const libraryListing = (_value: unknown) =>
  ({ library: "", documents: [], rubrics: [], promotions: 0, staged: 0 }) as never;
export const libraryFile = (_value: unknown) => ({ promotions: [] }) as never;
export const stagedList = (_value: unknown) => ({}) as never;
export const candidateDetail = (_value: unknown) => ({ candidate: {}, lines: [] }) as never;
export const ratings = (_value: unknown) =>
  ({ tables: [], storeClasses: [], catalogueDigest: "" }) as never;
export const fileRoute = (_kind: string, _role: string): string => "";
export const candidateRoute = (_id: string): string => "";
