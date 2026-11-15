// The welcome and the engine step. Everything shown is set as text, never as markup.
// Credentials go one way: from a field into the app (which keeps them in the Keychain). The
// state this page reads says only whether one is kept, never what it is.
//
// Each write (choosing the engine, keeping or forgetting a credential, setting the operator)
// asks first: its button opens a confirmation that names what is written, never a credential's
// value, and the write happens only on confirming, with the same calls it always made.
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

/** A button as the operator UI draws one: `browse`, `act` (a write, which asks first) or `ghost`. */
function button(kind, onclick, label) {
  return el("button", { class: `pg-btn pg-btn-${kind}`, type: "button", onclick }, label);
}

/** One of the operator UI's icons, beside the text it marks. */
const icon = (name) => el("span", { class: `pg-icon icon-${name}`, "aria-hidden": "true" });

/** A number and its unit, as the operator UI's Quantity draws them. */
const quantity = (value, unit) =>
  el("span", { class: "pg-quantity" }, value, " ", el("span", { class: "pg-quantity-unit" }, unit));

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

// ---- Asking first -------------------------------------------------------------------------

/**
 * Open the confirmation for one write: what it is, one sentence, and exactly what it writes.
 * ``write`` runs only when the person confirms; cancelling, or Escape, does nothing at all.
 */
function askFirst(what, write) {
  const dialog = $("confirm");
  const opener = document.activeElement;
  let confirmed = false;
  $("confirm-title").textContent = what.title;
  $("confirm-summary").textContent = what.summary;
  $("confirm-writes").textContent = what.writes;
  $("confirm-ok").textContent = what.confirm;
  $("confirm-ok").onclick = () => {
    confirmed = true;
    dialog.close();
  };
  $("confirm-cancel").onclick = () => dialog.close();
  dialog.onclose = () => {
    if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
    if (confirmed) write();
  };
  dialog.showModal();
}

/** What each credential's confirmation says. Never the credential itself. */
const KEEP = {
  subscription_token: {
    title: "Keep the token for runs?",
    summary: "Keeps the token in the macOS Keychain. It is never shown again.",
    writes: "macOS Keychain: the token runs sign in with",
    confirm: "Keep token",
  },
  api_key: {
    title: "Keep the API key?",
    summary: "Keeps the key in the macOS Keychain. It is never shown again, and nothing is sent anywhere.",
    writes: "macOS Keychain: the Claude API key",
    confirm: "Keep key",
  },
};

const FORGET = {
  subscription_token: {
    title: "Remove the token?",
    summary: "Removes the token for runs from the macOS Keychain.",
    writes: "macOS Keychain: the token runs sign in with, removed",
    confirm: "Remove the token",
  },
  api_key: {
    title: "Remove the API key?",
    summary: "Removes the Claude API key from the macOS Keychain.",
    writes: "macOS Keychain: the Claude API key, removed",
    confirm: "Remove the key",
  },
};

// ---- Welcome -----------------------------------------------------------------------

/** The intro film's length, in milliseconds, so the page moves on when it ends. */
const INTRO_MS = 7000;

function showIntro() {
  $("setup").hidden = true;
  $("welcome").hidden = false;
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

/** The arrow keys move the choice through the engines, round from the last to the first. */
const ARROWS = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 };

function onArrow(event) {
  const step = ARROWS[event.key];
  if (!step) return;
  event.preventDefault();
  const cards = [...document.querySelectorAll("#cards .card")];
  const next = cards[(cards.indexOf(event.currentTarget) + step + cards.length) % cards.length];
  next.focus();
  select(next.dataset.id);
}

async function showEngine() {
  document.onkeydown = null;
  $("welcome").hidden = true;
  $("setup").hidden = false;
  $("engine-title").focus();
  await refresh();
  const engines = state.catalogue.engines;
  chosen = state.engine || "claude-code";
  const cards = $("cards");
  cards.replaceChildren(
    ...engines.map((engine) =>
      el("button", {
        class: engine.status === "available" ? "card" : "card not-yet",
        type: "button", role: "radio", "data-id": engine.id,
        "aria-checked": String(engine.id === chosen),
        tabindex: engine.id === chosen ? "0" : "-1",
        onclick: () => select(engine.id),
        onkeydown: onArrow,
      },
      el("span", { class: "dot", "aria-hidden": "true" }),
      el("span", { class: "text" },
        el("span", { class: "name" }, engine.name),
        el("span", { class: "detail" }, engine.detail)),
      engine.status === "available" ? null : el("span", { class: "pg-badge" }, "Not yet")),
    ),
  );
  $("later").onclick = finish;
  $("continue").onclick = () => askFirst(engineChoice(), continueWith);
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
    card.setAttribute("tabindex", card.dataset.id === id ? "0" : "-1");
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
        el("li", {}, "Open Terminal with the installer.",
          el("div", { class: "row" }, button("browse", install, "Open in Terminal"))),
        el("li", {}, "Wait until Terminal says it is done. It downloads Claude Code from Anthropic."),
        el("li", {}, "Come back here and check again.",
          el("div", { class: "row" }, button("browse", renderClaudeCode, "Check again")))),
    );
    canContinue(false);
    return $("panel").replaceChildren(box);
  }
  const own = claude.logged_in
    ? `Claude Code itself is signed in${claude.subscription ? ` (${claude.subscription} plan)` : ""}.`
    : "Claude Code itself is not signed in; that does not stop runs, which use their own token.";
  box.append(
    el("h2", {}, "Claude Code"),
    el("p", { class: "ok" }, icon("check"), `Installed: ${claude.version || "version unknown"}`),
    el("p", {}, "At ", el("span", { class: "path" }, `${claude.path}`), `. ${own}`),
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
      el("p", { class: "ok" }, icon("lock"), "A token is kept in the macOS Keychain. It is never shown."),
      el("div", { class: "row" },
        button("act", () => askFirst(FORGET.subscription_token, () => forget("subscription_token")), "Remove the token…")),
    );
    return section;
  }
  section.append(
    el("h2", {}, "Sign in for runs"),
    el("p", {}, "Runs need a long-lived token from your subscription. Signing in opens your browser. " +
      "The token goes straight into the macOS Keychain and is never shown here."),
    el("div", { class: "row" },
      el("button", { class: "pg-btn pg-btn-browse", type: "button", onclick: signIn }, icon("external"), "Sign in")),
    el("div", { id: "progress" }),
    el("details", {},
      el("summary", {}, "Sign in in Terminal instead"),
      el("div", { class: "box" },
        el("p", {}, "Terminal runs the sign-in and prints the token. Paste it here; it goes to the Keychain. " +
          "Then press Return in Terminal: that empties the clipboard and clears the window."),
        el("div", { class: "row" }, button("browse", () => invoke("sign_in_in_terminal").catch(problem), "Open in Terminal")),
        secretField("subscription_token", "Token from Terminal", "Keep token…"))),
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
              button("browse", () => invoke("sign_in_return"), "Press Return"),
              button("ghost", () => invoke("sign_in_cancel"), "Stop"))
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
  return el("label", {}, label,
    el("div", { class: "row" }, input, button("act", () => askFirst(KEEP[secret], keep), action)));
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
      el("p", { class: "ok" }, icon("lock"), "A key is kept in the macOS Keychain. It is never shown."),
      el("div", { class: "row" },
        button("browse", async () => {
          result.textContent = "Asking Anthropic…";
          result.textContent = await invoke("test_api_key").catch((e) => String(e));
        }, "Test key (contacts Anthropic)"),
        button("act", () => askFirst(FORGET.api_key, () => forget("api_key")), "Remove the key…")),
      result,
    );
  } else {
    box.append(
      el("p", {}, "Paste an Anthropic API key. It goes straight into the macOS Keychain; nothing is sent anywhere."),
      secretField("api_key", "API key", "Keep key…"),
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
    const gb = (n) => quantity(n.toFixed(1), "GB");
    box.append(
      el("h2", {}, "This Mac"),
      el("table", {},
        el("tbody", {},
          el("tr", {}, el("th", { scope: "row" }, "Chip"), el("td", {}, device.chip)),
          el("tr", {}, el("th", { scope: "row" }, "Memory"), el("td", { class: "num" }, gb(device.memory_gb))),
          el("tr", {}, el("th", { scope: "row" }, "GPU cores"),
            el("td", { class: "num" }, device.gpu_cores == null ? "unknown" : el("span", { class: "pg-quantity" }, device.gpu_cores))),
          el("tr", {}, el("th", { scope: "row" }, "Neural Engine"), el("td", {}, device.apple_silicon ? "Yes (Apple silicon)" : "No")),
          el("tr", {}, el("th", { scope: "row" }, "Free disk"), el("td", { class: "num" }, gb(device.free_disk_gb))))),
      el("h2", {}, "What it could run"),
      el("table", {},
        el("thead", {}, el("tr", {},
          el("th", { scope: "col" }, "Model"),
          el("th", { scope: "col", class: "num" }, "Memory"),
          el("th", { scope: "col", class: "num" }, "Download"),
          el("th", { scope: "col" }, "Licence"),
          el("th", { scope: "col" }, "On this Mac"))),
        el("tbody", {}, device.models.map((m) =>
          el("tr", {},
            el("td", {}, m.name),
            el("td", { class: "num" }, quantity(m.memory_gb, "GB")),
            el("td", { class: "num" }, quantity(m.disk_gb, "GB")),
            el("td", {}, m.licence),
            el("td", { class: m.fits ? "ok" : "" }, m.fits ? "Would fit" : "Too large"))))),
      el("p", {}, "Nothing is downloaded. When local models are switched on, a model comes only from its official source, after you have seen its size and licence and clicked."),
    );
  }
  $("panel").replaceChildren(box);
}

// Finish -----------------------------------------------------------------------------

/** What choosing the engine writes: the engine, and for the Claude API its two models. */
function engineChoice() {
  const engine = engineById(chosen);
  const label = (id) => (engine.models || []).find((m) => m.id === id)?.label || id;
  const writes = chosen === "claude-api"
    ? `Engine: ${engine.name}\nImplementing model: ${label($("implementer").value)}\nReviewing model: ${label($("reviewer").value)}`
    : `Engine: ${engine.name}`;
  return {
    title: "Keep this engine choice?",
    summary: "Stored in this app's own settings only: a run's own parameters still name its credential and models. Then the operator UI opens.",
    writes,
    confirm: "Continue to the operator UI",
  };
}

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

// ---- Operator name ------------------------------------------------------------------

// The sections' ids are never the step names in the URL: a fragment that names an element
// makes the browser move focus there once the page has loaded, and the heading would lose it.
async function showOperator() {
  $("welcome").hidden = true;
  $("setup").hidden = true;
  $("operator-page").hidden = false;
  $("operator-title").focus();
  const said = await invoke("operator_state");
  const input = $("operator-name");
  input.value = said.current || said.suggested || "";
  const failed = (e) => {
    const p = $("operator-problem");
    p.textContent = `That name can't be used: ${String(e)}.`;
    p.hidden = false;
  };
  $("operator-save").onclick = () =>
    askFirst(
      {
        title: "Decide as this name?",
        summary: "Approvals and rejections made in the app are recorded under this name.",
        writes: `Operator: ${input.value}`,
        confirm: "Decide as this name",
      },
      () => invoke("set_operator", { name: input.value }).catch(failed),
    );
  $("operator-skip").onclick = () =>
    askFirst(
      {
        title: "Stay read-only?",
        summary: "No name is recorded, so the app shows everything and decides nothing.",
        writes: "Operator: none, read-only",
        confirm: "Stay read-only",
      },
      () => invoke("set_operator", { name: null }).catch(failed),
    );
  input.onkeydown = (event) => {
    if (event.key === "Enter") $("operator-save").click();
  };
}

// ---- Start --------------------------------------------------------------------------

(async () => {
  await refresh();
  const step = location.hash.slice(1);
  if (step === "operator") showOperator();
  else if (step === "intro" || (!step && !state.intro_seen)) showIntro();
  else showEngine();
})();
