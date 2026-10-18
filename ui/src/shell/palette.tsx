/**
 * The command palette (⌘K, or Ctrl+K). It opens with focus in its input. "Go to" reaches every
 * registered view; views add their own entries through ``usePaletteEntries`` while they are
 * shown. An entry that writes is labelled with "…" and opens that view's own confirmation: the
 * palette never writes anything itself.
 */
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";

export interface PaletteEntry {
  readonly id: string;
  /** The heading the entry is listed under: "Go to", or a view's own. */
  readonly section: string;
  readonly label: string;
  /** Run when chosen. A writing entry opens its confirmation here; it never writes. */
  readonly run: () => void;
  /** Why it cannot be chosen now; the entry is then shown, disabled, with the reason. */
  readonly disabledBecause?: string | null;
}

interface Registry {
  readonly entries: readonly PaletteEntry[];
  readonly register: (owner: string, entries: readonly PaletteEntry[]) => void;
  readonly unregister: (owner: string) => void;
}

const PaletteContext = createContext<Registry>({
  entries: [],
  register: () => undefined,
  unregister: () => undefined,
});

/** Hold the entries the views register, by owner. */
export function usePaletteRegistry(): Registry {
  const [byOwner, setByOwner] = useState<ReadonlyMap<string, readonly PaletteEntry[]>>(new Map());
  const register = useCallback((owner: string, entries: readonly PaletteEntry[]) => {
    setByOwner((current) => new Map(current).set(owner, entries));
  }, []);
  const unregister = useCallback((owner: string) => {
    setByOwner((current) => {
      const next = new Map(current);
      next.delete(owner);
      return next;
    });
  }, []);
  const entries = useMemo(() => [...byOwner.values()].flat(), [byOwner]);
  return useMemo(() => ({ entries, register, unregister }), [entries, register, unregister]);
}

export function PaletteProvider({
  registry,
  children,
}: {
  readonly registry: Registry;
  readonly children: ReactNode;
}) {
  return <PaletteContext.Provider value={registry}>{children}</PaletteContext.Provider>;
}

/** A view's own entries, listed while it is shown. */
export function usePaletteEntries(entries: readonly PaletteEntry[]): void {
  const { register, unregister } = useContext(PaletteContext);
  const owner = useId();
  useEffect(() => {
    register(owner, entries);
  }, [owner, entries, register]);
  useEffect(
    () => () => {
      unregister(owner);
    },
    [owner, unregister],
  );
}

/** The entries whose label holds every word typed, in their order. */
export function matching(entries: readonly PaletteEntry[], typed: string): readonly PaletteEntry[] {
  const words = typed
    .toLowerCase()
    .split(/\s+/)
    .filter((w) => w !== "");
  return entries.filter((entry) => {
    const text = `${entry.section} ${entry.label}`.toLowerCase();
    return words.every((word) => text.includes(word));
  });
}

export function Palette({
  open,
  goTo,
  onClose,
}: {
  readonly open: boolean;
  /** The "Go to" entries, from the registry. */
  readonly goTo: readonly PaletteEntry[];
  readonly onClose: () => void;
}) {
  const { entries } = useContext(PaletteContext);
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const returnTo = useRef<Element | null>(null);
  const [typed, setTyped] = useState("");
  const [active, setActive] = useState(0);
  const listId = useId();
  // Listed only while open: a closed palette holds no entry text in the page.
  const shown = open ? matching([...goTo, ...entries], typed) : [];
  const choosable = shown.filter(
    (e) => e.disabledBecause === undefined || e.disabledBecause === null,
  );

  useEffect(() => {
    const node = dialog.current;
    if (node === null) return;
    if (open && !node.open) {
      returnTo.current = document.activeElement;
      setTyped("");
      setActive(0);
      node.showModal();
      input.current?.focus();
    } else if (!open && node.open) {
      setTyped("");
      node.close();
      if (returnTo.current instanceof HTMLElement && returnTo.current.isConnected)
        returnTo.current.focus();
    }
  }, [open]);

  const choose = (entry: PaletteEntry | undefined) => {
    if (
      entry === undefined ||
      (entry.disabledBecause !== undefined && entry.disabledBecause !== null)
    )
      return;
    onClose();
    // After the palette has closed, so a confirmation the entry opens takes the focus.
    window.setTimeout(entry.run, 0);
  };

  const sections = [...new Set(shown.map((e) => e.section))];
  const activeEntry = choosable[Math.min(active, choosable.length - 1)];
  return (
    <dialog
      ref={dialog}
      className="pg-palette"
      aria-label="Command palette"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <div className="pg-palette-field pg-field">
        <input
          ref={input}
          type="text"
          role="combobox"
          aria-expanded="true"
          aria-controls={listId}
          aria-activedescendant={
            activeEntry === undefined ? undefined : `${listId}-${activeEntry.id}`
          }
          aria-label="Search views and actions"
          placeholder="Go to a view, or an action"
          value={typed}
          onChange={(event) => {
            setTyped(event.target.value);
            setActive(0);
          }}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setActive((a) => Math.min(a + 1, Math.max(choosable.length - 1, 0)));
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setActive((a) => Math.max(a - 1, 0));
            } else if (event.key === "Enter") {
              event.preventDefault();
              choose(activeEntry);
            }
          }}
        />
      </div>
      <div id={listId} role="listbox" aria-label="Views and actions" className="pg-palette-list">
        {open && shown.length === 0 && <p className="pg-palette-none">Nothing matches.</p>}
        {sections.map((section) => (
          <div key={section} role="group" aria-label={section} className="pg-palette-section">
            <div className="pg-palette-heading" aria-hidden="true">
              {section}
            </div>
            {shown
              .filter((e) => e.section === section)
              .map((entry) => {
                const disabled =
                  entry.disabledBecause !== undefined && entry.disabledBecause !== null;
                return (
                  <div
                    key={entry.id}
                    id={`${listId}-${entry.id}`}
                    role="option"
                    aria-selected={entry === activeEntry}
                    aria-disabled={disabled}
                    className="pg-palette-entry"
                    onClick={() => {
                      choose(entry);
                    }}
                  >
                    <span>{entry.label}</span>
                    {disabled && <span className="pg-palette-why">{entry.disabledBecause}</span>}
                  </div>
                );
              })}
          </div>
        ))}
      </div>
    </dialog>
  );
}
