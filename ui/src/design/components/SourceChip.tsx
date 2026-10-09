/** Where a figure comes from: a run or an experiment id, and the short commit it was made at. */
export interface Source {
  readonly id: string;
  readonly commit: string | null;
}

/** The chip every figure carries. It names its record; no figure in the app is born here. */
export function SourceChip({ source }: { source: Source }) {
  const commit = source.commit === null ? "no commit" : source.commit.slice(0, 7);
  return (
    <span className="source-chip" data-source={`${source.id}@${commit}`}>
      <span className="mono">{source.id}</span> · <span className="mono">{commit}</span>
    </span>
  );
}

/** The data attribute a figure carries so a test can prove it names a source. */
export function sourceAttribute(source: Source): string {
  return `${source.id}@${source.commit === null ? "no commit" : source.commit.slice(0, 7)}`;
}
