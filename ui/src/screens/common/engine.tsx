/**
 * The engine a run ran on, as the run recorded it. Today no run records its engine, so the cell
 * says so; it never names one the record does not hold. The run's authentication, which the
 * configuration does record, is shown beside it as written.
 */
export function EngineWords({ auth }: { readonly auth: string }) {
  return (
    <>
      <span className="pg-muted">not recorded by this run</span> ·{" "}
      <span className="mono">{auth}</span>
    </>
  );
}
