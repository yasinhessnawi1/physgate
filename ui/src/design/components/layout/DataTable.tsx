import { type ReactNode, useId, useMemo, useState } from "react";

import { Icon } from "../icons/Icon";

export interface DataTableColumn<Row> {
  readonly key: string;
  readonly label: string;
  /** Right-aligned, tabular mono. */
  readonly numeric?: boolean;
  /** A secondary id: mono and smaller. */
  readonly mono?: boolean;
  /** Sortable by this value; a column without it does not sort. */
  readonly sortValue?: (row: Row) => string | number;
  readonly render: (row: Row) => ReactNode;
  /** Its cell may wrap onto further lines (the default keeps cells on one line where they fit). */
  readonly wrap?: boolean;
}

export interface DataTableProps<Row> {
  /** The table's accessible name. */
  readonly label: string;
  readonly columns: readonly DataTableColumn<Row>[];
  readonly rows: readonly Row[];
  readonly rowKey: (row: Row) => string;
  /** The text a row is filtered by; with it, the table has a filter field. */
  readonly filterText?: (row: Row) => string;
  readonly selectedKey?: string | null;
  /** Shown when there are no rows, or none match the filter. */
  readonly empty?: ReactNode;
}

/**
 * A dense table with a sticky header. Columns sort by their own value and the filter narrows the
 * rows by their text; neither changes a value shown. Numeric columns align right in tabular mono.
 */
export function DataTable<Row>({
  label,
  columns,
  rows,
  rowKey,
  filterText,
  selectedKey = null,
  empty,
}: DataTableProps<Row>) {
  const [sort, setSort] = useState<{ key: string; dir: "asc" | "desc" } | null>(null);
  const [filter, setFilter] = useState("");
  const filterId = useId();
  const shown = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    const kept =
      filterText === undefined || needle === ""
        ? [...rows]
        : rows.filter((row) => filterText(row).toLowerCase().includes(needle));
    const column = sort === null ? undefined : columns.find((c) => c.key === sort.key);
    const value = column?.sortValue;
    if (value === undefined || sort === null) return kept;
    return kept.sort((a, b) => {
      const [x, y] = [value(a), value(b)];
      const order =
        typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y));
      return sort.dir === "asc" ? order : -order;
    });
  }, [rows, filter, filterText, sort, columns]);
  return (
    <div className="pg-data-table">
      {filterText !== undefined && (
        <label className="pg-table-filter" htmlFor={filterId}>
          <Icon name="filter" />
          <span className="pg-visually-hidden">Filter {label}</span>
          <input
            id={filterId}
            type="search"
            value={filter}
            placeholder="Filter"
            onChange={(event) => {
              setFilter(event.target.value);
            }}
          />
        </label>
      )}
      <div className="pg-table-wrap" role="region" aria-label={label} tabIndex={0}>
        <table className="pg-table" aria-label={label}>
          <thead>
            <tr>
              {columns.map((column) => {
                const sorted = sort?.key === column.key ? sort.dir : null;
                return (
                  <th
                    key={column.key}
                    scope="col"
                    className={column.numeric === true ? "pg-num" : undefined}
                    aria-sort={
                      sorted === null ? undefined : sorted === "asc" ? "ascending" : "descending"
                    }
                  >
                    {column.sortValue === undefined ? (
                      column.label
                    ) : (
                      <button
                        type="button"
                        className="pg-th-sort pg-hit"
                        onClick={() => {
                          setSort({
                            key: column.key,
                            dir: sorted === "asc" ? "desc" : "asc",
                          });
                        }}
                      >
                        {column.label}
                        <Icon
                          name={
                            sorted === null
                              ? "chevrons-up-down"
                              : sorted === "asc"
                                ? "arrow-up"
                                : "arrow-down"
                          }
                          size={12}
                        />
                      </button>
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {shown.map((row) => {
              const key = rowKey(row);
              return (
                <tr
                  key={key}
                  aria-selected={selectedKey === null ? undefined : selectedKey === key}
                >
                  {columns.map((column) => (
                    <td
                      key={column.key}
                      className={
                        [
                          column.numeric === true ? "pg-num" : null,
                          column.mono === true ? "pg-id" : null,
                          column.wrap === true ? "pg-wrap" : null,
                        ]
                          .filter((c) => c !== null)
                          .join(" ") || undefined
                      }
                    >
                      {column.render(row)}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
        {shown.length === 0 && empty !== undefined && <div className="pg-table-empty">{empty}</div>}
      </div>
    </div>
  );
}
