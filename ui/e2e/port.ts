/**
 * The loopback port the browser tests serve on. It comes from ``PHYSGATE_UI_E2E_PORT``, because
 * two worktrees running their browser tests at once would otherwise both ask for one port and the
 * second would refuse to start. ``scripts/check-ui.sh`` sets it to a free port when it is unset;
 * run directly, the tests fall back to 8799.
 */
export const PORT = Number(process.env.PHYSGATE_UI_E2E_PORT ?? "8799");
if (!Number.isInteger(PORT) || PORT < 1024 || PORT > 65535)
  throw new Error(
    `PHYSGATE_UI_E2E_PORT is not a usable port: ${String(process.env.PHYSGATE_UI_E2E_PORT)}`,
  );
