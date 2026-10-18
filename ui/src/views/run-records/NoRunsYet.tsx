/**
 * Home with no run yet: the app's first screen on a new machine. It leads with starting a
 * project, which the app cannot do yet, so the control is drawn disabled and says it is coming.
 * Nothing here tells the person to open a terminal.
 */
import { useId } from "react";

import { Button } from "../../design/components/actions/Button";
import { EmptyState } from "../../design/components/status/States";
import { StatusTag } from "../../design/components/status/StatusTag";

export function NoRunsYet() {
  const soon = useId();
  return (
    <EmptyState title="No runs yet" icon="folder-plus">
      <span className="home-start">
        <Button icon="folder-plus" disabled describedBy={soon}>
          Start a project
        </Button>
        <span id={soon}>
          <StatusTag status="coming-soon" />
        </span>
      </span>
      <p className="home-start-note">
        Starting a project from the app is coming soon. Runs recorded on this machine appear here as
        soon as there is one.
      </p>
    </EmptyState>
  );
}
