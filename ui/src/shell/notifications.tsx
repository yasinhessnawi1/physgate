/**
 * Notifications: the queue items still open, across every run the server lists. Each leads with
 * its sentence as recorded, its item id after it, smaller. A run whose queue could not be read
 * shows its refusal, never nothing.
 */
import { useEffect, useState } from "react";

import { getJson, type Result } from "../api/client";
import { type QueueItem, queueListing } from "../api/queue";
import { type RunListing, runListing } from "../api/records";
import { ErrorState, LoadingState } from "../design/components/status/States";
import { hrefFor } from "./route";

export interface RunQueue {
  readonly run: RunListing;
  readonly open: Result<readonly QueueItem[]>;
}

function base(run: RunListing): string {
  return `/api/runs/${String(run.root)}/${encodeURIComponent(run.name)}`;
}

/** Every listed run's open items, or its refusal. A run the server could not read says why. */
export async function openItems(): Promise<Result<readonly RunQueue[]>> {
  const runs = await getJson("/api/runs", runListing);
  if (!runs.ok) return runs;
  const queues = await Promise.all(
    runs.value.map(async (run): Promise<RunQueue> => {
      if (run.error !== null)
        return { run, open: { ok: false, refusal: { status: 0, error: run.error, context: {} } } };
      const listing = await getJson(`${base(run)}/queue`, queueListing);
      return { run, open: listing.ok ? { ok: true, value: listing.value.open } : listing };
    }),
  );
  return { ok: true, value: queues };
}

/** How many items are open across the runs that could be read. */
export function openCount(queues: readonly RunQueue[]): number {
  return queues.reduce((n, q) => n + (q.open.ok ? q.open.value.length : 0), 0);
}

export function Notifications({ onClose }: { readonly onClose: () => void }) {
  const [found, setFound] = useState<Result<readonly RunQueue[]> | null>(null);
  useEffect(() => {
    let live = true;
    void openItems().then((result) => {
      if (live) setFound(result);
    });
    return () => {
      live = false;
    };
  }, []);
  return (
    <section className="pg-popover pg-notifications" aria-label="Notifications" role="region">
      <h2 className="pg-popover-title">Waiting for a decision</h2>
      {found === null ? (
        <LoadingState reading="the queues" rows={1} />
      ) : !found.ok ? (
        <ErrorState title="The run list could not be read" {...found.refusal} />
      ) : openCount(found.value) === 0 && found.value.every((q) => q.open.ok) ? (
        <p className="pg-popover-empty">No queue item is open in any run.</p>
      ) : (
        <ul className="pg-notice-list">
          {found.value.map(({ run, open }) =>
            open.ok ? (
              open.value.map((item) => (
                <li key={`${run.name}/${item.itemId}`} className="pg-notice">
                  <a
                    className="pg-notice-link"
                    href={hrefFor(
                      "collaboration",
                      "approval-queue",
                      new URLSearchParams({
                        run: `${String(run.root)}/${run.name}`,
                        item: item.itemId,
                      }),
                    )}
                    onClick={onClose}
                  >
                    <span className="pg-notice-sentence">{item.decisionRequired}</span>
                    <span className="pg-notice-ids">
                      <span className="pg-id">{item.itemId}</span>
                      <span className="pg-id">{run.name}</span>
                    </span>
                  </a>
                </li>
              ))
            ) : (
              <li key={run.name} className="pg-notice">
                <ErrorState
                  title={`The queue of ${run.name} could not be read`}
                  {...open.refusal}
                />
              </li>
            ),
          )}
        </ul>
      )}
    </section>
  );
}
