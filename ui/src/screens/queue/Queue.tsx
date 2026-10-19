/**
 * One run's approval queue: the items waiting and those resolved on the left, the chosen item on
 * the right with everything a person needs to decide it, and the decision itself, the one write
 * this app makes. Every figure is read from the run's queue and event log through the server; the
 * decision is sent with what this page showed, and recorded by the queue's own function.
 */
import { useEffect, useState } from "react";

import { actToken, getJson, pageOperator, postAction, type Result } from "../../api/client";
import { runEvent } from "../../api/events";
import { decisionRequest, type ItemView, queueListing, resolved, type Verb } from "../../api/queue";
import { Segmented } from "../../design/components/actions/Segmented";
import { Id } from "../../design/components/data/Id";
import { EmptyState, ErrorState, LoadingState } from "../../design/components/status/States";
import { StatusTag } from "../../design/components/status/StatusTag";
import type { ViewProps } from "../../shell/header";
import { hrefFor } from "../../shell/route";
import { SOURCE_WORDS } from "../../words/queue";
import { allItems } from "../common/queueItems";
import { useLines } from "../common/read";
import { subtaskNames } from "../common/rows";
import { RunSwitcher } from "../common/RunSwitcher";
import { inProgress, runSource, useChosenRun } from "../common/runs";
import { useResult } from "../common/useResult";
import { Decide } from "./Decide";
import { chosenItem } from "./model";
import { QueueItem } from "./QueueItem";

const AREA = "collaboration";
const SLUG = "approval-queue";

function ItemList({
  views,
  chosen,
  query,
  names,
}: {
  readonly views: readonly ItemView[];
  readonly chosen: ItemView | undefined;
  readonly query: URLSearchParams;
  readonly names: ReadonlyMap<string, string>;
}) {
  const [show, setShow] = useState<"waiting" | "resolved">(
    chosen !== undefined && !chosen.open ? "resolved" : "waiting",
  );
  const waiting = views.filter((v) => v.open);
  const done = views.filter((v) => !v.open);
  const listed = show === "waiting" ? waiting : done;
  return (
    <section className="pg-card pg-panel pg-queue-list" aria-label="Queue items">
      <header className="pg-panel-head">
        <h2 className="pg-panel-title">Items</h2>
        <Segmented
          label="Show items"
          value={show}
          onChange={setShow}
          options={[
            { value: "waiting", label: `Waiting · ${String(waiting.length)}` },
            { value: "resolved", label: `Resolved · ${String(done.length)}` },
          ]}
        />
      </header>
      {listed.length === 0 ? (
        <p className="pg-panel-empty">
          {show === "waiting" ? "Nothing is waiting in this run." : "Nothing is resolved yet."}
        </p>
      ) : (
        <nav aria-label="Queue items">
          <ul className="pg-list">
            {listed.map((view) => {
              const next = new URLSearchParams(query);
              next.set("item", view.item.itemId);
              const on = view === chosen;
              return (
                <li key={view.item.itemId}>
                  <a
                    className={
                      on ? "pg-queue-entry pg-queue-entry-on pg-hit" : "pg-queue-entry pg-hit"
                    }
                    aria-current={on ? "true" : undefined}
                    href={hrefFor(AREA, SLUG, next)}
                  >
                    <span className="pg-queue-entry-head">
                      <span className="pg-panel-over">{SOURCE_WORDS[view.item.source].kind}</span>
                      <StatusTag status={view.open ? "waiting" : "resolved"} />
                    </span>
                    <span className="pg-queue-entry-title">
                      {names.get(view.item.subtaskId) ?? "The whole design"}
                    </span>
                    <Id value={view.item.itemId} copy={false} />
                  </a>
                </li>
              );
            })}
          </ul>
        </nav>
      )}
    </section>
  );
}

export default function Queue({ setHeader, query }: ViewProps) {
  const chosen = useChosenRun(query);
  const { runs, config, status, base, label } = chosen;
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
  const events = useLines(base === null ? null : `${base}/events`, runEvent);
  const operator = pageOperator();
  const configValue = config?.ok === true ? config.value : undefined;
  const going = status?.ok === true && inProgress(status.value);
  useEffect(() => {
    if (runs?.ok === true && runs.value.length === 0)
      setHeader({ title: "Queue", runState: "none" });
    else if (config?.ok === false || runs?.ok === false || listing?.ok === false)
      setHeader({ title: "Queue", runState: "unread" });
    else if (configValue !== undefined)
      setHeader({
        title: "Queue",
        source: runSource(configValue),
        gateMode: configValue.gateMode,
        osLayer: configValue.osLayer,
        inProgress: going,
        ...(label === undefined ? {} : { run: label }),
      });
  }, [runs, config, configValue, going, label, setHeader, listing]);

  if (runs === null) return <LoadingState reading="the run list" />;
  if (!runs.ok)
    return (
      <ErrorState title="The run list could not be read" {...runs.refusal} route="/api/runs" />
    );
  if (chosen.chosen === undefined || base === null)
    return (
      <EmptyState title="Nothing to decide yet">
        A run's queue appears here once a run is recorded on this machine.
      </EmptyState>
    );
  const switcher = (
    <RunSwitcher
      runs={runs.value}
      chosen={chosen.chosen}
      labels={chosen.labels}
      area={AREA}
      slug={SLUG}
      allShown={chosen.allShown}
      showAll={chosen.showAll}
    />
  );
  if (config === null || listing === null || views === null)
    return (
      <div className="pg-screen">
        {switcher}
        <LoadingState reading="the queue" />
      </div>
    );
  const refused = !config.ok
    ? { title: "The run's configuration could not be read", refusal: config.refusal }
    : !listing.ok
      ? { title: "The queue could not be read", refusal: listing.refusal }
      : !views.ok
        ? { title: "An item of the queue could not be read", refusal: views.refusal }
        : null;
  if (refused !== null || !config.ok || !listing.ok || !views.ok)
    return (
      <div className="pg-screen">
        {switcher}
        <ErrorState
          title={refused?.title ?? "The queue could not be read"}
          {...(refused?.refusal ?? { status: 0, error: "", context: {} })}
          onRetry={() => {
            setVersion((v) => v + 1);
          }}
        />
      </div>
    );
  const names =
    events.result?.ok === true ? subtaskNames(events.result.value) : new Map<string, string>();
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
    <div className="pg-screen">
      {switcher}
      <div className="pg-queue-layout">
        <ItemList views={views.value} chosen={item} query={query} names={names} />
        {item === undefined ? (
          <EmptyState title="Nothing to decide">
            This run's queue is empty: no subtask was set aside for a person.
          </EmptyState>
        ) : (
          <QueueItem
            view={item}
            decided={decided}
            source={runSource(config.value)}
            subtaskName={names.get(item.item.subtaskId) ?? "The whole design"}
          >
            <Decide
              key={`${item.item.itemId}#${String(version)}`}
              view={item}
              runId={config.value.runId}
              operator={operator}
              holdsToken={actToken() !== null}
              send={send}
              onDecided={() => {
                setVersion((v) => v + 1);
              }}
            />
          </QueueItem>
        )}
      </div>
    </div>
  );
}
