/*
  SmartCart Kiosk UI (Milestone 4)
  ---------------------------------
  This is entirely new -- nothing shopper-facing existed in the original
  repo (webapp/dashboard/index.html was an ADMIN tool, not this). Runs as
  a full-screen Chromium kiosk on the 7" touchscreen, talking to the
  FastAPI backend over plain fetch() calls (same-box, per the confirmed
  architecture: apiBaseUrl defaults to http://localhost:8000).

  Design choice worth calling out: this UI holds NO client-side session
  state across a reload (no localStorage/cookie tracking "am I logged
  in"). Instead, on every load it asks the backend "is there currently an
  active session for my cart_id?" via the same /sessions/active endpoint
  the ESP32 firmware and the Pi detection module already poll. This means
  a Chromium crash/restart on the kiosk recovers gracefully back into the
  shopping screen without the shopper needing to re-enter their code --
  the backend, not the browser tab, is the single source of truth for
  "is a trip in progress," consistent with how every other device in this
  system already works.
*/

const CFG = window.SMARTCART_CONFIG;
const CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"; // must match backend's generate_shopper_token alphabet

const el = (id) => document.getElementById(id);

const screens = {
  login: el("screen-login"),
  shopping: el("screen-shopping"),
  checkout: el("screen-checkout"),
};

function showScreen(name) {
  Object.values(screens).forEach((s) => s.classList.remove("screen-active"));
  screens[name].classList.add("screen-active");
}

// ---------------------------------------------------------------------
// Backend calls
// ---------------------------------------------------------------------

async function apiFetch(path, options = {}) {
  const res = await fetch(`${CFG.apiBaseUrl}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  return res;
}

async function getActiveSession() {
  const res = await apiFetch(`/sessions/active?cart_id=${encodeURIComponent(CFG.cartId)}`);
  if (res.status === 200) return await res.json();
  return null; // 404 or any transient error -> treat as "no active session"
}

async function startSession(code) {
  return apiFetch("/sessions/start", {
    method: "POST",
    body: JSON.stringify({ token: code, cart_id: CFG.cartId }),
  });
}

async function getCartSummary(sessionId) {
  const res = await apiFetch(`/sessions/${sessionId}`);
  if (!res.ok) return null;
  return await res.json();
}

async function getRecommendations(sessionId) {
  const res = await apiFetch(`/recommendations/for-shopper/${sessionId}`);
  if (!res.ok) return null;
  return await res.json();
}

async function closeSession(sessionId) {
  const res = await apiFetch(`/sessions/${sessionId}/close`, { method: "POST" });
  if (!res.ok) return null;
  return await res.json();
}

// ---------------------------------------------------------------------
// Clock
// ---------------------------------------------------------------------

function tickClock() {
  const now = new Date();
  el("topbar-clock").textContent = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
setInterval(tickClock, 1000 * 30);
tickClock();
el("topbar-cart-id").textContent = CFG.cartId;

// ---------------------------------------------------------------------
// LOGIN SCREEN
// ---------------------------------------------------------------------

let enteredCode = "";

function buildKeyboard() {
  const keyboard = el("keyboard");
  keyboard.innerHTML = "";
  for (const ch of CODE_ALPHABET) {
    const key = document.createElement("button");
    key.className = "key";
    key.textContent = ch;
    key.addEventListener("click", () => onKeyPress(ch));
    keyboard.appendChild(key);
  }
}

function onKeyPress(ch) {
  if (enteredCode.length >= 8) return;
  enteredCode += ch;
  renderCodeDisplay();
  if (enteredCode.length === 8) {
    attemptLogin();
  }
}

function renderCodeDisplay() {
  const slots = document.querySelectorAll("#code-display .code-slot");
  slots.forEach((slot, i) => {
    if (i < enteredCode.length) {
      slot.textContent = enteredCode[i];
      slot.classList.add("filled");
    } else {
      slot.textContent = "";
      slot.classList.remove("filled");
    }
  });
}

function clearCode() {
  enteredCode = "";
  renderCodeDisplay();
  el("login-error").textContent = "";
}

async function attemptLogin() {
  el("login-error").textContent = "";
  const res = await startSession(enteredCode);

  if (res.status === 201) {
    const session = await res.json();
    clearCode();
    enterShoppingScreen(session.id);
    return;
  }

  if (res.status === 401) {
    el("login-error").textContent = "That code wasn't recognized. Please try again.";
  } else if (res.status === 429) {
    el("login-error").textContent = "Too many attempts. Please wait a minute and try again.";
  } else {
    el("login-error").textContent = "Couldn't reach the cart system. Please try again.";
  }
  // Deliberately clear the code on ANY failure (not just success) --
  // leaving a wrong code on screen invites re-submitting the same wrong
  // code, which just burns the rate-limit budget faster.
  enteredCode = "";
  renderCodeDisplay();
}

el("btn-clear").addEventListener("click", clearCode);
el("btn-enter").addEventListener("click", () => {
  if (enteredCode.length === 8) attemptLogin();
});

// ---------------------------------------------------------------------
// SHOPPING SCREEN
// ---------------------------------------------------------------------

let activeSessionId = null;
let pollTimer = null;
let recsPollTimer = null;
let sessionStartedAt = null;
let lastRenderedTotal = null;

function enterShoppingScreen(sessionId, startedAt) {
  activeSessionId = sessionId;
  sessionStartedAt = startedAt ? new Date(startedAt) : new Date();
  showScreen("shopping");
  refreshCartSummary();
  refreshRecommendations();
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(refreshCartSummary, CFG.cartSummaryPollMs);
  if (recsPollTimer) clearInterval(recsPollTimer);
  // Recommendations change far less often than the cart itself within a
  // single trip, and the query is heavier (aggregates purchase history)
  // -- polled at a slower, separate cadence rather than piggybacking on
  // every 2s cart refresh.
  recsPollTimer = setInterval(refreshRecommendations, CFG.recommendationsPollMs || 8000);
}

function formatCurrency(amount) {
  return `₹${Number(amount).toFixed(2)}`;
}

async function refreshCartSummary() {
  if (activeSessionId == null) return;
  const summary = await getCartSummary(activeSessionId);
  if (summary === null) return; // transient failure -- try again next tick, don't disrupt the UI

  if (summary.status !== "active") {
    // Session was closed from elsewhere (e.g. an admin action) -- return
    // to login rather than continuing to poll a dead session.
    clearInterval(pollTimer);
    clearInterval(recsPollTimer);
    activeSessionId = null;
    showScreen("login");
    return;
  }

  renderReceipt(summary.items, "receipt-list", "receipt-empty");
  renderTotal(summary.items, summary.total);

  el("receipt-meta").textContent = `started ${sessionStartedAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;

  const btn = el("btn-checkout");
  btn.textContent = summary.items.length > 0 ? "Checkout" : "End trip";
}

const RECS_BASIS_LABEL = {
  your_past_purchases: "You usually buy",
  trending: "Popular right now",
  frequently_bought_together: "Goes well together",
};

async function refreshRecommendations() {
  if (activeSessionId == null) return;
  const rec = await getRecommendations(activeSessionId);
  const panel = el("recs-panel");

  if (rec === null || rec.basis === "not_enough_data" || rec.items.length === 0) {
    panel.style.display = "none";
    return;
  }

  panel.style.display = "block";
  el("recs-label").textContent = RECS_BASIS_LABEL[rec.basis] || "You might also like";

  const list = el("recs-list");
  list.innerHTML = "";
  for (const item of rec.items) {
    const row = document.createElement("div");
    row.className = "recs-item";
    row.innerHTML = `
      <span class="recs-item-name">${escapeHtml(item.name)}</span>
      <span class="recs-item-price">${formatCurrency(item.price)}</span>
    `;
    list.appendChild(row);
  }
}

function renderReceipt(items, listId, emptyId) {
  const list = el(listId);
  const empty = document.getElementById(emptyId);
  list.querySelectorAll(".receipt-row").forEach((n) => n.remove());
  if (empty) empty.style.display = items.length === 0 ? "block" : "none";

  for (const item of items) {
    const row = document.createElement("div");
    row.className = "receipt-row";
    const lineTotal = item.unit_price_snapshot * item.quantity;
    row.innerHTML = `
      <span class="receipt-row-name">${escapeHtml(item.product_name || "Item")}</span>
      <span class="receipt-row-qty">x${item.quantity}</span>
      <span class="receipt-row-fill"></span>
      <span class="receipt-row-price">${formatCurrency(lineTotal)}</span>
    `;
    if (!item.weight_verified) {
      const pending = document.createElement("span");
      pending.className = "receipt-row-pending";
      pending.textContent = "confirming weight…";
      row.appendChild(pending);
    }
    list.appendChild(row);
  }
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function renderTotal(items, total) {
  const amountEl = el("price-tag-amount");
  amountEl.textContent = formatCurrency(total);
  if (lastRenderedTotal !== null && total !== lastRenderedTotal) {
    amountEl.classList.add("bump");
    setTimeout(() => amountEl.classList.remove("bump"), 260);
  }
  lastRenderedTotal = total;

  const count = items.reduce((sum, i) => sum + i.quantity, 0);
  el("price-tag-count").textContent = `${count} item${count === 1 ? "" : "s"}`;
}

el("btn-checkout").addEventListener("click", async () => {
  if (activeSessionId == null) return;
  const receipt = await closeSession(activeSessionId);
  if (receipt === null) return; // transient failure, stay on shopping screen, let the shopper retry

  clearInterval(pollTimer);
  clearInterval(recsPollTimer);
  el("recs-panel").style.display = "none";
  showCheckoutScreen(receipt);
});

// ---------------------------------------------------------------------
// CHECKOUT SCREEN
// ---------------------------------------------------------------------

function showCheckoutScreen(receipt) {
  const rows = receipt.lines.map((line) => ({
    product_name: line.product_name,
    quantity: line.quantity,
    unit_price_snapshot: line.unit_price,
    weight_verified: true, // finalized receipt -- no pending state to show
  }));
  renderReceipt(rows, "final-receipt-list", null);
  el("final-receipt-total").textContent = formatCurrency(receipt.total);
  el("checkout-eyebrow").textContent = receipt.lines.length > 0 ? "All set" : "See you soon";
  activeSessionId = null;
  showScreen("checkout");
}

el("btn-new-shopper").addEventListener("click", () => {
  showScreen("login");
});

// ---------------------------------------------------------------------
// Boot: recover an in-progress session if one exists, otherwise login
// ---------------------------------------------------------------------

async function boot() {
  buildKeyboard();
  renderCodeDisplay();

  const active = await getActiveSession();
  if (active) {
    enterShoppingScreen(active.id, active.started_at);
  } else {
    showScreen("login");
  }
}

boot();
