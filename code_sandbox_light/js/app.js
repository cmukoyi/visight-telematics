/**
 * App State & Router
 * Single-page application state management
 */

const App = (() => {
  // ── State ─────────────────────────────────────────────────
  const state = {
    currentView: "dashboard",
    selectedAsset: null,
    selectedCategory: "all",
    mapInstance: null,
    mapMarkers: [],
    historyMarkers: [],
    historyPolyline: null,
    historyAsset: null,
    sidebarOpen: true,
    searchQuery: "",
    demoMode: true,          // true = use DEMO data, false = call real API
    notifications: [...DEMO.alerts],
    assets: [...DEMO.assets],
    categories: [...DEMO.categories],
    subAccounts: [...DEMO.subAccounts],
    editingAsset: null,
    editingUser: null
  };

  // ── Helper: format time ───────────────────────────────────
  function fmtTime(str) {
    if (!str) return "—";
    const d = new Date(str.replace(" ", "T") + "Z");
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function fmtDateTime(str) {
    if (!str) return "—";
    const d = new Date(str.replace(" ", "T") + "Z");
    return d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }

  function statusBadge(status) {
    const map = {
      online:  ["status-online",  "Online"],
      idle:    ["status-idle",    "Idle"],
      offline: ["status-offline", "Offline"]
    };
    const [cls, label] = map[status] || ["status-offline", "Unknown"];
    return `<span class="status-dot ${cls}"></span><span>${label}</span>`;
  }

  function batteryIcon(pct) {
    const cls = pct <= 20 ? "battery-critical" : pct <= 50 ? "battery-low" : "battery-ok";
    const w = Math.round(pct / 100 * 22);
    return `<span class="battery-wrap ${cls}" title="${pct}%">
      <i class="fa-solid fa-battery-full"></i> <small>${pct}%</small>
    </span>`;
  }

  function categoryById(id) {
    return DEMO.categories.find(c => c.id === id) || { name: "Uncategorized", icon: "fa-tag", color: "#6B7280" };
  }

  // ── Router ─────────────────────────────────────────────────
  function navigate(view, params = {}) {
    state.currentView = view;
    document.querySelectorAll(".nav-item").forEach(el => el.classList.remove("active"));
    const navEl = document.querySelector(`.nav-item[data-view="${view}"]`);
    if (navEl) navEl.classList.add("active");

    document.querySelectorAll(".view").forEach(v => v.classList.remove("active-view"));
    const viewEl = document.getElementById(`view-${view}`);
    if (viewEl) viewEl.classList.add("active-view");

    // Run view-specific init
    switch (view) {
      case "dashboard": Dashboard.init(); break;
      case "assets":    AssetsView.init(); break;
      case "history":   HistoryView.init(params.imei, params.asset); break;
      case "accounts":  AccountsView.init(); break;
      case "asset-mgmt": AssetMgmt.init(); break;
    }

    // update page title
    const titles = {
      dashboard: "Live Map",
      assets: "Asset List",
      history: "Movement History",
      accounts: "User Accounts",
      "asset-mgmt": "Asset Management"
    };
    document.getElementById("page-title").textContent = titles[view] || view;
  }

  // ── Notification badge ────────────────────────────────────
  function updateBadge() {
    const unread = state.notifications.filter(n => !n.read).length;
    const badge = document.getElementById("notif-badge");
    if (badge) {
      badge.textContent = unread;
      badge.style.display = unread ? "flex" : "none";
    }
  }

  // ── Toast ─────────────────────────────────────────────────
  function toast(msg, type = "info") {
    const t = document.createElement("div");
    t.className = `toast toast-${type}`;
    t.innerHTML = `<i class="fa-solid ${type === "success" ? "fa-circle-check" : type === "error" ? "fa-circle-xmark" : "fa-circle-info"}"></i> ${msg}`;
    document.getElementById("toast-container").appendChild(t);
    setTimeout(() => t.classList.add("show"), 10);
    setTimeout(() => { t.classList.remove("show"); setTimeout(() => t.remove(), 300); }, 3000);
  }

  // ── Modal helpers ─────────────────────────────────────────
  function openModal(id) { document.getElementById(id).classList.add("modal-open"); }
  function closeModal(id) { document.getElementById(id).classList.remove("modal-open"); }

  // ── Expose ────────────────────────────────────────────────
  return { state, navigate, toast, openModal, closeModal, updateBadge,
           fmtTime, fmtDateTime, statusBadge, batteryIcon, categoryById };
})();

// ══════════════════════════════════════════════════════════════
// DASHBOARD (Live Map)
// ══════════════════════════════════════════════════════════════
const Dashboard = (() => {
  let map = null;
  let markers = {};

  function init() {
    renderSidebarList();
    initMap();
    updateStats();
  }

  function updateStats() {
    const assets = App.state.assets;
    document.getElementById("stat-total").textContent   = assets.length;
    document.getElementById("stat-online").textContent  = assets.filter(a => a.status === "online").length;
    document.getElementById("stat-idle").textContent    = assets.filter(a => a.status === "idle").length;
    document.getElementById("stat-offline").textContent = assets.filter(a => a.status === "offline").length;
  }

  function initMap() {
    if (!document.getElementById("map-container")) return;
    if (map) { map.invalidateSize(); placeMarkers(); return; }

    map = L.map("map-container", { zoomControl: true }).setView([25.774, -80.220], 12);
    App.state.mapInstance = map;

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "© OpenStreetMap contributors",
      maxZoom: 19
    }).addTo(map);

    placeMarkers();
  }

  function markerIcon(asset) {
    const cat = App.categoryById(asset.groupId);
    const color = asset.status === "online" ? "#10B981" : asset.status === "idle" ? "#F59E0B" : "#EF4444";
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="36" height="44" viewBox="0 0 36 44">
      <path d="M18 0C8.06 0 0 8.06 0 18c0 13.5 18 26 18 26S36 31.5 36 18C36 8.06 27.94 0 18 0z" fill="${color}"/>
      <circle cx="18" cy="18" r="11" fill="white" opacity="0.95"/>
      <text x="18" y="23" text-anchor="middle" font-size="13" font-family="sans-serif" fill="${color}">
        ${asset.status === "online" ? "●" : asset.status === "idle" ? "◐" : "○"}
      </text>
    </svg>`;
    return L.divIcon({
      html: `<div style="filter: drop-shadow(0 2px 4px rgba(0,0,0,.35))">${svg}</div>`,
      className: "",
      iconSize: [36, 44],
      iconAnchor: [18, 44],
      popupAnchor: [0, -44]
    });
  }

  function placeMarkers() {
    Object.values(markers).forEach(m => map.removeLayer(m));
    markers = {};

    App.state.assets.forEach(asset => {
      const m = L.marker([asset.lat, asset.lng], { icon: markerIcon(asset) }).addTo(map);
      m.bindPopup(`
        <div class="map-popup">
          <strong>${asset.deviceName}</strong><br>
          <small>${asset.rfidTag}</small><br>
          <div class="popup-status">${App.statusBadge(asset.status)}</div>
          <div>${asset.address}</div>
          <div style="margin-top:6px">
            <button class="btn-popup-hist" onclick="App.navigate('history',{imei:'${asset.imei}',asset:'${asset.imei}'})">
              <i class='fa-solid fa-route'></i> History
            </button>
          </div>
        </div>
      `, { maxWidth: 240 });
      m.on("click", () => selectAsset(asset.imei));
      markers[asset.imei] = m;
    });
  }

  function selectAsset(imei) {
    const asset = App.state.assets.find(a => a.imei === imei);
    if (!asset) return;
    App.state.selectedAsset = imei;

    // highlight sidebar row
    document.querySelectorAll(".asset-row").forEach(r => r.classList.remove("selected"));
    const row = document.querySelector(`.asset-row[data-imei="${imei}"]`);
    if (row) { row.classList.add("selected"); row.scrollIntoView({ block: "nearest" }); }

    // pan map
    if (map) map.flyTo([asset.lat, asset.lng], 15, { duration: 0.8 });
    markers[imei]?.openPopup();

    renderDetailPanel(asset);
  }

  function renderDetailPanel(asset) {
    const cat = App.categoryById(asset.groupId);
    const panel = document.getElementById("asset-detail-panel");
    if (!panel) return;
    panel.innerHTML = `
      <div class="detail-header">
        <div class="detail-icon" style="background:${cat.color}20;color:${cat.color}">
          <i class="fa-solid ${cat.icon}"></i>
        </div>
        <div>
          <h3>${asset.deviceName}</h3>
          <small>${asset.rfidTag} · ${cat.name}</small>
        </div>
        <button class="btn-icon close-detail" onclick="document.getElementById('asset-detail-panel').innerHTML=''">
          <i class="fa-solid fa-xmark"></i>
        </button>
      </div>
      <div class="detail-grid">
        <div class="detail-item"><label>Status</label><span>${App.statusBadge(asset.status)}</span></div>
        <div class="detail-item"><label>Battery</label>${App.batteryIcon(asset.battery)}</div>
        <div class="detail-item"><label>Speed</label><span>${asset.speed} km/h</span></div>
        <div class="detail-item"><label>Last Update</label><span>${App.fmtTime(asset.gpsTime)}</span></div>
        <div class="detail-item detail-full"><label>Address</label><span>${asset.address}</span></div>
        <div class="detail-item"><label>IMEI</label><span class="mono">${asset.imei}</span></div>
        <div class="detail-item"><label>Position Type</label><span>${asset.positionType === 5 ? "BEACON" : "GPS"}</span></div>
      </div>
      <div class="detail-actions">
        <button class="btn btn-primary btn-sm" onclick="App.navigate('history',{imei:'${asset.imei}',asset:'${asset.imei}'})">
          <i class="fa-solid fa-route"></i> View History
        </button>
        <button class="btn btn-ghost btn-sm" onclick="App.navigate('asset-mgmt')">
          <i class="fa-solid fa-pen"></i> Edit Asset
        </button>
      </div>
    `;
  }

  function renderSidebarList() {
    const cat   = App.state.selectedCategory;
    const query = App.state.searchQuery.toLowerCase();
    const list  = App.state.assets.filter(a => {
      const inCat   = cat === "all" || a.groupId === cat;
      const inQuery = !query || a.deviceName.toLowerCase().includes(query) || a.rfidTag.toLowerCase().includes(query);
      return inCat && inQuery;
    });

    const container = document.getElementById("map-asset-list");
    if (!container) return;
    container.innerHTML = list.map(a => {
      const cat = App.categoryById(a.groupId);
      return `
        <div class="asset-row" data-imei="${a.imei}" onclick="Dashboard._select('${a.imei}')">
          <div class="asset-row-icon" style="background:${cat.color}20;color:${cat.color}">
            <i class="fa-solid ${cat.icon}"></i>
          </div>
          <div class="asset-row-info">
            <span class="asset-row-name">${a.deviceName}</span>
            <span class="asset-row-tag">${a.rfidTag}</span>
          </div>
          <div class="asset-row-right">
            <span class="status-dot ${`status-${a.status}`}"></span>
            ${App.batteryIcon(a.battery)}
          </div>
        </div>`;
    }).join("") || `<div class="empty-list"><i class="fa-solid fa-magnifying-glass"></i><p>No assets found</p></div>`;
  }

  return { init, renderSidebarList, _select: selectAsset };
})();

// ══════════════════════════════════════════════════════════════
// ASSETS LIST VIEW
// ══════════════════════════════════════════════════════════════
const AssetsView = (() => {
  function init() {
    renderCategories();
    renderTable();
  }

  function renderCategories() {
    const wrap = document.getElementById("category-chips");
    if (!wrap) return;
    wrap.innerHTML = `<button class="chip ${App.state.selectedCategory === 'all' ? 'chip-active' : ''}" onclick="AssetsView._cat('all')">
        All <span class="chip-count">${App.state.assets.length}</span>
      </button>` +
      DEMO.categories.map(c => `
        <button class="chip ${App.state.selectedCategory === c.id ? 'chip-active' : ''}" onclick="AssetsView._cat('${c.id}')" style="--chip-color:${c.color}">
          <i class="fa-solid ${c.icon}"></i> ${c.name}
          <span class="chip-count">${c.count}</span>
        </button>`).join("");
  }

  function renderTable() {
    const cat   = App.state.selectedCategory;
    const query = (document.getElementById("assets-search")?.value || "").toLowerCase();
    const list  = App.state.assets.filter(a => {
      const inCat   = cat === "all" || a.groupId === cat;
      const inQuery = !query || a.deviceName.toLowerCase().includes(query) || a.rfidTag.toLowerCase().includes(query);
      return inCat && inQuery;
    });

    const tbody = document.getElementById("assets-tbody");
    if (!tbody) return;
    tbody.innerHTML = list.map(a => {
      const cat = App.categoryById(a.groupId);
      return `<tr>
        <td>
          <div class="table-asset-name">
            <div class="tbl-icon" style="background:${cat.color}20;color:${cat.color}"><i class="fa-solid ${cat.icon}"></i></div>
            <div>
              <strong>${a.deviceName}</strong>
              <small class="mono">${a.rfidTag}</small>
            </div>
          </div>
        </td>
        <td>${cat.name}</td>
        <td><div class="status-wrap">${App.statusBadge(a.status)}</div></td>
        <td>${App.batteryIcon(a.battery)}</td>
        <td class="addr-cell">${a.address}</td>
        <td>${App.fmtDateTime(a.gpsTime)}</td>
        <td>
          <div class="row-actions">
            <button class="btn-icon-sm" title="View on map" onclick="App.navigate('dashboard');setTimeout(()=>Dashboard._select('${a.imei}'),400)">
              <i class="fa-solid fa-map-pin"></i>
            </button>
            <button class="btn-icon-sm" title="History" onclick="App.navigate('history',{imei:'${a.imei}',asset:'${a.imei}'})">
              <i class="fa-solid fa-route"></i>
            </button>
            <button class="btn-icon-sm" title="Edit" onclick="AssetMgmt._editFromList('${a.imei}')">
              <i class="fa-solid fa-pen"></i>
            </button>
          </div>
        </td>
      </tr>`;
    }).join("") || `<tr><td colspan="7" class="table-empty">No assets match the filter.</td></tr>`;
  }

  return { init, renderTable, _cat(id) { App.state.selectedCategory = id; renderCategories(); renderTable(); } };
})();

// ══════════════════════════════════════════════════════════════
// HISTORY VIEW  — sequential markers 1-2-3-4-5-6
// ══════════════════════════════════════════════════════════════
const HistoryView = (() => {
  let map = null;
  let markers = [];
  let polyline = null;

  function init(imei, _assetParam) {
    // Populate asset selector
    const sel = document.getElementById("hist-asset-select");
    if (sel) {
      sel.innerHTML = App.state.assets.map(a => `<option value="${a.imei}">${a.deviceName} (${a.rfidTag})</option>`).join("");
      if (imei) sel.value = imei;
    }

    const resolvedImei = (sel && sel.value) ? sel.value : (imei || App.state.assets[0]?.imei);
    App.state.historyAsset = resolvedImei;

    renderHistoryMap(resolvedImei);
    renderTimeline(resolvedImei);
    updateHistoryHeader(resolvedImei);
  }

  function updateHistoryHeader(imei) {
    const asset = App.state.assets.find(a => a.imei === imei);
    if (!asset) return;
    const el = document.getElementById("hist-asset-name");
    if (el) el.textContent = `${asset.deviceName} — ${asset.rfidTag}`;
  }

  function renderHistoryMap(imei) {
    const points = DEMO.trackHistory[imei] || generateFakeHistory(imei);

    if (!map) {
      map = L.map("hist-map", { zoomControl: true });
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "© OpenStreetMap contributors", maxZoom: 19
      }).addTo(map);
    }

    // clear old
    markers.forEach(m => map.removeLayer(m));
    if (polyline) map.removeLayer(polyline);
    markers = [];
    polyline = null;

    if (!points.length) return;

    // Draw polyline path
    const latlngs = points.map(p => [p.lat, p.lng]);
    polyline = L.polyline(latlngs, {
      color: "#3B82F6",
      weight: 3,
      opacity: 0.7,
      dashArray: "8 4"
    }).addTo(map);

    // Draw numbered markers
    points.forEach((p, i) => {
      const isFirst = i === 0;
      const isLast  = i === points.length - 1;
      const color   = isFirst ? "#10B981" : isLast ? "#EF4444" : "#3B82F6";
      const icon = L.divIcon({
        html: `<div class="hist-marker" style="background:${color}">
          <span>${p.seq}</span>
        </div>`,
        className: "",
        iconSize: [32, 32],
        iconAnchor: [16, 16],
        popupAnchor: [0, -18]
      });

      const m = L.marker([p.lat, p.lng], { icon }).addTo(map);
      m.bindPopup(`
        <div class="hist-popup">
          <div class="hist-popup-seq" style="background:${color}">${p.seq}</div>
          <div>
            <strong>${p.event}</strong><br>
            <small>${p.address}</small><br>
            <small><i class='fa-regular fa-clock'></i> ${App.fmtDateTime(p.gpsTime)}</small><br>
            <small><i class='fa-solid fa-gauge'></i> ${p.speed} km/h — ${p.posType === 5 ? "BEACON" : "GPS"}</small>
          </div>
        </div>`, { maxWidth: 260 });
      m.on("click", () => highlightTimeline(p.seq));
      markers.push(m);
    });

    map.fitBounds(polyline.getBounds(), { padding: [40, 40] });
  }

  function renderTimeline(imei) {
    const points = DEMO.trackHistory[imei] || generateFakeHistory(imei);
    const container = document.getElementById("hist-timeline");
    if (!container) return;

    container.innerHTML = points.map((p, i) => {
      const isFirst = i === 0;
      const isLast  = i === points.length - 1;
      const color   = isFirst ? "#10B981" : isLast ? "#EF4444" : "#3B82F6";
      return `
        <div class="timeline-item" id="tl-${p.seq}" onclick="HistoryView._focus(${p.seq})">
          <div class="tl-left">
            <div class="tl-circle" style="border-color:${color};color:${color}">${p.seq}</div>
            ${i < points.length - 1 ? '<div class="tl-line"></div>' : ''}
          </div>
          <div class="tl-body">
            <div class="tl-event">${p.event}</div>
            <div class="tl-address">${p.address}</div>
            <div class="tl-meta">
              <span><i class="fa-regular fa-clock"></i> ${App.fmtDateTime(p.gpsTime)}</span>
              <span><i class="fa-solid fa-gauge"></i> ${p.speed} km/h</span>
              <span class="tl-type ${p.posType === 5 ? 'beacon' : 'gps'}">${p.posType === 5 ? 'BEACON' : 'GPS'}</span>
            </div>
          </div>
        </div>`;
    }).join("");
  }

  function highlightTimeline(seq) {
    document.querySelectorAll(".timeline-item").forEach(el => el.classList.remove("tl-active"));
    const el = document.getElementById(`tl-${seq}`);
    if (el) { el.classList.add("tl-active"); el.scrollIntoView({ behavior: "smooth", block: "nearest" }); }
  }

  function focusMarker(seq) {
    const imei  = App.state.historyAsset;
    const points = DEMO.trackHistory[imei] || [];
    const p = points.find(pt => pt.seq === seq);
    if (!p || !map) return;
    map.flyTo([p.lat, p.lng], 16, { duration: 0.6 });
    markers[seq - 1]?.openPopup();
    highlightTimeline(seq);
  }

  // Generate placeholder history if asset has no data
  function generateFakeHistory(imei) {
    const asset = App.state.assets.find(a => a.imei === imei);
    if (!asset) return [];
    const pts = [];
    for (let i = 0; i < 6; i++) {
      pts.push({
        seq: i + 1,
        lat: asset.lat + (Math.random() - 0.5) * 0.08,
        lng: asset.lng + (Math.random() - 0.5) * 0.08,
        gpsTime: `2025-04-20 ${String(8 + i * 2).padStart(2, "0")}:00:00`,
        speed: Math.floor(Math.random() * 60),
        posType: 5,
        address: "Position " + (i + 1),
        event: i === 0 ? "Departed" : i === 5 ? "Current Position" : "Waypoint " + i
      });
    }
    DEMO.trackHistory[imei] = pts;
    return pts;
  }

  return {
    init,
    _focus: focusMarker,
    _changeAsset(imei) {
      App.state.historyAsset = imei;
      updateHistoryHeader(imei);
      renderHistoryMap(imei);
      renderTimeline(imei);
    }
  };
})();

// ══════════════════════════════════════════════════════════════
// ACCOUNTS VIEW
// ══════════════════════════════════════════════════════════════
const AccountsView = (() => {
  function init() { renderTable(); }

  function renderTable() {
    const tbody = document.getElementById("accounts-tbody");
    if (!tbody) return;
    tbody.innerHTML = App.state.subAccounts.map(u => `
      <tr>
        <td>
          <div class="user-cell">
            <div class="avatar">${u.name.split(" ").map(n => n[0]).join("").slice(0,2)}</div>
            <div>
              <strong>${u.name}</strong>
              <small>${u.account}</small>
            </div>
          </div>
        </td>
        <td>${u.role}</td>
        <td><span class="type-badge type-${u.type}">${u.typeName}</span></td>
        <td>
          <span class="perm-badge" title="Permissions: ${u.permissions}">
            ${[..."Login","Cmd","Edit","View","Report","Config"].slice(0, u.permissions.length)
              .map((lbl, i) => `<span class="perm-bit ${u.permissions[i] === '1' ? 'perm-on' : 'perm-off'}" title="${lbl}"></span>`).join("")}
          </span>
        </td>
        <td>${u.devices}</td>
        <td>${u.createdAt}</td>
        <td>
          <span class="enabled-badge ${u.enabledFlag ? 'enabled' : 'disabled'}">
            ${u.enabledFlag ? "Active" : "Suspended"}
          </span>
        </td>
        <td>
          <div class="row-actions">
            <button class="btn-icon-sm" title="Edit" onclick="AccountsView._edit('${u.id}')"><i class="fa-solid fa-pen"></i></button>
            <button class="btn-icon-sm btn-danger-sm" title="Delete" onclick="AccountsView._del('${u.id}')"><i class="fa-solid fa-trash"></i></button>
          </div>
        </td>
      </tr>`).join("") || `<tr><td colspan="8" class="table-empty">No sub-accounts found.</td></tr>`;
  }

  function openAddModal() {
    App.state.editingUser = null;
    document.getElementById("user-modal-title").textContent = "Add User Account";
    document.getElementById("user-form").reset();
    App.openModal("user-modal");
  }

  function edit(id) {
    const u = App.state.subAccounts.find(x => x.id === id);
    if (!u) return;
    App.state.editingUser = id;
    document.getElementById("user-modal-title").textContent = "Edit User Account";
    document.getElementById("uf-name").value    = u.name;
    document.getElementById("uf-account").value = u.account;
    document.getElementById("uf-role").value    = u.role;
    document.getElementById("uf-type").value    = u.type;
    document.getElementById("uf-enabled").checked = !!u.enabledFlag;
    App.openModal("user-modal");
  }

  function del(id) {
    if (!confirm("Remove this user account?")) return;
    App.state.subAccounts = App.state.subAccounts.filter(u => u.id !== id);
    renderTable();
    App.toast("User removed", "success");
    // API: Accounts.remove(account, subAccount)
  }

  function save() {
    const name    = document.getElementById("uf-name").value.trim();
    const account = document.getElementById("uf-account").value.trim();
    const role    = document.getElementById("uf-role").value.trim();
    const type    = parseInt(document.getElementById("uf-type").value);
    const enabled = document.getElementById("uf-enabled").checked ? 1 : 0;

    if (!name || !account) { App.toast("Name and account are required", "error"); return; }

    if (App.state.editingUser) {
      const u = App.state.subAccounts.find(x => x.id === App.state.editingUser);
      if (u) { u.name = name; u.account = account; u.role = role; u.type = type; u.typeName = type === 8 ? "Distributor" : "User"; u.enabledFlag = enabled; }
      // API: Accounts.update({...})
      App.toast("User updated", "success");
    } else {
      App.state.subAccounts.push({
        id: "usr_" + Date.now(),
        account, name, role,
        type, typeName: type === 8 ? "Distributor" : "User",
        enabledFlag: enabled,
        createdAt: new Date().toISOString().slice(0, 10),
        permissions: "100000",
        devices: 0
      });
      // API: Accounts.create({...})
      App.toast("User created", "success");
    }
    App.closeModal("user-modal");
    renderTable();
  }

  return { init, renderTable, openAddModal, save, _edit: edit, _del: del };
})();

// ══════════════════════════════════════════════════════════════
// ASSET MANAGEMENT
// ══════════════════════════════════════════════════════════════
const AssetMgmt = (() => {
  function init() { renderCards(); }

  function renderCards() {
    const container = document.getElementById("assetmgmt-grid");
    if (!container) return;
    const query = (document.getElementById("assetmgmt-search")?.value || "").toLowerCase();
    const list  = App.state.assets.filter(a =>
      !query || a.deviceName.toLowerCase().includes(query) || a.rfidTag.toLowerCase().includes(query) || a.imei.includes(query)
    );

    container.innerHTML = list.map(a => {
      const cat = App.categoryById(a.groupId);
      return `
        <div class="asset-card">
          <div class="asset-card-header" style="border-top:3px solid ${cat.color}">
            <div class="asset-card-icon" style="background:${cat.color}20;color:${cat.color}">
              <i class="fa-solid ${cat.icon}"></i>
            </div>
            <div class="asset-card-title">
              <strong>${a.deviceName}</strong>
              <small>${cat.name}</small>
            </div>
            <div class="status-dot ${`status-${a.status}`}" style="margin-left:auto"></div>
          </div>
          <div class="asset-card-body">
            <div class="card-kv"><span>RFID Tag</span><span class="mono">${a.rfidTag}</span></div>
            <div class="card-kv"><span>IMEI</span><span class="mono small">${a.imei}</span></div>
            <div class="card-kv"><span>Model</span><span>${a.mcType}</span></div>
            <div class="card-kv"><span>Battery</span>${App.batteryIcon(a.battery)}</div>
            <div class="card-kv"><span>Last Seen</span><span>${App.fmtDateTime(a.gpsTime)}</span></div>
          </div>
          <div class="asset-card-footer">
            <button class="btn btn-ghost btn-sm" onclick="AssetMgmt._edit('${a.imei}')"><i class="fa-solid fa-pen"></i> Edit</button>
            <button class="btn btn-ghost btn-sm" onclick="App.navigate('history',{imei:'${a.imei}'})"><i class="fa-solid fa-route"></i> History</button>
            <button class="btn btn-danger-ghost btn-sm" onclick="AssetMgmt._del('${a.imei}')"><i class="fa-solid fa-trash"></i></button>
          </div>
        </div>`;
    }).join("") || `<div class="empty-list"><i class="fa-solid fa-box-open fa-2x"></i><p>No assets found.</p></div>`;
  }

  function openAddModal() {
    App.state.editingAsset = null;
    document.getElementById("asset-modal-title").textContent = "Add New Asset";
    document.getElementById("asset-form").reset();
    App.openModal("asset-modal");
  }

  function edit(imei) {
    const a = App.state.assets.find(x => x.imei === imei);
    if (!a) return;
    App.state.editingAsset = imei;
    document.getElementById("asset-modal-title").textContent = "Edit Asset";
    document.getElementById("af-name").value    = a.deviceName;
    document.getElementById("af-imei").value    = a.imei;
    document.getElementById("af-rfid").value    = a.rfidTag;
    document.getElementById("af-model").value   = a.mcType;
    document.getElementById("af-group").value   = a.groupId;
    App.openModal("asset-modal");
  }

  function editFromList(imei) {
    App.navigate("asset-mgmt");
    setTimeout(() => edit(imei), 100);
  }

  function del(imei) {
    if (!confirm("Remove this asset?")) return;
    App.state.assets = App.state.assets.filter(a => a.imei !== imei);
    renderCards();
    App.toast("Asset removed", "success");
  }

  function save() {
    const name  = document.getElementById("af-name").value.trim();
    const imei  = document.getElementById("af-imei").value.trim();
    const rfid  = document.getElementById("af-rfid").value.trim();
    const model = document.getElementById("af-model").value.trim();
    const group = document.getElementById("af-group").value;

    if (!name || !imei) { App.toast("Name and IMEI are required", "error"); return; }

    if (App.state.editingAsset) {
      const a = App.state.assets.find(x => x.imei === App.state.editingAsset);
      if (a) { a.deviceName = name; a.rfidTag = rfid; a.mcType = model; a.groupId = group; }
      App.toast("Asset updated", "success");
    } else {
      App.state.assets.push({
        imei, deviceName: name, mcType: model, groupId: group,
        status: "offline", battery: 0, rfidTag: rfid,
        lat: 25.77, lng: -80.20, speed: 0,
        gpsTime: new Date().toISOString().replace("T", " ").slice(0, 19),
        positionType: 5, address: "Unknown"
      });
      App.toast("Asset added", "success");
    }
    App.closeModal("asset-modal");
    renderCards();
  }

  return { init, renderCards, openAddModal, save, _edit: edit, _del: del, _editFromList: editFromList };
})();

// ══════════════════════════════════════════════════════════════
// BOOTSTRAP
// ══════════════════════════════════════════════════════════════
document.addEventListener("DOMContentLoaded", () => {
  App.updateBadge();
  App.navigate("dashboard");

  // Notification panel toggle
  document.getElementById("notif-btn")?.addEventListener("click", e => {
    e.stopPropagation();
    document.getElementById("notif-panel")?.classList.toggle("open");
  });
  document.addEventListener("click", () => {
    document.getElementById("notif-panel")?.classList.remove("open");
  });

  // Render notifications
  const nlist = document.getElementById("notif-list");
  if (nlist) {
    nlist.innerHTML = DEMO.alerts.map(a => `
      <div class="notif-item ${a.read ? "" : "notif-unread"}">
        <i class="fa-solid ${a.type === "low_battery" ? "fa-battery-low" : a.type === "offline" ? "fa-wifi-slash" : "fa-bell"} notif-icon"></i>
        <div>
          <strong>${a.asset}</strong><br>
          <small>${a.msg}</small>
        </div>
        <span class="notif-time">${a.time}</span>
      </div>`).join("");
  }

  // Sidebar toggle
  document.getElementById("sidebar-toggle")?.addEventListener("click", () => {
    document.getElementById("sidebar").classList.toggle("collapsed");
    document.getElementById("main-content").classList.toggle("sidebar-collapsed");
  });
});
