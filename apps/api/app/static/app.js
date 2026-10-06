/* ShipForge dashboard — vanilla JS, no dependencies */
"use strict";

const API = "/api/v1";
const PAGE_SIZE = 20;

const state = {
  token: sessionStorage.getItem("sf_token") || "",
  role: sessionStorage.getItem("sf_role") || "",
  username: sessionStorage.getItem("sf_user") || "",
  shipments: [],
  selectedId: null,
  offset: 0,
  total: 0,
  timer: null,
};

/* ---------- helpers ---------- */

const $ = (id) => document.getElementById(id);

function authHeaders(extra = {}) {
  return { Authorization: `Bearer ${state.token}`, ...extra };
}

function toast(message, isError = false) {
  const el = $("toast");
  el.textContent = message;
  el.className = "toast" + (isError ? " err" : "");
  el.hidden = false;
  clearTimeout(el._t);
  el._t = setTimeout(() => (el.hidden = true), 4000);
}

async function api(path, options = {}) {
  const res = await fetch(API + path, {
    ...options,
    headers: authHeaders(options.headers || {}),
  });
  if (res.status === 401) {
    logout();
    throw new Error("Session expired — please sign in again");
  }
  const isJson = (res.headers.get("content-type") || "").includes("json");
  const body = isJson ? await res.json() : await res.text();
  if (!res.ok) {
    const msg = body && body.error ? `${body.error.code}: ${body.error.message}` : `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return body;
}

function fmtTime(iso) {
  return iso ? new Date(iso).toLocaleString() : "—";
}

function statusBadge(status) {
  return `<span class="badge ${status}">${status}</span>`;
}

function can(action) {
  const perms = {
    developer: ["read", "create"],
    release_manager: ["read", "create", "retry", "publish"],
    admin: ["read", "create", "retry", "publish"],
  };
  return (perms[state.role] || []).includes(action);
}

/* ---------- auth ---------- */

async function login(username, password) {
  const res = await fetch(API + "/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error ? body.error.message : "Login failed");
  }
  const data = await res.json();
  state.token = data.access_token;
  sessionStorage.setItem("sf_token", state.token);
  const me = await api("/auth/me");
  state.role = me.role;
  state.username = me.username;
  sessionStorage.setItem("sf_role", me.role);
  sessionStorage.setItem("sf_user", me.username);
  showApp();
}

function logout() {
  state.token = "";
  sessionStorage.removeItem("sf_token");
  sessionStorage.removeItem("sf_role");
  sessionStorage.removeItem("sf_user");
  stopAutoRefresh();
  $("app-view").hidden = true;
  $("login-view").hidden = false;
}

function showApp() {
  $("login-view").hidden = true;
  $("app-view").hidden = false;
  $("whoami").textContent = `${state.username} · ${state.role}`;
  // Role-aware buttons
  $("retry-btn").hidden = !can("retry");
  $("publish-btn").hidden = !can("publish");
  loadShipments();
  startAutoRefresh();
}

/* ---------- shipments list ---------- */

async function loadShipments() {
  const product = $("filter-product").value.trim();
  const status = $("filter-status").value;
  const params = new URLSearchParams({ limit: PAGE_SIZE, offset: state.offset });
  if (product) params.set("product", product);
  if (status) params.set("status", status);
  try {
    const data = await api(`/shipments?${params}`);
    state.shipments = data.items;
    state.total = data.total;
    renderList();
  } catch (err) {
    toast(err.message, true);
  }
}

function renderList() {
  const tbody = $("shipments-table").querySelector("tbody");
  tbody.innerHTML = state.shipments.length
    ? state.shipments
        .map(
          (s) => `
        <tr data-id="${s.id}" class="${s.id === state.selectedId ? "selected" : ""}">
          <td>${s.product}</td>
          <td>${s.version}</td>
          <td>${statusBadge(s.status)}</td>
          <td class="muted small">${fmtTime(s.created_at)}</td>
        </tr>`
        )
        .join("")
    : `<tr><td colspan="4" class="muted">No shipments found</td></tr>`;

  tbody.querySelectorAll("tr[data-id]").forEach((row) => {
    row.addEventListener("click", () => selectShipment(row.dataset.id));
  });

  const from = state.total === 0 ? 0 : state.offset + 1;
  const to = Math.min(state.offset + PAGE_SIZE, state.total);
  $("page-info").textContent = `${from}–${to} of ${state.total}`;
  $("page-prev").disabled = state.offset === 0;
  $("page-next").disabled = state.offset + PAGE_SIZE >= state.total;
}

/* ---------- detail ---------- */

async function selectShipment(id) {
  state.selectedId = id;
  renderList();
  $("detail-empty").hidden = true;
  $("detail-body").hidden = false;
  $("analysis-box").hidden = true;
  $("detail-error").hidden = true;
  await Promise.all([loadDetail(), loadEvents(), loadLogs()]);
}

async function loadDetail() {
  try {
    const s = await api(`/shipments/${state.selectedId}`);
    const el = $("detail-status");
    el.textContent = s.status;
    el.className = `badge ${s.status}`;

    const rows = [
      ["Product", s.product],
      ["Version", s.version],
      ["ID", s.id],
      ["Artifact", s.artifact_name || "—"],
      ["Created", fmtTime(s.created_at)],
      ["Updated", fmtTime(s.updated_at)],
      ["Published", fmtTime(s.published_at)],
    ];
    if (s.error_code) {
      rows.push(["Error code", s.error_code]);
      rows.push(["Error message", s.error_message || "—"]);
    }
    $("detail-meta").innerHTML = rows
      .map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`)
      .join("");

    const dl = $("download-link");
    if (s.artifact_name) {
      dl.hidden = false;
      dl.href = "#";
      dl.onclick = async (e) => {
        e.preventDefault();
        try {
          const res = await fetch(`${API}/shipments/${s.id}/artifact`, { headers: authHeaders() });
          if (!res.ok) throw new Error("Download failed");
          const blob = await res.blob();
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = s.artifact_name;
          a.click();
          URL.revokeObjectURL(url);
        } catch (err) {
          toast(err.message, true);
        }
      };
    } else {
      dl.hidden = true;
    }

    $("publish-btn").disabled = s.status !== "READY" && s.status !== "PUBLISHED";
    $("retry-btn").disabled = s.status !== "FAILED";
  } catch (err) {
    toast(err.message, true);
  }
}

async function loadEvents() {
  try {
    const events = await api(`/shipments/${state.selectedId}/events`);
    $("events-list").innerHTML = events.length
      ? events
          .map((e) => {
            const cls = e.event_type === "PUBLISHED" ? "published" : e.event_type === "PIPELINE_FAILED" ? "failed" : "";
            return `<li class="${cls}">
              <span class="ev-type">${e.event_type}</span>
              <span class="ev-time">${fmtTime(e.created_at)}</span>
              <span class="ev-msg">${e.message || ""}</span>
            </li>`;
          })
          .join("")
      : `<li class="muted">No events</li>`;
  } catch (err) {
    toast(err.message, true);
  }
}

async function loadLogs() {
  try {
    const data = await api(`/shipments/${state.selectedId}/logs`);
    const tbody = $("logs-table").querySelector("tbody");
    tbody.innerHTML = data.items.length
      ? data.items
          .map(
            (l) => `<tr>
              <td class="muted small">${fmtTime(l.created_at)}</td>
              <td>${l.level}</td>
              <td>${l.stage || "—"}</td>
              <td>${l.message}</td>
            </tr>`
          )
          .join("")
      : `<tr><td colspan="4" class="muted">No logs</td></tr>`;
  } catch (err) {
    toast(err.message, true);
  }
}

/* ---------- actions ---------- */

async function createShipment(product, version) {
  await api("/shipments", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ product, version }),
  });
  toast("Shipment created");
  await loadShipments();
}

async function uploadArtifact(file) {
  const form = new FormData();
  form.append("file", file);
  await api(`/shipments/${state.selectedId}/artifact`, { method: "POST", body: form });
  toast("Artifact uploaded — pipeline queued");
  await Promise.all([loadDetail(), loadEvents(), loadLogs()]);
}

async function retryShipment() {
  await api(`/shipments/${state.selectedId}/retry`, { method: "POST" });
  toast("Retry queued");
  await Promise.all([loadDetail(), loadEvents(), loadLogs()]);
}

async function publishShipment() {
  await api(`/shipments/${state.selectedId}/publish`, { method: "POST" });
  toast("Shipment published");
  await Promise.all([loadDetail(), loadEvents(), loadLogs()]);
}

async function analyzeShipment() {
  const box = $("analysis-box");
  box.hidden = false;
  box.innerHTML = `<h4>Analyzing…</h4><p class="conf">advisory only</p>`;
  try {
    const data = await api(`/shipments/${state.selectedId}/analyze`, { method: "POST" });
    const a = data.analysis;
    box.innerHTML = `
      <h4>AI analysis (${data.source}${data.advisory ? " · advisory only" : ""})</h4>
      <p><strong>${a.category}</strong> · severity ${a.severity}</p>
      <p>${a.root_cause}</p>
      <p class="conf">confidence ${(a.confidence * 100).toFixed(0)}%</p>
      <ul>${a.recommendations.map((r) => `<li>${r}</li>`).join("")}</ul>`;
  } catch (err) {
    box.innerHTML = `<p class="error">${err.message}</p>`;
  }
}

/* ---------- auto-refresh ---------- */

function startAutoRefresh() {
  stopAutoRefresh();
  state.timer = setInterval(() => {
    if ($("autorefresh").checked && !document.hidden) {
      loadShipments();
      if (state.selectedId) {
        loadDetail();
        loadEvents();
        loadLogs();
      }
    }
  }, 5000);
}

function stopAutoRefresh() {
  if (state.timer) clearInterval(state.timer);
  state.timer = null;
}

/* ---------- wiring ---------- */

$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errEl = $("login-error");
  errEl.hidden = true;
  try {
    await login($("login-username").value.trim(), $("login-password").value);
  } catch (err) {
    errEl.textContent = err.message;
    errEl.hidden = false;
  }
});

$("logout-btn").addEventListener("click", logout);
$("refresh-btn").addEventListener("click", loadShipments);
$("page-prev").addEventListener("click", () => {
  state.offset = Math.max(0, state.offset - PAGE_SIZE);
  loadShipments();
});
$("page-next").addEventListener("click", () => {
  state.offset += PAGE_SIZE;
  loadShipments();
});
$("filter-product").addEventListener("input", () => {
  state.offset = 0;
  loadShipments();
});
$("filter-status").addEventListener("change", () => {
  state.offset = 0;
  loadShipments();
});

$("create-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await createShipment($("create-product").value.trim(), $("create-version").value.trim());
    $("create-product").value = "";
    $("create-version").value = "";
  } catch (err) {
    toast(err.message, true);
  }
});

$("upload-file").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file || !state.selectedId) return;
  try {
    await uploadArtifact(file);
  } catch (err) {
    toast(err.message, true);
  }
});

$("retry-btn").addEventListener("click", async () => {
  try {
    await retryShipment();
  } catch (err) {
    toast(err.message, true);
  }
});

$("publish-btn").addEventListener("click", async () => {
  try {
    await publishShipment();
  } catch (err) {
    toast(err.message, true);
  }
});

$("analyze-btn").addEventListener("click", analyzeShipment);

/* Boot: restore session or show login */
if (state.token) {
  api("/auth/me")
    .then((me) => {
      state.role = me.role;
      state.username = me.username;
      showApp();
    })
    .catch(() => logout());
}
