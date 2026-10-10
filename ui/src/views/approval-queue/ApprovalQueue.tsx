/**
 * The approval queue of one run: its items, the one chosen with everything a person needs to
 * decide it, and the decision itself. Every figure is read from the run's queue and event log
 * through the server, which reads them with the command line's own functions; the one write is
 * a decision, sent with what this page showed and recorded by the queue's own function.
 */
import { useEffect, useState } from "react";

import { getJson, pageOperator, postAction, type Result } from "../../api/client";
import {
  decisionRequest,
  type ItemView,
  itemView,
  queueListing,
  resolved,
  type Verb,
} from "../../api/queue";
import { EmptyState, ErrorState, LoadingState } from "../../design/components/States";
import type { ViewProps } from "../../shell/header";
import { RunPicker, runKey, runSource, useChosenRun } from "../common/runs";
import { useResult } from "../common/useResult";
import { DecisionPanel } from "./DecisionPanel";
import { ItemDetail } from "./ItemDetail";
import { ItemList } from "./ItemList";
import { chosenItem } from "./model";

async function allItems(base: string, count: number): Promise<Result<readonly ItemView[]>> {
  const read = await Promise.all(
    Array.from({ length: count }, (_, i) => getJson(`${base}/queue/items/${String(i)}`, itemView)),
  );
  const views: ItemView[] = [];
  for (const one of read) {
    if (!one.ok) return one;
    views.push(one.value);
  }
  return { ok: true, value: views };
}

export default function ApprovalQueue({ setHeader, query }: ViewProps) {
  const { runs, chosen, config, base } = useChosenRun(query);
  const [version, setVersion] = useState(0);
  const listing = useResult(
    base === null ? null : () => getJson(`${base}/queue`, queueListing),
    `${String(base)}/queue#${String(version)}`,
  );
  const total =
    listing?.ok === true ? listing.value.open.length + listing.value.decided.length : null;
  const views = useResult(
    base === null || total === null ? null : () => allItems(base, total),
    `${String(base)}/items/${String(total)}#${String(version)}`,
  );
  const operator = pageOperator();
  useEffect(() => {
    if (config?.ok === true)
      setHeader({
        title: "Approval queue",
        source: runSource(config.value),
        gateMode: config.value.gateMode,
      });
  }, [config, setHeader]);

  if (runs === null) return <LoadingState reading="the run list" />;
  if (!runs.ok) return <ErrorState title="The run list was refused" refusal={runs.refusal} />;
  if (chosen === undefined || base === null)
    return (
      <EmptyState title="No runs under the roots yet">
        A run's approval queue appears here once a run directory exists under a root this server was
        started with.
      </EmptyState>
    );
  const picker = (
    <RunPicker runs={runs.value} chosen={chosen} area="collaboration" slug="approval-queue" />
  );
  if (config === null || listing === null)
    return (
      <div className="view">
        {picker}
        <LoadingState reading="the approval queue" />
      </div>
    );
  if (!config.ok)
    return <ErrorState title="The run's configuration was refused" refusal={config.refusal} />;
  if (!listing.ok)
    return <ErrorState title="The approval queue was refused" refusal={listing.refusal} />;
  if (views === null)
    return (
      <div className="view">
        {picker}
        <LoadingState reading="the queue's items" />
      </div>
    );
  if (!views.ok) return <ErrorState title="An item was refused" refusal={views.refusal} />;

  const item = chosenItem(views.value, query.get("item"));
  const decided =
    item === undefined
      ? undefined
      : listing.value.decided.find((d) => d.itemId === item.item.itemId);
  const send = (verb: Verb, note: string) =>
    item === undefined
      ? Promise.resolve<Result<never>>({
          ok: false,
          refusal: { status: 0, error: "no item is chosen", context: {} },
        })
      : postAction(`${base}/queue/decisions`, decisionRequest(item, verb, note), resolved);

  return (
    <div className="view">
      {picker}
      <div className="queue-layout">
        <ItemList listing={listing.value} views={views.value} chosen={item} query={query} />
        {item === undefined ? (
          <EmptyState title="Nothing to decide">
            This run's queue is empty: no subtask was escalated to a person.
          </EmptyState>
        ) : (
          <ItemDetail
            view={item}
            decided={decided}
            source={runSource(config.value)}
            runKey={runKey(chosen)}
          >
            <DecisionPanel
              key={`${item.item.itemId}#${String(version)}`}
              view={item}
              runId={config.value.runId}
              operator={operator}
              send={send}
              onDecided={() => {
                setVersion((v) => v + 1);
              }}
            />
          </ItemDetail>
        )}
      </div>
    </div>
  );
}
