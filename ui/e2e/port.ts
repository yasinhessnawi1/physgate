/**
 * The loopback port the browser tests serve on. It comes from ``PHYSGATE_UI_E2E_PORT``, 8799
 * when unset, because two worktrees running their browser tests at once would otherwise both ask
 * for 8799 and the second would refuse to start.
 */
export const PORT = Number(process.env.PHYSGATE_UI_E2E_PORT ?? "8799");
if (!Number.isInteger(PORT) || PORT < 1024 || PORT > 65535)
  throw new Error(
    `PHYSGATE_UI_E2E_PORT is not a usable port: ${String(process.env.PHYSGATE_UI_E2E_PORT)}`,
  );
