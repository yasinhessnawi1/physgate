// The welcome and the engine step. Everything shown is set as text, never as markup.
// Credentials go one way: from a field into the app (which keeps them in the Keychain). The
// state this page reads says only whether one is kept, never what it is.
"use strict";

const invoke = (cmd, args) => window.__TAURI_INTERNALS__.invoke(cmd, args || {});
const $ = (id) => document.getElementById(id);

function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v === true) node.setAttribute(k, "");
    else if (v !== false && v != null) node.setAttribute(k, v);
  }
  for (const child of children.flat()) {
    if (child == null || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

let state = null;
let chosen = null;
let claude = null;
let polling = null;

function problem(text) {
  const p = $("problem");
  p.textContent = text || "";
  p.hidden = !text;
}

async function refresh() {
  state = await invoke("onboarding_state");
}

// ---- Welcome -----------------------------------------------------------------------

/** The intro film's length, in milliseconds, so the page moves on when it ends. */
const INTRO_MS = 7000;

function showIntro() {
  $("setup").hidden = true;
  $("intro").hidden = false;
  const film = $("intro-film");
  let finished = false;
  const done = async () => {
    if (finished) return;
    finished = true;
    await invoke("intro_seen").catch(() => {});
    showEngine();
  };
  $("skip").onclick = done;
  document.onkeydown = (event) => {
    if (event.key === "Escape" || event.key === "Enter") done();
  };
  $("skip").focus();
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    // The last frame, still, instead of the motion.
    film.src = "intro-poster.png";
    $("skip").textContent = "Continue";
    return;
  }
  // An animated image, played once: it needs no media permission, so it starts by itself.
  film.onload = () => setTimeout(done, INTRO_MS + 500);
  film.src = "intro.gif";
}

// ---- Engine ------------------------------------------------------------------------

async function showEngine() {
  document.onkeydown = null;
  $("intro").hidden = true;
  $("setup").hidden = false;
  await refresh();
  const engines = state.catalogue.engines;
  chosen = state.engine || "claude-code";
  const cards = $("cards");
  cards.replaceChildren(
    ...engines.map((engine) =>
      el("button", {
        class: "card", type: "button", role: "radio", "data-id": engine.id,
        "aria-checked": String(engine.id === chosen),
        onclick: () => select(engine.id),
      },
      el("span", { class: "name" }, engine.name),
      el("span", { class: "detail" }, engine.detail),
      el("span", { class: `badge ${engine.status}` }, engine.status === "available" ? "Available" : "Not available yet")),
    ),
  );
  $("later").onclick = finish;
  $("continue").onclick = continueWith;
  select(chosen);
}

function engineById(id) {
  return state.catalogue.engines.find((e) => e.id === id);
}

async function select(id) {
  chosen = id;
  problem("");
  for (const card of document.querySelectorAll(".card")) {
    card.setAttribute("aria-checked", String(card.dataset.id === id));
  }
  stopPolling();
  const engine = engineById(id);
  if (engine.status !== "available") return renderNotYet(engine);
  if (id === "claude-code") return renderClaudeCode();
  if (id === "claude-api") return renderApi(engine);
}

function canContinue(ok) {
  $("continue").disabled = !ok;
}

// Claude Code ------------------------------------------------------------------------

async function renderClaudeCode() {
  claude = await invoke("claude_code_detect");
  await refresh();
  const box = el("div", { class: "box" });
  if (!claude.installed) {
    box.append(
      el("h2", {}, "Claude Code is not installed"),
      el("p", {}, "Install it with Anthropic's official installer. It runs in Terminal, where you can see every step."),
      el("ol", { class: "howto" },
        el("li", {}, "Open Terminal with the installer. It runs this command:",
          el("pre", { class: "copy" }, state.install_command),
          el("div", { class: "row" }, el("button", { type: "button", onclick: install }, "Open in Terminal"))),
        el("li", {}, "Wait until Terminal says it is done. It downloads Claude Code from Anthropic."),
        el("li", {}, "Come back here and check again.",
          el("div", { class: "row" }, el("button", { type: "button", onclick: renderClaudeCode }, "Check Again")))),
    );
    canContinue(false);
    return $("panel").replaceChildren(box);
  }
  const own = claude.logged_in
    ? `Claude Code itself is signed in${claude.subscription ? ` (${claude.subscription} plan)` : ""}.`
    : "Claude Code itself is not signed in; that does not stop runs, which use their own token.";
  box.append(
    el("h2", {}, "Claude Code"),
    el("p", { class: "ok" }, `Installed: ${claude.version || "version unknown"}`),
    el("p", {}, `At ${claude.path}. ${own}`),
  );
  box.append(signInSection());
  $("panel").replaceChildren(box);
  canContinue(state.kept.subscription_token);
  const view = await invoke("sign_in_status");
  if (view.phase === "running") startPolling();
}

function signInSection() {
  const section = el("div", { class: "box", id: "sign-in" });
  if (state.kept.subscription_token) {
    section.append(
      el("h2", {}, "Signed in for runs"),
      el("p", { class: "ok" }, "A token is kept in the macOS Keychain. It is never shown."),
      el("p", {}, "To start a run from Terminal, load it first with this line. It names the Keychain item and holds no secret:"),
      el("pre", { class: "copy" }, state.handover.subscription_token),
      el("div", { class: "row" }, el("button", { type: "button", onclick: () => forget("subscription_token") }, "Remove the Token")),
    );
    return section;
  }
  section.append(
    el("h2", {}, "Sign in for runs"),
    el("p", {}, "Runs need a long-lived token from your subscription. Signing in opens your browser. " +
      "The token goes straight into the macOS Keychain and is never shown here."),
    el("div", { class: "row" }, el("button", { class: "primary", type: "button", onclick: signIn }, "Sign In")),
    el("div", { id: "progress" }),
    el("details", {},
      el("summary", {}, "Sign in in Terminal instead"),
      el("div", { class: "box" },
        el("p", {}, "Terminal runs the sign-in and prints the token. Paste it here; it goes to the Keychain."),
        el("div", { class: "row" }, el("button", { type: "button", onclick: () => invoke("sign_in_in_terminal").catch(problem) }, "Open in Terminal")),
        secretField("subscription_token", "Token from Terminal", "Keep Token"))),
  );
  return section;
}

async function install() {
  problem("");
  await invoke("claude_code_install").catch(problem);
}

async function signIn() {
  problem("");
  try {
    await invoke("sign_in_start");
    startPolling();
  } catch (e) {
    problem(String(e));
  }
}

function startPolling() {
  stopPolling();
  const tick = async () => {
    const view = await invoke("sign_in_status");
    const progress = $("progress");
    if (progress) {
      progress.replaceChildren(...[
        el("pre", { class: "log" }, (view.lines || []).join("\n") || "Starting…"),
        view.message ? el("p", { class: view.phase === "failed" ? "warn" : "ok" }, view.message) : null,
        view.phase === "running"
          ? el("div", { class: "row" },
              el("button", { type: "button", onclick: () => invoke("sign_in_return") }, "Press Return"),
              el("button", { class: "quiet", type: "button", onclick: () => invoke("sign_in_cancel") }, "Stop"))
          : null,
      ].filter(Boolean));
    }
    if (view.phase === "running") return;
    stopPolling();
    if (view.phase === "stored") renderClaudeCode();
  };
  tick();
  polling = setInterval(tick, 700);
}

function stopPolling() {
  if (polling) clearInterval(polling);
  polling = null;
}

// The Claude API ---------------------------------------------------------------------

function secretField(secret, label, action) {
  const input = el("input", { type: "password", autocomplete: "off", spellcheck: "false", "aria-label": label });
  const keep = async () => {
    problem("");
    const value = input.value;
    input.value = "";
    try {
      await invoke("store_secret", { secret, value });
      await refresh();
      select(chosen);
    } catch (e) {
      problem(String(e));
    }
  };
  return el("label", {}, label, el("div", { class: "row" }, input, el("button", { type: "button", onclick: keep }, action)));
}

async function forget(secret) {
  await invoke("forget_secret", { secret });
  await refresh();
  select(chosen);
}

async function renderApi(engine) {
  await refresh();
  const box = el("div", { class: "box" });
  box.append(el("h2", {}, "Claude API"));
  if (state.kept.api_key) {
    const result = el("p", { id: "test-result" });
    box.append(
      el("p", { class: "ok" }, "A key is kept in the macOS Keychain. It is never shown."),
      el("div", { class: "row" },
        el("button", { type: "button", onclick: async () => {
          result.textContent = "Asking Anthropic…";
          result.textContent = await invoke("test_api_key").catch((e) => String(e));
        } }, "Test Key — contacts Anthropic"),
        el("button", { class: "quiet", type: "button", onclick: () => forget("api_key") }, "Remove the Key")),
      result,
      el("p", {}, "To start a run from Terminal, load it first with this line. It holds no secret:"),
      el("pre", { class: "copy" }, state.handover.api_key),
    );
  } else {
    box.append(
      el("p", {}, "Paste an Anthropic API key. It goes straight into the macOS Keychain; nothing is sent anywhere."),
      secretField("api_key", "API key", "Keep Key"),
    );
  }
  const options = (selected) => engine.models.map((m) => el("option", { value: m.id, selected: m.id === selected }, m.label));
  const implementer = el("select", { id: "implementer" }, options(state.implementer || engine.defaults.implementer));
  const reviewer = el("select", { id: "reviewer" }, options(state.reviewer || engine.defaults.reviewer));
  const pairNote = el("p", { id: "pair-note" });
  const check = () => {
    const same = implementer.value === reviewer.value;
    pairNote.className = same ? "warn" : "";
    pairNote.textContent = same
      ? "The reviewer must run on a different model from the implementer."
      : "Stored only: a run's own parameters still name its models.";
    canContinue(state.kept.api_key && !same);
  };
  implementer.onchange = check;
  reviewer.onchange = check;
  box.append(
    el("div", { class: "pair" },
      el("label", {}, "Implementing model", implementer),
      el("label", {}, "Reviewing model", reviewer)),
    pairNote,
    el("p", {}, "Runs on an API key still ask the owner before they spend."),
  );
  $("panel").replaceChildren(box);
  check();
}

// Not yet ----------------------------------------------------------------------------

async function renderNotYet(engine) {
  canContinue(false);
  const box = el("div", { class: "box" },
    el("h2", {}, `${engine.name}: not available yet`),
    el("p", {}, `${engine.detail} physgate's runs can't use it yet. A later change can switch it on; until then, runs use Claude Code.`));
  if (engine.id === "local") {
    const device = await invoke("device_report");
    const gb = (n) => `${n.toFixed(1)} GB`;
    box.append(
      el("h2", {}, "This Mac"),
      el("table", {},
        el("tbody", {},
          el("tr", {}, el("th", {}, "Chip"), el("td", {}, device.chip)),
          el("tr", {}, el("th", {}, "Memory"), el("td", { class: "num" }, gb(device.memory_gb))),
          el("tr", {}, el("th", {}, "GPU cores"), el("td", { class: "num" }, device.gpu_cores ?? "unknown")),
          el("tr", {}, el("th", {}, "Neural Engine"), el("td", {}, device.apple_silicon ? "Yes (Apple silicon)" : "No")),
          el("tr", {}, el("th", {}, "Free disk"), el("td", { class: "num" }, gb(device.free_disk_gb))))),
      el("h2", {}, "What it could run"),
      el("table", {},
        el("thead", {}, el("tr", {}, el("th", {}, "Model"), el("th", {}, "Memory"), el("th", {}, "Download"), el("th", {}, "Licence"), el("th", {}, "On this Mac"))),
        el("tbody", {}, device.models.map((m) =>
          el("tr", {},
            el("td", {}, m.name),
            el("td", { class: "num" }, `${m.memory_gb} GB`),
            el("td", { class: "num" }, `${m.disk_gb} GB`),
            el("td", {}, m.licence),
            el("td", { class: m.fits ? "ok" : "" }, m.fits ? "Would fit" : "Too large"))))),
      el("p", {}, "Nothing is downloaded. When local models are switched on, a model comes only from its official source, after you have seen its size and licence and clicked."),
    );
  }
  $("panel").replaceChildren(box);
}

// Finish -----------------------------------------------------------------------------

async function continueWith() {
  problem("");
  const args = { engine: chosen, implementer: null, reviewer: null };
  if (chosen === "claude-api") {
    args.implementer = $("implementer").value;
    args.reviewer = $("reviewer").value;
  }
  try {
    await invoke("choose_engine", args);
    await finish();
  } catch (e) {
    problem(String(e));
  }
}

async function finish() {
  stopPolling();
  await invoke("finish_onboarding").catch(problem);
}

// ---- Start --------------------------------------------------------------------------

(async () => {
  await refresh();
  const step = location.hash.slice(1);
  if (step === "intro" || (!step && !state.intro_seen)) showIntro();
  else showEngine();
})();
