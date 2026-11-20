/**
 * A server of a browser test's own: the real `physgate ui` over a root the test names, on a free
 * port, in a process group of its own, so the other screens' tests never read its runs. Stopped
 * by the folder the test made, so the stop finds only that test's processes.
 */
import { type ChildProcessWithoutNullStreams, execFileSync, spawn } from "node:child_process";
import { rmSync } from "node:fs";
import { fileURLToPath } from "node:url";

const CHECKOUT = fileURLToPath(new URL("../..", import.meta.url));

export interface Started {
  readonly url: string;
}

const servers: ChildProcessWithoutNullStreams[] = [];

/** The real `physgate ui` over `root`, with `library`, on a free port. */
export async function serve(root: string, library: string): Promise<Started> {
  const child = spawn(
    "uv",
    ["run", "physgate", "ui", "--root", root, "--library", library, "--port", "0"],
    { cwd: CHECKOUT, detached: true },
  );
  servers.push(child);
  return new Promise<Started>((resolve, reject) => {
    let out = "";
    let err = "";
    child.stdout.on("data", (chunk: Buffer) => {
      out += chunk.toString();
      try {
        resolve(JSON.parse(out) as Started);
      } catch {
        // The announcement is not whole yet.
      }
    });
    child.stderr.on("data", (chunk: Buffer) => {
      err += chunk.toString();
    });
    child.on("exit", (code) => {
      reject(new Error(`the server stopped before it served (${String(code)}): ${err}`));
    });
  });
}

/** The processes still running whose command line names `marker`, as `pid command` lines. */
function runningWith(marker: string): string[] {
  return execFileSync("ps", ["-A", "-ww", "-o", "pid=,command="], { encoding: "utf8" })
    .split("\n")
    .filter((line) => line.includes(marker))
    .map((line) => line.trim());
}

async function until(gone: () => boolean, ms: number) {
  const deadline = Date.now() + ms;
  while (!gone() && Date.now() < deadline) await new Promise((resolve) => setTimeout(resolve, 50));
}

/** Stop every server this file started, then anything left naming `folder`, and remove it. */
export async function stopServers(folder: string): Promise<void> {
  for (const child of servers) {
    if (child.pid === undefined || child.exitCode !== null) continue;
    try {
      process.kill(-child.pid, "SIGINT");
    } catch {
      // Gone already.
    }
  }
  if (folder === "") return;
  await until(() => runningWith(folder).length === 0, 10_000);
  for (const line of runningWith(folder)) {
    try {
      process.kill(Number(line.split(" ")[0]), "SIGKILL");
    } catch {
      // Gone since it was listed.
    }
  }
  rmSync(folder, { recursive: true, force: true });
}

/** The origin a test's own server answers on, as a pattern for the request watch. */
export function local(url: string): RegExp {
  return new RegExp(`^${url.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`);
}
