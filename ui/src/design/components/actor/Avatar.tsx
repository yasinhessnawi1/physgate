/** Up to two initials of a name, as written: "Yasin K." reads "YK". */
export function initialsOf(name: string): string {
  const words = name.split(/[\s._-]+/).filter((w) => w !== "");
  const letters = words.map((w) => w.charAt(0).toUpperCase());
  return letters.length > 1 ? `${letters[0] ?? ""}${letters.at(-1) ?? ""}` : (letters[0] ?? "?");
}

/** An operator's identity: initials on the human actor's ground, named in full for assistive tech. */
export function Avatar({
  name,
  size = "sm",
}: {
  readonly name: string;
  readonly size?: "sm" | "md";
}) {
  return (
    <span
      className={size === "md" ? "pg-avatar pg-avatar-md" : "pg-avatar"}
      role="img"
      aria-label={name}
      title={name}
    >
      {initialsOf(name)}
    </span>
  );
}
