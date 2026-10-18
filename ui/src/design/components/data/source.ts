/** Where a figure comes from: a run or an experiment id, and the commit it was made at. */
export interface Source {
  readonly id: string;
  readonly commit: string | null;
}

/** The commit as shown: its first seven characters, or the words saying there is none. */
export function shortCommit(commit: string | null): string {
  return commit === null || commit === "" ? "no commit" : commit.slice(0, 7);
}

/** The data attribute a figure carries so a test can prove it names a source. */
export function sourceAttribute(source: Source): string {
  return `${source.id}@${shortCommit(source.commit)}`;
}

/** A short name for an id: its last path segment ("0/run-on" reads "run-on"). */
export function shortName(id: string): string {
  return (
    id
      .split("/")
      .filter((part) => part !== "")
      .at(-1) ?? id
  );
}
