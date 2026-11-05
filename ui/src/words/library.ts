/** The library's words: not written yet. */
export const STATE_WORDS: Readonly<Record<string, string>> = {};
export const EFFECT_WORDS: Readonly<Record<string, string>> = {};
export const LIBRARY_COPY: Readonly<Record<string, string>> = {};
export const roleWord = (role: string): string => `${role}?`;
export const documentLabel = (_kind: string, _role: string): string => "";
export const candidateLabel = (_kind: string, _replaces: boolean, _role: string): string => "";
export const stagedErrorLabel = (_kind: string): string => "";
export const promotionsCount = (_n: number): string => "";
export const proposedTab = (_n: number): string => "";
export const writtenWords = (_written: string): string => "";
export const libraryErrorTitle = (_error: string): string => "";
export const documentErrorWords = (_error: string): string => "";
export const candidateErrorWords = (_error: string): string => "";
