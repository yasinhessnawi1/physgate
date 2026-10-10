/** The queue's items, open first then decided, each a link that chooses it; counts from the listing. */
import type { ItemView, QueueListing } from "../../api/queue";
import { hrefFor } from "../../shell/route";
import { SOURCE_LABEL } from "./model";

export function ItemList({
  listing,
  views,
  chosen,
  query,
}: {
  listing: QueueListing;
  views: readonly ItemView[];
  chosen: ItemView | undefined;
  query: URLSearchParams;
}) {
  const ordered = [...views.filter((v) => v.open), ...views.filter((v) => !v.open)];
  return (
    <section className="card queue-list" aria-labelledby="queue-items">
      <div className="card-head">
        <h2 className="card-title" id="queue-items">
          Items
        </h2>
        <span className="muted">
          <span className="mono">{listing.open.length}</span> open ·{" "}
          <span className="mono">{listing.decided.length}</span> decided
        </span>
      </div>
      {ordered.length === 0 ? (
        <p className="view-note">Nothing has been escalated in this run.</p>
      ) : (
        <nav className="queue-items" aria-label="Queue items">
          {ordered.map((view) => {
            const next = new URLSearchParams(query);
            next.set("item", String(view.position));
            const on = view === chosen;
            return (
              <a
                key={view.item.itemId}
                className={on ? "queue-item queue-item-on" : "queue-item"}
                aria-current={on ? "true" : undefined}
                href={hrefFor("collaboration", "approval-queue", next)}
              >
                <span className="queue-item-head">
                  <span className="queue-item-source">{SOURCE_LABEL[view.item.source]}</span>
                  <span className={view.open ? "badge queue-open" : "badge queue-decided"}>
                    {view.open ? "Open" : "Decided"}
                  </span>
                </span>
                <span className="muted mono">
                  {view.item.subtaskId} · {view.item.itemId}
                </span>
              </a>
            );
          })}
        </nav>
      )}
    </section>
  );
}
