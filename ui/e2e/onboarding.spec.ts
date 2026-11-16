import { existsSync, readFileSync } from "node:fs";
import { extname, join, sep } from "node:path";
import { fileURLToPath } from "node:url";

import AxeBuilder from "@axe-core/playwright";
import { expect, type Locator, type Page, test } from "@playwright/test";

import { cspViolations, hitAreasShort, namesNoCommand, THEMES, watch, type Watch } from "./support";

/**
 * The desktop app's own onboarding page (the welcome, the operator name and the engine step),
 * served from `desktop/status/` as the app bundles it, under the app's own content security
 * policy, read from `tauri.conf.json` here so a copy can never drift. The app itself is a stub:
 * every call the page makes into it is answered from a fixture and recorded as
 * `[command, arguments]`, in order. Each flow's list must equal the one recorded from the page
 * before its restyle (`onboarding.calls.json`): a call added, dropped, moved or given other
 * arguments fails. Where a write asks for a confirmation, the list is equal after confirming, and
 * cancelling calls nothing at all. No request leaves the page's own origin, and nothing violates
 * the policy.
 */

const json = (path: string): unknown => JSON.parse(readFileSync(path, "utf8"));

interface TauriConf {
  readonly app: { readonly security: { readonly csp: string } };
}

const DESKTOP = fileURLToPath(new URL("../../desktop/", import.meta.url));
const STATUS = join(DESKTOP, "status");
const CSP = (json(join(DESKTOP, "src-tauri", "tauri.conf.json")) as TauriConf).app.security.csp;
const CATALOGUE = json(join(DESKTOP, "onboarding", "engines.json")) as Catalogue;
const CALLS = fileURLToPath(new URL("onboarding.calls.json", import.meta.url));
const RECORDED = json(CALLS) as Record<string, Call[]>;

/** Where the rig serves the page: an origin of its own, which no real server answers. */
const RIG = "http://onboarding.rig/";
/** The app's window as the shell opens it. */
const WINDOW = { width: 1360, height: 900 };
/** The page's clock, held still: it moves only when a test moves it. */
const START = new Date("2026-11-15T12:00:00Z");

const TOKEN = "stand-in-token-0000";
const KEY = "stand-in-key-0000";
const ANSWER = "Anthropic answered: the key works.";

type Call = [string, unknown];

interface Engine {
  readonly id: string;
  readonly name: string;
  readonly detail: string;
  readonly status: string;
  readonly [more: string]: unknown;
}

interface Catalogue {
  readonly engines: readonly Engine[];
  readonly [more: string]: unknown;
}

interface Claude {
  readonly installed: boolean;
  readonly path: string | null;
  readonly version: string | null;
  readonly logged_in: boolean | null;
  readonly auth_method: string | null;
  readonly subscription: string | null;
}

interface Fixture {
  readonly intro_seen: boolean;
  readonly catalogue: Catalogue;
  readonly kept: { readonly subscription_token: boolean; readonly api_key: boolean };
  readonly claude: Claude;
  /** How many times `sign_in_status` answers "running" after a sign-in starts. */
  readonly running: number;
  readonly operator: { readonly current: string | null; readonly suggested: string | null };
  /** The commands the app refuses: each is recorded, then rejected, as a failed call is. */
  readonly rejects: readonly string[];
  /** Whether the sign-in's poll, once it stops running, reports `failed` and not `stored`. */
  readonly fails: boolean;
}

const MISSING: Claude = {
  installed: false,
  path: null,
  version: null,
  logged_in: null,
  auth_method: null,
  subscription: null,
};
const SIGNED_OUT: Claude = {
  installed: true,
  path: "/Users/stand-in/.local/bin/claude",
  version: "2.1.0 (Claude Code)",
  logged_in: false,
  auth_method: null,
  subscription: null,
};
const SIGNED_IN: Claude = { ...SIGNED_OUT, logged_in: true, subscription: "max" };
const TOKEN_KEPT = { subscription_token: true, api_key: false };
const KEY_KEPT = { subscription_token: false, api_key: true };

function fixture(changes: Partial<Fixture> = {}): Fixture {
  return {
    intro_seen: true,
    catalogue: CATALOGUE,
    kept: { subscription_token: false, api_key: false },
    claude: SIGNED_OUT,
    running: 2,
    operator: { current: null, suggested: "Ada Lovelace" },
    rejects: [],
    fails: false,
    ...changes,
  };
}

/**
 * The app, as the page reaches it: `window.__TAURI_INTERNALS__.invoke`. It runs in the page
 * before the page's own script, so it reads nothing from outside its argument.
 */
function stub(given: Fixture): void {
  const calls: [string, unknown][] = [];
  const kept: Record<string, boolean> = { ...given.kept };
  let started = false;
  let polls = 0;
  const device = {
    chip: "Apple M3 Pro",
    memory_gb: 36,
    gpu_cores: 18,
    apple_silicon: true,
    free_disk_gb: 412.5,
    models: [
      {
        name: "Llama 3.1 8B Instruct",
        memory_gb: 6,
        disk_gb: 5,
        licence: "Llama 3.1 Community License",
        source: "https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct",
        fits: true,
      },
      {
        name: "Llama 3.3 70B Instruct",
        memory_gb: 42,
        disk_gb: 40,
        licence: "Llama 3.3 Community License",
        source: "https://huggingface.co/meta-llama/Llama-3.3-70B-Instruct",
        fits: false,
      },
    ],
  };
  const answer = (cmd: string, args: Record<string, unknown>): unknown => {
    switch (cmd) {
      case "onboarding_state":
        return {
          intro_seen: given.intro_seen,
          engine: null,
          implementer: null,
          reviewer: null,
          catalogue: given.catalogue,
          kept: { ...kept },
        };
      case "claude_code_detect":
        return given.claude;
      case "sign_in_start":
        started = true;
        return { phase: "running", lines: [], message: null };
      case "sign_in_cancel":
        started = false;
        return null;
      case "sign_in_status":
        if (!started) return { phase: "idle", lines: [], message: null };
        polls += 1;
        if (polls <= given.running)
          return { phase: "running", lines: ["Opening your browser to sign in…"], message: null };
        if (given.fails) return { phase: "failed", lines: [], message: "Sign-in did not finish." };
        kept.subscription_token = true;
        return { phase: "stored", lines: [], message: "Kept in the macOS Keychain." };
      case "store_secret":
        kept[String(args.secret)] = true;
        return null;
      case "forget_secret":
        kept[String(args.secret)] = false;
        return null;
      case "test_api_key":
        return "Anthropic answered: the key works.";
      case "device_report":
        return device;
      case "operator_state":
        return given.operator;
      default:
        return null;
    }
  };
  const app = {
    invoke: (cmd: string, args?: Record<string, unknown>): Promise<unknown> => {
      calls.push([cmd, JSON.parse(JSON.stringify(args ?? null)) as unknown]);
      if (given.rejects.includes(cmd))
        return Promise.reject(new Error(`stand-in refusal of ${cmd}`));
      return Promise.resolve(answer(cmd, args ?? {}));
    },
  };
  Object.assign(window, { __TAURI_INTERNALS__: app, recordedCalls: calls });
}

const TYPES: Readonly<Record<string, string>> = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".png": "image/png",
  ".gif": "image/gif",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2",
  ".txt": "text/plain; charset=utf-8",
};

interface Rig extends Watch {
  /** The page's own requests for a file the folder does not hold. */
  readonly missing: string[];
}

/**
 * Serve `desktop/status/` at the rig's origin under the app's policy, with the app stubbed and
 * the page's clock held, so the film's timer and the sign-in's poll move only when a test says.
 * ``edit`` changes the page's markup as it is served (the canary row's planted style).
 */
async function rig(page: Page, given: Fixture, edit?: (html: string) => string): Promise<Rig> {
  await page.setViewportSize(WINDOW);
  const seen = await watch(page, /^http:\/\/onboarding\.rig\//);
  const missing: string[] = [];
  // Registered after the watch, so it answers the rig's own requests first.
  await page.route(`${RIG}**`, async (route) => {
    const path = decodeURIComponent(new URL(route.request().url()).pathname).replace(/^\/+/, "");
    const file = join(STATUS, path);
    if (!file.startsWith(STATUS + sep) || !existsSync(file)) {
      if (path !== "favicon.ico") missing.push(path);
      await route.fulfill({ status: 404, body: "" });
      return;
    }
    let body: Buffer | string = readFileSync(file);
    if (edit !== undefined && path === "onboarding.html") body = edit(body.toString());
    await route.fulfill({
      status: 200,
      body,
      headers: {
        "content-type": TYPES[extname(file)] ?? "application/octet-stream",
        "content-security-policy": CSP,
      },
    });
  });
  await page.clock.install({ time: START });
  await page.clock.pauseAt(new Date(START.getTime() + 1000));
  await page.addInitScript(stub, given);
  return { ...seen, missing };
}

async function open(page: Page, step: string) {
  await page.goto(`${RIG}onboarding.html${step === "" ? "" : `#${step}`}`);
}

async function calls(page: Page): Promise<Call[]> {
  return page.evaluate(() => (window as unknown as { recordedCalls: Call[] }).recordedCalls);
}

function recorded(flow: string): Call[] {
  const list = RECORDED[flow];
  if (list === undefined) throw new Error(`no recorded list for "${flow}"`);
  return list;
}

/** Wait until the calls so far are the recorded list's first ``n``, in order. */
async function upTo(page: Page, flow: string, n: number) {
  const want = recorded(flow).slice(0, n);
  const message = `${flow}, its first ${String(n)} calls`;
  await expect.poll(() => calls(page), { message }).toEqual(want);
}

/** A moment of real time, for anything still on its way. */
const settle = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 300));

const button = (page: Page, name: RegExp): Locator => page.getByRole("button", { name });
const card = (page: Page, name: string): Locator =>
  page.getByRole("radio", { name: new RegExp(`^${name}`) });
const confirmation = (page: Page): Locator => page.locator("dialog[open]");

/** Where a write asks for a confirmation, confirm it. Where it asks none, do nothing. */
async function confirmIfAsked(page: Page) {
  const dialog = confirmation(page);
  if ((await dialog.count()) > 0) await dialog.locator(".pg-btn-act").click();
}

/** The engine panel has finished drawing: its last call was made and answered. */
async function engineStepDrawn(page: Page, flow: string, n: number) {
  await upTo(page, flow, n);
  await expect(page.locator("#panel h2").first()).toBeVisible();
}

/** The operator page has its name and its handlers: the value is set in the same step. */
async function operatorDrawn(page: Page, flow: string) {
  await upTo(page, flow, 2);
  await expect(page.locator("#operator-name")).toHaveValue("Ada Lovelace");
}

/** The film's timer starts when the film has loaded: move the clock until it has run out. */
async function filmEnds(page: Page) {
  const ran = async (): Promise<number> => {
    await page.clock.runFor(1000);
    return (await calls(page)).length;
  };
  await expect.poll(ran).toBeGreaterThan(1);
}

interface Flow {
  readonly name: string;
  readonly step: string;
  readonly given: Fixture;
  readonly walk: (page: Page, flow: string) => Promise<void>;
}

const FLOWS: readonly Flow[] = [
  {
    name: "the welcome, skipped",
    step: "",
    given: fixture({ intro_seen: false }),
    walk: async (page, flow) => {
      await upTo(page, flow, 1);
      await page.locator("#skip").click();
      await engineStepDrawn(page, flow, 6);
    },
  },
  {
    name: "the welcome, played to its end",
    step: "",
    given: fixture({ intro_seen: false }),
    walk: async (page, flow) => {
      await upTo(page, flow, 1);
      await filmEnds(page);
      await engineStepDrawn(page, flow, 6);
    },
  },
  {
    name: "no Claude Code",
    step: "engine",
    given: fixture({ claude: MISSING }),
    walk: async (page, flow) => {
      await engineStepDrawn(page, flow, 4);
    },
  },
  {
    name: "install Claude Code",
    step: "engine",
    given: fixture({ claude: MISSING }),
    walk: async (page, flow) => {
      await engineStepDrawn(page, flow, 4);
      await button(page, /^open in terminal/i).click();
      await upTo(page, flow, 5);
      await button(page, /^check again/i).click();
      await engineStepDrawn(page, flow, 7);
    },
  },
  {
    name: "sign in",
    step: "engine",
    given: fixture(),
    walk: async (page, flow) => {
      await engineStepDrawn(page, flow, 5);
      await button(page, /^sign in…?$/i).click();
      await upTo(page, flow, 7);
      await button(page, /^press return/i).click();
      await upTo(page, flow, 8);
      await page.clock.runFor(700);
      await upTo(page, flow, 9);
      await page.clock.runFor(700);
      await engineStepDrawn(page, flow, 13);
    },
  },
  {
    name: "sign in, stopped",
    step: "engine",
    given: fixture(),
    walk: async (page, flow) => {
      await engineStepDrawn(page, flow, 5);
      await button(page, /^sign in…?$/i).click();
      await upTo(page, flow, 7);
      await button(page, /^stop/i).click();
      await upTo(page, flow, 8);
      await page.clock.runFor(700);
      await upTo(page, flow, 9);
    },
  },
  {
    name: "sign in in Terminal",
    step: "engine",
    given: fixture(),
    walk: async (page, flow) => {
      await engineStepDrawn(page, flow, 5);
      await page.locator("#sign-in summary").click();
      await button(page, /^open in terminal/i).click();
      await upTo(page, flow, 6);
      await page.locator('#sign-in input[type="password"]').fill(TOKEN);
      await button(page, /^keep token/i).click();
      await confirmIfAsked(page);
      await engineStepDrawn(page, flow, 11);
    },
  },
  {
    name: "forget the token",
    step: "engine",
    given: fixture({ claude: SIGNED_IN, kept: TOKEN_KEPT }),
    walk: async (page, flow) => {
      await engineStepDrawn(page, flow, 5);
      await button(page, /^remove the token/i).click();
      await confirmIfAsked(page);
      await engineStepDrawn(page, flow, 10);
    },
  },
  {
    name: "API key: keep, test and forget",
    step: "engine",
    given: fixture(),
    walk: async (page, flow) => {
      await engineStepDrawn(page, flow, 5);
      await card(page, "Claude API").click();
      await upTo(page, flow, 6);
      await expect(page.locator("#implementer")).toBeVisible();
      await page.locator('#panel input[type="password"]').fill(KEY);
      await button(page, /^keep key/i).click();
      await confirmIfAsked(page);
      await upTo(page, flow, 9);
      await button(page, /^test key/i).click();
      await upTo(page, flow, 10);
      await expect(page.locator("#test-result")).toHaveText(ANSWER);
      await button(page, /^remove the key/i).click();
      await confirmIfAsked(page);
      await upTo(page, flow, 13);
      await expect(page.locator('#panel input[type="password"]')).toBeVisible();
    },
  },
  {
    name: "choose an engine: the Claude API",
    step: "engine",
    given: fixture({ kept: KEY_KEPT }),
    walk: async (page, flow) => {
      await engineStepDrawn(page, flow, 5);
      await card(page, "Claude API").click();
      await upTo(page, flow, 6);
      await page.locator("#reviewer").selectOption("claude-haiku-4-5-20251001");
      await expect(page.locator("#continue")).toBeEnabled();
      await page.locator("#continue").click();
      await confirmIfAsked(page);
      await upTo(page, flow, 8);
    },
  },
  {
    name: "choose an engine: Claude Code",
    step: "engine",
    given: fixture({ claude: SIGNED_IN, kept: TOKEN_KEPT }),
    walk: async (page, flow) => {
      await engineStepDrawn(page, flow, 5);
      await expect(page.locator("#continue")).toBeEnabled();
      await page.locator("#continue").click();
      await confirmIfAsked(page);
      await upTo(page, flow, 7);
    },
  },
  {
    name: "the engines not available yet",
    step: "engine",
    given: fixture(),
    walk: async (page, flow) => {
      await engineStepDrawn(page, flow, 5);
      await card(page, "A model on this Mac").click();
      await upTo(page, flow, 6);
      await expect(page.locator("#panel table")).toHaveCount(2);
      await expect(page.locator("#continue")).toBeDisabled();
      await card(page, "OpenAI API").click();
      await expect(page.locator("#panel h2").first()).toContainText("OpenAI API");
      await expect(page.locator("#continue")).toBeDisabled();
    },
  },
  {
    name: "set up later",
    step: "engine",
    given: fixture(),
    walk: async (page, flow) => {
      await engineStepDrawn(page, flow, 5);
      await button(page, /^set up later/i).click();
      await upTo(page, flow, 6);
    },
  },
  {
    name: "operator name",
    step: "operator",
    given: fixture(),
    walk: async (page, flow) => {
      await operatorDrawn(page, flow);
      await button(page, /^decide as this name/i).click();
      await confirmIfAsked(page);
      await upTo(page, flow, 3);
    },
  },
  {
    name: "stay read-only",
    step: "operator",
    given: fixture(),
    walk: async (page, flow) => {
      await operatorDrawn(page, flow);
      await button(page, /^stay read-only/i).click();
      await confirmIfAsked(page);
      await upTo(page, flow, 3);
    },
  },
];

// -- error paths: begin (a proof builds its own spec from here to the end marker) ------------

/** The first calls of an engine step, as the page draws it, and of the operator step. */
const ENGINE_5 = 5;

const ERROR_FLOWS: readonly Flow[] = [
  {
    name: "error: keeping the token from Terminal is refused",
    step: "engine",
    given: fixture({ rejects: ["store_secret"] }),
    walk: async (page, flow) => {
      await engineStepDrawn(page, flow, ENGINE_5);
      await page.locator("#sign-in summary").click();
      await page.locator('#sign-in input[type="password"]').fill(TOKEN);
      await button(page, /^keep token/i).click();
      await confirmIfAsked(page);
      await upTo(page, flow, 6);
      await expect(page.locator("#problem")).toContainText("stand-in refusal of store_secret");
    },
  },
  {
    name: "error: keeping the API key is refused",
    step: "engine",
    given: fixture({ rejects: ["store_secret"] }),
    walk: async (page, flow) => {
      await engineStepDrawn(page, flow, ENGINE_5);
      await card(page, "Claude API").click();
      await upTo(page, flow, 6);
      await page.locator('#panel input[type="password"]').fill(KEY);
      await button(page, /^keep key/i).click();
      await confirmIfAsked(page);
      await upTo(page, flow, 7);
      await expect(page.locator("#problem")).toContainText("stand-in refusal of store_secret");
    },
  },
  {
    name: "error: choosing the engine is refused",
    step: "engine",
    given: fixture({ claude: SIGNED_IN, kept: TOKEN_KEPT, rejects: ["choose_engine"] }),
    walk: async (page, flow) => {
      await engineStepDrawn(page, flow, ENGINE_5);
      await expect(page.locator("#continue")).toBeEnabled();
      await page.locator("#continue").click();
      await confirmIfAsked(page);
      await upTo(page, flow, 6);
      await expect(page.locator("#problem")).toContainText("stand-in refusal of choose_engine");
    },
  },
  {
    name: "error: the sign-in does not start",
    step: "engine",
    given: fixture({ rejects: ["sign_in_start"] }),
    walk: async (page, flow) => {
      await engineStepDrawn(page, flow, ENGINE_5);
      await button(page, /^sign in…?$/i).click();
      await upTo(page, flow, 6);
      await expect(page.locator("#problem")).toContainText("stand-in refusal of sign_in_start");
      await page.clock.runFor(2100);
    },
  },
  {
    name: "error: the sign-in's poll reports it failed",
    step: "engine",
    given: fixture({ running: 0, fails: true }),
    walk: async (page, flow) => {
      await engineStepDrawn(page, flow, ENGINE_5);
      await button(page, /^sign in…?$/i).click();
      await upTo(page, flow, 7);
      await expect(page.locator("#progress")).toContainText("Sign-in did not finish.");
      await page.clock.runFor(2100);
    },
  },
  {
    name: "error: the installer does not start",
    step: "engine",
    given: fixture({ claude: MISSING, rejects: ["claude_code_install"] }),
    walk: async (page, flow) => {
      await engineStepDrawn(page, flow, 4);
      await button(page, /^open in terminal/i).click();
      await upTo(page, flow, 5);
      await expect(page.locator("#problem")).toContainText("stand-in refusal of claude_code_install");
    },
  },
  {
    name: "error: the key test is refused",
    step: "engine",
    given: fixture({ kept: KEY_KEPT, rejects: ["test_api_key"] }),
    walk: async (page, flow) => {
      await engineStepDrawn(page, flow, ENGINE_5);
      await card(page, "Claude API").click();
      await upTo(page, flow, 6);
      await button(page, /^test key/i).click();
      await upTo(page, flow, 7);
      await expect(page.locator("#test-result")).toContainText("stand-in refusal of test_api_key");
    },
  },
  {
    name: "error: the operator name is refused",
    step: "operator",
    given: fixture({ rejects: ["set_operator"] }),
    walk: async (page, flow) => {
      await operatorDrawn(page, flow);
      await button(page, /^decide as this name/i).click();
      await confirmIfAsked(page);
      await upTo(page, flow, 3);
      await expect(page.locator("#operator-problem")).toContainText(
        "That name can't be used: Error: stand-in refusal of set_operator.",
      );
    },
  },
];

test.describe("an error from the app changes no call: the page makes the calls it always made", () => {
  for (const flow of ERROR_FLOWS) {
    test(flow.name, async ({ page }) => {
      const seen = await rig(page, flow.given);
      await open(page, flow.step);
      await flow.walk(page, flow.name);
      await settle();
      expect(await calls(page)).toEqual(recorded(flow.name));
      await holds(page, seen, flow.name);
    });
  }
});

// -- error paths: end ------------------------------------------------------------------------

/** What every view of the page holds to: its own origin only, no violation, no command. */
async function holds(page: Page, seen: Rig, where: string) {
  expect(seen.outbound, where).toEqual([]);
  expect(seen.missing, where).toEqual([]);
  expect(await cspViolations(page), where).toEqual([]);
  expect(await page.locator("[style]").count(), where).toBe(0);
  await namesNoCommand(page, where);
}

const notComment = (key: string): boolean => key !== "$comment";

test.describe("each flow calls into the app exactly as the page did before its restyle", () => {
  test("every recorded flow has a walk, and every walk a recorded list", () => {
    const walked = [...FLOWS, ...ERROR_FLOWS].map((f) => f.name).sort();
    expect(walked).toEqual(Object.keys(RECORDED).filter(notComment).sort());
  });

  for (const flow of FLOWS) {
    test(flow.name, async ({ page }) => {
      const seen = await rig(page, flow.given);
      await open(page, flow.step);
      await flow.walk(page, flow.name);
      // Settled: nothing more arrives once the walk is done.
      await settle();
      expect(await calls(page)).toEqual(recorded(flow.name));
      await holds(page, seen, flow.name);
    });
  }
});

interface Write {
  readonly name: string;
  readonly flow: string;
  readonly step: string;
  readonly given: Fixture;
  /** Walk up to the write; returns how many calls are made before it. */
  readonly before: (page: Page, flow: string) => Promise<number>;
  readonly trigger: (page: Page) => Locator;
  /** What the confirmation must name. */
  readonly names: readonly string[];
}

const WRITES: readonly Write[] = [
  {
    name: "keeping the token from Terminal",
    flow: "sign in in Terminal",
    step: "engine",
    given: fixture(),
    before: async (page, flow) => {
      await engineStepDrawn(page, flow, 5);
      await page.locator("#sign-in summary").click();
      await page.locator('#sign-in input[type="password"]').fill(TOKEN);
      return 5;
    },
    trigger: (page) => button(page, /^keep token/i),
    names: ["macOS Keychain"],
  },
  {
    name: "forgetting the token",
    flow: "forget the token",
    step: "engine",
    given: fixture({ claude: SIGNED_IN, kept: TOKEN_KEPT }),
    before: async (page, flow) => {
      await engineStepDrawn(page, flow, 5);
      return 5;
    },
    trigger: (page) => button(page, /^remove the token/i),
    names: ["macOS Keychain"],
  },
  {
    name: "keeping the API key",
    flow: "API key: keep, test and forget",
    step: "engine",
    given: fixture(),
    before: async (page, flow) => {
      await engineStepDrawn(page, flow, 5);
      await card(page, "Claude API").click();
      await upTo(page, flow, 6);
      await page.locator('#panel input[type="password"]').fill(KEY);
      return 6;
    },
    trigger: (page) => button(page, /^keep key/i),
    names: ["macOS Keychain"],
  },
  {
    name: "forgetting the API key",
    flow: "choose an engine: the Claude API",
    step: "engine",
    given: fixture({ kept: KEY_KEPT }),
    before: async (page, flow) => {
      await engineStepDrawn(page, flow, 5);
      await card(page, "Claude API").click();
      await upTo(page, flow, 6);
      return 6;
    },
    trigger: (page) => button(page, /^remove the key/i),
    names: ["macOS Keychain"],
  },
  {
    name: "choosing the engine",
    flow: "choose an engine: the Claude API",
    step: "engine",
    given: fixture({ kept: KEY_KEPT }),
    before: async (page, flow) => {
      await engineStepDrawn(page, flow, 5);
      await card(page, "Claude API").click();
      await upTo(page, flow, 6);
      await page.locator("#reviewer").selectOption("claude-haiku-4-5-20251001");
      return 6;
    },
    trigger: (page) => page.locator("#continue"),
    names: ["Claude API", "Claude Opus 5.5", "Claude Haiku 4.5"],
  },
  {
    name: "setting the operator",
    flow: "operator name",
    step: "operator",
    given: fixture(),
    before: async (page, flow) => {
      await operatorDrawn(page, flow);
      await page.locator("#operator-name").fill("Grace Hopper");
      return 2;
    },
    trigger: (page) => button(page, /^decide as this name/i),
    names: ["Grace Hopper"],
  },
  {
    name: "staying read-only",
    flow: "stay read-only",
    step: "operator",
    given: fixture(),
    before: async (page, flow) => {
      await operatorDrawn(page, flow);
      return 2;
    },
    trigger: (page) => button(page, /^stay read-only/i),
    names: ["Operator", "read-only"],
  },
];

test.describe("each write asks first, names what it writes, and a cancel calls nothing", () => {
  for (const write of WRITES) {
    for (const how of ["Cancel", "Escape"] as const) {
      test(`${write.name}, cancelled by ${how}`, async ({ page }) => {
        const seen = await rig(page, write.given);
        await open(page, write.step);
        const n = await write.before(page, write.flow);
        const trigger = write.trigger(page);
        await expect(trigger).toHaveText(/…$/);
        await expect(trigger).toHaveClass(/\bpg-btn-act\b/);
        await trigger.click();
        const dialog = confirmation(page);
        await expect(dialog).toBeVisible();
        const said = (await dialog.textContent()) ?? "";
        for (const name of write.names) expect(said).toContain(name);
        expect(said).not.toContain(TOKEN);
        expect(said).not.toContain(KEY);
        if (how === "Cancel") await dialog.getByRole("button", { name: /^cancel$/i }).click();
        else await page.keyboard.press("Escape");
        await expect(confirmation(page)).toHaveCount(0);
        await settle();
        expect(await calls(page)).toEqual(recorded(write.flow).slice(0, n));
        await holds(page, seen, write.name);
      });
    }
  }
});

test.describe("the page under the app's policy", () => {
  test("the canary: one planted style attribute is exactly one violation", async ({ page }) => {
    await rig(page, fixture(), (html) => html.replace("<body", '<body style="margin: 0"'));
    await open(page, "engine");
    await expect(page.locator("#panel h2").first()).toBeVisible();
    await expect.poll(() => cspViolations(page)).toHaveLength(1);
  });

  test("every text from the app is shown as text, never as markup", async ({ page }) => {
    const planted = "<img src=x>Marked-up engine";
    const catalogue: Catalogue = {
      ...CATALOGUE,
      engines: [
        ...CATALOGUE.engines,
        { id: "planted", name: planted, detail: "<b>bold</b> detail", status: "not-yet" },
      ],
    };
    const seen = await rig(page, fixture({ catalogue }));
    await open(page, "engine");
    await expect(page.locator("#panel h2").first()).toBeVisible();
    await expect(card(page, planted)).toHaveCount(1);
    await expect(page.locator("#cards img, #cards b")).toHaveCount(0);
    await card(page, planted).click();
    await expect(page.locator("#panel h2").first()).toContainText(planted);
    await expect(page.locator("#panel img, #panel b")).toHaveCount(0);
    await holds(page, seen, "planted markup");
  });

  test("an operator name with markup in it is a value, never markup", async ({ page }) => {
    const given = fixture({ operator: { current: null, suggested: "<b>Ada</b> Lovelace" } });
    const seen = await rig(page, given);
    await open(page, "operator");
    await expect(page.locator("#operator-name")).toHaveValue("<b>Ada</b> Lovelace");
    await expect(page.locator("#operator-page b")).toHaveCount(0);
    await holds(page, seen, "planted operator");
  });
});

interface View {
  readonly name: string;
  readonly step: string;
  readonly given: Fixture;
  readonly reach?: (page: Page) => Promise<void>;
}

/** The views a person sees, each reached the way a person reaches it. */
const VIEWS: readonly View[] = [
  { name: "the welcome", step: "intro", given: fixture({ intro_seen: false }) },
  { name: "Claude Code missing", step: "engine", given: fixture({ claude: MISSING }) },
  { name: "Claude Code signed out", step: "engine", given: fixture() },
  { name: "signed in for runs", step: "engine", given: fixture({ kept: TOKEN_KEPT }) },
  {
    name: "the Claude API with a key kept",
    step: "engine",
    given: fixture({ kept: KEY_KEPT }),
    reach: async (page) => {
      await card(page, "Claude API").click();
      await expect(page.locator("#implementer")).toBeVisible();
    },
  },
  {
    name: "a model on this Mac",
    step: "engine",
    given: fixture(),
    reach: async (page) => {
      await card(page, "A model on this Mac").click();
      await expect(page.locator("#panel table")).toHaveCount(2);
    },
  },
  { name: "who decides here", step: "operator", given: fixture() },
];

/** The families of the faces the page has, and of those it has loaded. */
async function faces(page: Page): Promise<{ declared: string[]; loaded: string[] }> {
  return page.evaluate(async () => {
    await document.fonts.ready;
    const all = [...document.fonts];
    const family = (f: FontFace): string => f.family.replace(/"/g, "");
    return {
      declared: all.map(family),
      loaded: all.filter((f) => f.status === "loaded").map(family),
    };
  });
}

async function axeClean(page: Page, where: string) {
  const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(
    axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`),
    where,
  ).toEqual([]);
}

test.describe("the page is the app's, in both themes", () => {
  for (const theme of THEMES) {
    for (const view of VIEWS) {
      test(`${view.name} (${theme})`, async ({ page }) => {
        await page.emulateMedia({ colorScheme: theme });
        const seen = await rig(page, view.given);
        await open(page, view.step);
        if (view.step === "engine") await expect(page.locator("#panel h2").first()).toBeVisible();
        if (view.reach !== undefined) await view.reach(page);
        await holds(page, seen, view.name);
        // The app's own faces, from the app's own files.
        const found = await faces(page);
        expect(found.declared).toContain("Instrument Sans");
        expect(found.declared).toContain("JetBrains Mono");
        expect(found.loaded).toContain("Instrument Sans");
        // axe waits on the page's timers: let them run.
        await page.clock.resume();
        await axeClean(page, view.name);
        expect(
          await hitAreasShort(page, "button:visible, [role='radio'], summary, select, input"),
          view.name,
        ).toEqual([]);
      });
    }
  }
});

test.describe("the engine step, by keyboard", () => {
  test("the engines are one radio group: arrow keys move the choice", async ({ page }) => {
    await rig(page, fixture());
    await open(page, "engine");
    await expect(page.locator("#panel h2").first()).toBeVisible();
    // One stop in the tab order: the chosen engine.
    const radios = page.locator("#cards [role='radio']");
    const tabs = await radios.evaluateAll((all) => all.map((r) => r.tabIndex));
    const ids = CATALOGUE.engines.map((e) => e.id);
    expect(tabs).toEqual(ids.map((id) => (id === "claude-code" ? 0 : -1)));
    await card(page, "Claude Code").focus();
    await page.keyboard.press("ArrowDown");
    await expect(card(page, "Claude API")).toBeFocused();
    await expect(card(page, "Claude API")).toHaveAttribute("aria-checked", "true");
    await expect(card(page, "Claude Code")).toHaveAttribute("aria-checked", "false");
    await page.keyboard.press("ArrowUp");
    await expect(card(page, "Claude Code")).toBeFocused();
    await expect(card(page, "Claude Code")).toHaveAttribute("aria-checked", "true");
    // From the first, round to the last, and back.
    await page.keyboard.press("ArrowLeft");
    await expect(card(page, "A model on this Mac")).toBeFocused();
    await expect(card(page, "A model on this Mac")).toHaveAttribute("aria-checked", "true");
    await page.keyboard.press("ArrowRight");
    await expect(card(page, "Claude Code")).toBeFocused();
  });

  test("a Not yet engine can be read about and is never the choice", async ({ page }) => {
    await rig(page, fixture());
    await open(page, "engine");
    await expect(page.locator("#panel h2").first()).toBeVisible();
    for (const engine of CATALOGUE.engines.filter((e) => e.status !== "available")) {
      await expect(card(page, engine.name).locator(".pg-badge")).toHaveText("Not yet");
      await card(page, engine.name).click();
      await expect(page.locator("#panel h2").first()).toContainText(engine.name);
      await expect(page.locator("#continue")).toBeDisabled();
    }
  });

  test("the steps say where the person is, in words", async ({ page }) => {
    await rig(page, fixture());
    await open(page, "engine");
    await expect(page.locator(".steps")).toContainText("Step 2 of 3");
  });

  test("focus moves to each panel's heading when the panel changes", async ({ page }) => {
    await rig(page, fixture({ intro_seen: false }));
    await open(page, "");
    await expect(page.locator("#skip")).toBeFocused();
    await page.locator("#skip").click();
    const heading = page.getByRole("heading", { level: 1, name: "Connect the engine" });
    await expect(heading).toBeFocused();
  });

  test("focus starts on the operator page's heading", async ({ page }) => {
    await rig(page, fixture());
    await open(page, "operator");
    const heading = page.getByRole("heading", { level: 1, name: "Who decides here?" });
    await expect(heading).toBeFocused();
  });
});

test.describe("a trigger other than a plain click makes the calls a click makes", () => {
  /** Two confirmations in one task: the second lands on a dialog the first has closed. */
  const twice = (page: Page) =>
    confirmation(page)
      .locator(".pg-btn-act")
      .evaluate((ok) => {
        (ok as HTMLElement).click();
        (ok as HTMLElement).click();
      });

  test("a dialog confirmed twice at once makes its call once: the engine", async ({ page }) => {
    const flow = "choose an engine: Claude Code";
    const seen = await rig(page, fixture({ claude: SIGNED_IN, kept: TOKEN_KEPT }));
    await open(page, "engine");
    await engineStepDrawn(page, flow, 5);
    await page.locator("#continue").click();
    await expect(confirmation(page)).toBeVisible();
    await twice(page);
    await settle();
    expect(await calls(page)).toEqual(recorded(flow));
    await holds(page, seen, flow);
  });

  test("a dialog confirmed twice at once makes its call once: the operator", async ({ page }) => {
    const flow = "operator name";
    const seen = await rig(page, fixture());
    await open(page, "operator");
    await operatorDrawn(page, flow);
    await button(page, /^decide as this name/i).click();
    await expect(confirmation(page)).toBeVisible();
    await twice(page);
    await settle();
    expect(await calls(page)).toEqual(recorded(flow));
    await holds(page, seen, flow);
  });

  test("an arrow key onto the Claude API makes the calls clicking its card makes", async ({
    page,
  }) => {
    const flow = "API key: keep, test and forget";
    const seen = await rig(page, fixture());
    await open(page, "engine");
    await engineStepDrawn(page, flow, 5);
    await card(page, "Claude Code").focus();
    await page.keyboard.press("ArrowDown");
    await expect(card(page, "Claude API")).toHaveAttribute("aria-checked", "true");
    await upTo(page, flow, 6);
    await settle();
    expect(await calls(page)).toEqual(recorded(flow).slice(0, 6));
    await holds(page, seen, "an arrow key onto the Claude API");
  });

  test("an arrow key onto a model on this Mac makes the calls clicking its card makes", async ({
    page,
  }) => {
    const flow = "the engines not available yet";
    const seen = await rig(page, fixture());
    await open(page, "engine");
    await engineStepDrawn(page, flow, 5);
    await card(page, "Claude Code").focus();
    await page.keyboard.press("ArrowLeft");
    await expect(card(page, "A model on this Mac")).toHaveAttribute("aria-checked", "true");
    await upTo(page, flow, 6);
    await settle();
    expect(await calls(page)).toEqual(recorded(flow));
    await holds(page, seen, "an arrow key onto a model on this Mac");
  });

  test("Enter in the operator name makes the calls clicking its button makes", async ({ page }) => {
    const flow = "operator name";
    const seen = await rig(page, fixture());
    await open(page, "operator");
    await operatorDrawn(page, flow);
    await page.locator("#operator-name").focus();
    await page.keyboard.press("Enter");
    await confirmIfAsked(page);
    await upTo(page, flow, 3);
    await settle();
    expect(await calls(page)).toEqual(recorded(flow));
    await holds(page, seen, "Enter in the operator name");
  });
});
