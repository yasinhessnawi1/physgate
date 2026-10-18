import { Icon } from "../icons/Icon";
import { shortCommit, shortName, sourceAttribute } from "./source";

export interface SourceChipProps {
  /** The run or experiment id; ``null`` when the figure's record names none. */
  readonly id: string | null;
  /** The commit; shortened to seven characters. ``null`` reads "no commit". */
  readonly commit: string | null;
  /** An icon and a short name; the full id and commit on hover, on focus and in its name. */
  readonly compact?: boolean;
}

/**
 * The chip every figure carries: the record it comes from and the commit it was made at. A
 * missing source or a missing commit is dashed and says so in words, never a plain chip with a
 * dash where the commit belongs.
 */
export function SourceChip({ id, commit, compact = false }: SourceChipProps) {
  if (id === null || id.trim() === "") {
    return <span className="pg-source pg-source-missing">no source</span>;
  }
  const short = shortCommit(commit);
  const missing = commit === null || commit === "";
  const full = `Source: ${id} at ${missing ? "no commit" : `commit ${short}`}`;
  const className = `pg-source${missing ? " pg-source-missing" : ""}`;
  const attribute = sourceAttribute({ id, commit });
  if (compact) {
    return (
      <span
        className={`${className} pg-source-compact pg-hit`}
        data-source={attribute}
        data-full={`${id} · ${short}`}
        title={`${id} · ${short}`}
        aria-label={full}
        role="note"
        tabIndex={0}
      >
        <Icon name="git-commit-horizontal" size={12} />
        <span aria-hidden="true">{shortName(id)}</span>
      </span>
    );
  }
  return (
    <span className={className} data-source={attribute} aria-label={full} role="note">
      <span className="pg-source-id">{id}</span>
      <span className="pg-source-sep" aria-hidden="true">
        ·
      </span>
      <span className="pg-source-commit">{short}</span>
    </span>
  );
}
