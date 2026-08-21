let allData = {};
let currentTab = "Blended";
let currentPayoutsTab = "Blended";
let currentMetaTab = "Blended";
let currentMonth = new Date().getMonth();
let currentYear = new Date().getFullYear();
let currentView = "calendar";
let ebitdaPreset = "This month";
let ebitdaCustomRange = null; // {start, end} - only used when preset is "Custom"
let metaPreset = "Last 30 days";
let metaCustomRange = null;

const VIEW_LABELS = { calendar: "Calendar", ebitda: "EBITDA", annual: "Annual", payouts: "Payouts", metaads: "Meta Ads" };

const DATE_PRESETS = ["Yesterday", "Last 7 days", "Last 14 days", "Last 30 days", "This month", "Last month", "Maximum"];

function todayStr() {
  return new Date().toISOString().slice(0, 10);
}

function daysAgoStr(n) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

/** Resolves a preset name into a concrete {start, end} range. `allRowsForMax` is
 * the full row list for the current tab, used only by "Maximum" to find the
 * earliest date actually present in the data. */
function resolvePreset(presetName, allRowsForMax) {
  const today = new Date();
  const y = today.getFullYear();
  const m = today.getMonth();

  switch (presetName) {
    case "Yesterday": {
      const d = daysAgoStr(1);
      return { start: d, end: d };
    }
    case "Last 7 days":
      return { start: daysAgoStr(7), end: todayStr() };
    case "Last 14 days":
      return { start: daysAgoStr(14), end: todayStr() };
    case "Last 30 days":
      return { start: daysAgoStr(30), end: todayStr() };
    case "This month": {
      const start = new Date(y, m, 1).toISOString().slice(0, 10);
      return { start, end: todayStr() };
    }
    case "Last month": {
      const start = new Date(y, m - 1, 1).toISOString().slice(0, 10);
      const end = new Date(y, m, 0).toISOString().slice(0, 10);
      return { start, end };
    }
    case "Maximum": {
      if (!allRowsForMax || allRowsForMax.length === 0) return { start: todayStr(), end: todayStr() };
      const dates = allRowsForMax.map(r => r.Date).filter(Boolean).sort();
      return { start: dates[0], end: dates[dates.length - 1] };
    }
    default:
      return { start: daysAgoStr(30), end: todayStr() };
  }
}

// ---- Theme ----
function initTheme() {
  const saved = localStorage.getItem("pnl-theme");
  const theme = saved || "dark";
  document.documentElement.setAttribute("data-theme", theme);
  updateThemeToggleIcon(theme);
}

function updateThemeToggleIcon(theme) {
  document.getElementById("themeToggle").textContent = theme === "dark" ? "\u2600" : "\u263D";
}

document.getElementById("themeToggle").onclick = () => {
  const current = document.documentElement.getAttribute("data-theme");
  const next = current === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  try { localStorage.setItem("pnl-theme", next); } catch (e) {}
  updateThemeToggleIcon(next);
};

// ---- Slide-out nav ----
const navToggle = document.getElementById("navToggle");
const navScrim = document.getElementById("navScrim");

function closeNav() { document.body.classList.remove("nav-open"); }
function toggleNav() { document.body.classList.toggle("nav-open"); }

navToggle.onclick = toggleNav;
navScrim.onclick = closeNav;

document.querySelectorAll(".nav-item").forEach(btn => {
  btn.onclick = () => {
    currentView = btn.dataset.view;
    document.querySelectorAll(".nav-item").forEach(b => b.classList.toggle("active", b === btn));
    document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
    document.getElementById("view-" + currentView).classList.add("active");
    document.getElementById("currentViewLabel").textContent = VIEW_LABELS[currentView];
    closeNav();
    render();
  };
});

// ---- Formatting ----
function formatMoney(n) {
  const sign = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  if (abs >= 1000) return sign + "$" + (abs / 1000).toFixed(2) + "K";
  return sign + "$" + abs.toFixed(2);
}

function formatMoneyFull(n) {
  const sign = n < 0 ? "-" : "";
  return sign + "$" + Math.abs(n).toFixed(2);
}

function formatNumber(n) {
  if (n === null || n === undefined || n === "") return "—";
  if (Math.abs(n) >= 1000) return (n / 1000).toFixed(1) + "K";
  return Number.isInteger(n) ? String(n) : n.toFixed(2);
}

// ---- Brand dropdown (shared component) ----
function getPnlBrandNames() {
  const names = Object.keys(allData).filter(k => k !== "Payouts");
  names.sort((a, b) => (a === "Blended" ? -1 : b === "Blended" ? 1 : 0));
  return names;
}

function getPayoutsBrandNames() {
  const payoutsData = allData["Payouts"] || {};
  const names = Object.keys(payoutsData);
  names.sort((a, b) => (a === "Blended" ? -1 : b === "Blended" ? 1 : 0));
  return names;
}

function buildBrandPicker(viewKey, names, currentValue, onSelect) {
  const pickerEl = document.getElementById("brandPicker-" + viewKey);
  const buttonEl = pickerEl.querySelector(".brand-picker-button");
  const labelEl = buttonEl.querySelector("[data-label]");
  const menuEl = document.getElementById("brandMenu-" + viewKey);

  labelEl.textContent = currentValue;
  menuEl.innerHTML = "";

  names.forEach(name => {
    const item = document.createElement("button");
    item.className = "brand-picker-item" + (name === currentValue ? " active" : "");
    item.textContent = name;
    item.onclick = () => {
      onSelect(name);
      pickerEl.classList.remove("open");
      updateBrandPickerScrim();
    };
    menuEl.appendChild(item);
  });

  buttonEl.onclick = (e) => {
    e.stopPropagation();
    const wasOpen = pickerEl.classList.contains("open");
    document.querySelectorAll(".brand-picker").forEach(p => p.classList.remove("open"));
    if (!wasOpen) pickerEl.classList.add("open");
    updateBrandPickerScrim();
  };
}

function updateBrandPickerScrim() {
  const anyOpen = document.querySelector(".brand-picker.open") !== null;
  document.getElementById("brandPickerScrim").classList.toggle("active", anyOpen);
}

document.getElementById("brandPickerScrim").onclick = () => {
  document.querySelectorAll(".brand-picker").forEach(p => p.classList.remove("open"));
  updateBrandPickerScrim();
};

document.addEventListener("click", () => {
  document.querySelectorAll(".brand-picker").forEach(p => p.classList.remove("open"));
  updateBrandPickerScrim();
});

// ---- Single-window calendar range picker (click a start day, then an end day) ----
// Tracks its own per-instance nav month and in-progress selection state, keyed by
// instanceKey ("ebitda" or "meta") so the two pickers don't interfere with each other.
const rangePickerState = {};

function updateRangePickerScrim() {
  const anyOpen = document.querySelector(".range-picker.open") !== null;
  document.getElementById("rangePickerScrim").classList.toggle("active", anyOpen);
}

document.getElementById("rangePickerScrim").onclick = () => {
  document.querySelectorAll(".range-picker").forEach(p => p.classList.remove("open"));
  updateRangePickerScrim();
};

document.addEventListener("click", () => {
  document.querySelectorAll(".range-picker").forEach(p => p.classList.remove("open"));
  updateRangePickerScrim();
});

function buildRangePicker(instanceKey, currentPreset, currentRange, onApply) {
  const pickerEl = document.getElementById("rangePicker-" + instanceKey);
  const buttonEl = pickerEl.querySelector(".range-picker-button");
  const labelEl = buttonEl.querySelector("[data-label]");
  const popoverEl = document.getElementById("rangePopover-" + instanceKey);

  if (!rangePickerState[instanceKey]) {
    const base = currentRange || resolvePreset(currentPreset);
    rangePickerState[instanceKey] = {
      navMonth: new Date(base.end + "T00:00:00").getMonth(),
      navYear: new Date(base.end + "T00:00:00").getFullYear(),
      pendingStart: null,
    };
  }
  const state = rangePickerState[instanceKey];

  labelEl.textContent = currentPreset === "Custom" && currentRange
    ? `${currentRange.start} to ${currentRange.end}`
    : currentPreset;

  buttonEl.onclick = (e) => {
    e.stopPropagation();
    const wasOpen = pickerEl.classList.contains("open");
    document.querySelectorAll(".range-picker").forEach(p => p.classList.remove("open"));
    if (!wasOpen) pickerEl.classList.add("open");
    updateRangePickerScrim();
    if (!wasOpen) renderRangePickerPopover(instanceKey, currentRange, onApply);
  };

  popoverEl.onclick = (e) => e.stopPropagation();

  if (pickerEl.classList.contains("open")) {
    renderRangePickerPopover(instanceKey, currentRange, onApply);
  }
}

function renderRangePickerPopover(instanceKey, currentRange, onApply) {
  const popoverEl = document.getElementById("rangePopover-" + instanceKey);
  const state = rangePickerState[instanceKey];

  const monthLabel = new Date(state.navYear, state.navMonth, 1).toLocaleDateString("en-US", { month: "long", year: "numeric" });
  const firstDay = new Date(state.navYear, state.navMonth, 1).getDay();
  const daysInMonth = new Date(state.navYear, state.navMonth + 1, 0).getDate();

  const selStart = state.pendingStart || (currentRange ? currentRange.start : null);
  const selEnd = (!state.pendingStart && currentRange) ? currentRange.end : null;

  let dayCells = "";
  for (let i = 0; i < firstDay; i++) {
    dayCells += `<div class="range-picker-day empty"></div>`;
  }
  for (let d = 1; d <= daysInMonth; d++) {
    const dateStr = `${state.navYear}-${String(state.navMonth + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
    let cls = "range-picker-day";
    if (selStart && dateStr === selStart) cls += " range-start";
    if (selEnd && dateStr === selEnd) cls += " range-end";
    if (selStart && selEnd && dateStr > selStart && dateStr < selEnd) cls += " in-range";
    dayCells += `<button class="${cls}" data-date="${dateStr}">${d}</button>`;
  }

  popoverEl.innerHTML = `
    <div class="range-picker-presets">
      ${DATE_PRESETS.map(p => `<button class="range-picker-preset" data-preset="${p}">${p}</button>`).join("")}
    </div>
    <div class="range-picker-month-nav">
      <button data-nav="prev">&#8249;</button>
      <div class="range-picker-month-label">${monthLabel}</div>
      <button data-nav="next">&#8250;</button>
    </div>
    <div class="range-picker-weekdays">
      <div>S</div><div>M</div><div>T</div><div>W</div><div>T</div><div>F</div><div>S</div>
    </div>
    <div class="range-picker-grid">${dayCells}</div>
  `;

  popoverEl.querySelectorAll(".range-picker-preset").forEach(btn => {
    btn.onclick = () => {
      const range = resolvePreset(btn.dataset.preset);
      state.pendingStart = null;
      document.getElementById("rangePicker-" + instanceKey).classList.remove("open");
      updateRangePickerScrim();
      onApply(btn.dataset.preset, range);
    };
  });

  popoverEl.querySelector('[data-nav="prev"]').onclick = () => {
    state.navMonth--;
    if (state.navMonth < 0) { state.navMonth = 11; state.navYear--; }
    renderRangePickerPopover(instanceKey, currentRange, onApply);
  };

  popoverEl.querySelector('[data-nav="next"]').onclick = () => {
    state.navMonth++;
    if (state.navMonth > 11) { state.navMonth = 0; state.navYear++; }
    renderRangePickerPopover(instanceKey, currentRange, onApply);
  };

  popoverEl.querySelectorAll(".range-picker-day:not(.empty)").forEach(dayBtn => {
    dayBtn.onclick = () => {
      const clickedDate = dayBtn.dataset.date;
      if (!state.pendingStart) {
        state.pendingStart = clickedDate;
        renderRangePickerPopover(instanceKey, currentRange, onApply);
      } else {
        let start = state.pendingStart;
        let end = clickedDate;
        if (end < start) { const t = start; start = end; end = t; }
        state.pendingStart = null;
        document.getElementById("rangePicker-" + instanceKey).classList.remove("open");
        updateRangePickerScrim();
        onApply("Custom", { start, end });
      }
    };
  });
}

function getDataByDate() {
  const rows = allData[currentTab] || [];
  const map = {};
  rows.forEach(r => { map[r.Date] = r; });
  return map;
}

// ---- Calendar view ----
function renderSummary(dateMap) {
  const monthPrefix = `${currentYear}-${String(currentMonth + 1).padStart(2, "0")}`;
  const monthRows = Object.values(dateMap).filter(r => r.Date.startsWith(monthPrefix));
  renderStatsInto("summary", monthRows, "Net Profit (Month)");
}

function renderStatsInto(elId, rows, profitLabel) {
  const totalProfit = rows.reduce((sum, r) => sum + (r.netProfitV2 || 0), 0);
  const totalRevenue = rows.reduce((sum, r) => sum + (r.netRevenueV2 || 0), 0);
  const totalOrders = rows.reduce((sum, r) => sum + (r.ordersFloat || 0), 0);
  const winDays = rows.filter(r => (r.netProfitV2 || 0) > 0).length;

  const el = document.getElementById(elId);
  el.innerHTML = `
    <div class="stat">
      <div class="stat-label">${profitLabel}</div>
      <div class="stat-value ${totalProfit >= 0 ? "pos" : "neg"}">${formatMoney(totalProfit)}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Net Revenue</div>
      <div class="stat-value">${formatMoney(totalRevenue)}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Orders</div>
      <div class="stat-value">${totalOrders}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Win Days</div>
      <div class="stat-value">${winDays} / ${rows.length}</div>
    </div>
  `;
}

function renderCalendar(dateMap) {
  const monthLabel = new Date(currentYear, currentMonth, 1).toLocaleDateString("en-US", { month: "long", year: "numeric" });
  document.getElementById("monthLabel").textContent = monthLabel;

  const firstDay = new Date(currentYear, currentMonth, 1).getDay();
  const daysInMonth = new Date(currentYear, currentMonth + 1, 0).getDate();

  const gridEl = document.getElementById("grid");
  gridEl.innerHTML = "";

  for (let i = 0; i < firstDay; i++) {
    const empty = document.createElement("div");
    empty.className = "day empty";
    gridEl.appendChild(empty);
  }

  for (let d = 1; d <= daysInMonth; d++) {
    const dateStr = `${currentYear}-${String(currentMonth + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
    const record = dateMap[dateStr];
    const cell = document.createElement("div");

    if (!record || record.netProfitV2 === undefined || record.netProfitV2 === "") {
      cell.className = "day no-data";
      cell.innerHTML = `<div class="day-num">${d}</div>`;
    } else {
      const profit = record.netProfitV2;
      cell.className = "day " + (profit >= 0 ? "pos" : "neg");
      cell.innerHTML = `
        <div class="day-num">${d}</div>
        <div>
          <div class="day-value">${formatMoney(profit)}</div>
          <div class="day-orders">${record.ordersFloat || 0} orders</div>
        </div>
      `;
      cell.onclick = () => openDayModal(dateStr, record);
    }
    gridEl.appendChild(cell);
  }
}

function openDayModal(dateStr, record) {
  const dateObj = new Date(dateStr + "T00:00:00");
  const label = dateObj.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric" });
  document.getElementById("modalDate").textContent = label;

  const revenue = record.netRevenueV2 || 0;
  const cogs = record.cogsV2 || 0;
  const adSpend = record.totalAdSpend || 0;
  const profit = record.netProfitV2 || 0;
  const grossProfit = record.grossProfitV2 || 0;
  const orders = record.ordersFloat || 0;

  document.getElementById("modalBody").innerHTML = `
    <div class="modal-row"><div class="modal-row-label">Net Revenue</div><div class="modal-row-value">${formatMoneyFull(revenue)}</div></div>
    <div class="modal-row"><div class="modal-row-label">COGS</div><div class="modal-row-value">${formatMoneyFull(cogs)}</div></div>
    <div class="modal-row"><div class="modal-row-label">Ad Spend</div><div class="modal-row-value">${formatMoneyFull(adSpend)}</div></div>
    <div class="modal-row"><div class="modal-row-label">Gross Profit</div><div class="modal-row-value">${formatMoneyFull(grossProfit)}</div></div>
    <div class="modal-row"><div class="modal-row-label">Net Profit</div><div class="modal-row-value ${profit >= 0 ? "pos" : "neg"}">${formatMoneyFull(profit)}</div></div>
    <div class="modal-row"><div class="modal-row-label">Orders</div><div class="modal-row-value">${orders}</div></div>
  `;

  document.getElementById("modalOverlay").classList.add("open");
}

document.getElementById("modalClose").onclick = () => {
  document.getElementById("modalOverlay").classList.remove("open");
};

document.getElementById("modalOverlay").onclick = (e) => {
  if (e.target === e.currentTarget) document.getElementById("modalOverlay").classList.remove("open");
};

document.getElementById("rangeApply").onclick = () => {
  const start = document.getElementById("rangeStart").value;
  const end = document.getElementById("rangeEnd").value;
  if (!start || !end) return;
  const dateMap = getDataByDate();
  const rows = Object.values(dateMap).filter(r => r.Date >= start && r.Date <= end);
  renderStatsInto("rangeSummary", rows, "Net Profit (Range)");
};

document.getElementById("prevMonth").onclick = () => {
  currentMonth--;
  if (currentMonth < 0) { currentMonth = 11; currentYear--; }
  render();
};

document.getElementById("nextMonth").onclick = () => {
  currentMonth++;
  if (currentMonth > 11) { currentMonth = 0; currentYear++; }
  render();
};

// ---- EBITDA tile view ----
function renderEbitda(dateMap) {
  if (!ebitdaCustomRange) {
    ebitdaCustomRange = resolvePreset(ebitdaPreset, allData[currentTab]);
  }

  const rows = Object.values(dateMap).filter(r => r.Date >= ebitdaCustomRange.start && r.Date <= ebitdaCustomRange.end);
  const rangeLabel = `${ebitdaCustomRange.start} to ${ebitdaCustomRange.end}`;

  const gridEl = document.getElementById("waterfall");
  if (rows.length === 0) {
    gridEl.innerHTML = `<div style="padding:20px;color:var(--text-dim);font-size:13px;grid-column:1/-1;">No data for ${rangeLabel}.</div>`;
    return;
  }

  const revenue = rows.reduce((s, r) => s + (r.netRevenueV2 || 0), 0);
  const cogs = rows.reduce((s, r) => s + (r.cogsV2 || 0), 0);
  const adSpend = rows.reduce((s, r) => s + (r.totalAdSpend || 0), 0);
  const grossProfit = rows.reduce((s, r) => s + (r.grossProfitV2 || 0), 0);
  const netProfit = rows.reduce((s, r) => s + (r.netProfitV2 || 0), 0);
  const orders = rows.reduce((s, r) => s + (r.ordersFloat || 0), 0);

  const margin = revenue ? (netProfit / revenue) * 100 : 0;
  const cogsPct = revenue ? (cogs / revenue) * 100 : 0;
  const adSpendPct = revenue ? (adSpend / revenue) * 100 : 0;
  const aov = orders ? revenue / orders : 0;

  const tiles = [
    { label: "Net Profit", value: formatMoneyFull(netProfit), sub: `${margin.toFixed(1)}% margin`, colorClass: netProfit >= 0 ? "pos" : "neg", dotColor: "var(--pos-text)", featured: true },
    { label: "Revenue", value: formatMoneyFull(revenue), sub: `${orders} orders`, colorClass: "", dotColor: "var(--accent)" },
    { label: "COGS", value: formatMoneyFull(cogs), sub: `${cogsPct.toFixed(1)}% of revenue`, colorClass: "", dotColor: "var(--neg-text)" },
    { label: "Ad Spend", value: formatMoneyFull(adSpend), sub: `${adSpendPct.toFixed(1)}% of revenue`, colorClass: "", dotColor: "var(--neg-text)" },
    { label: "Gross Profit", value: formatMoneyFull(grossProfit), sub: revenue ? `${((grossProfit / revenue) * 100).toFixed(1)}% margin` : "", colorClass: grossProfit >= 0 ? "pos" : "neg", dotColor: "var(--pos-text)" },
    { label: "AOV", value: formatMoneyFull(aov), sub: "avg order value", colorClass: "", dotColor: "var(--accent)" },
  ];

  gridEl.innerHTML = tiles.map(t => `
    <div class="ebitda-tile${t.featured ? ' featured' : ''}">
      <div>
        <div class="ebitda-tile-label"><span class="ebitda-tile-icon" style="background:${t.dotColor}"></span>${t.label}</div>
        <div class="ebitda-tile-value ${t.colorClass}">${t.value}</div>
      </div>
      <div class="ebitda-tile-sub">${t.sub}</div>
    </div>
  `).join("");
}

// ---- Annual summary view ----
function renderAnnual(dateMap) {
  const rowsByYear = {};
  Object.values(dateMap).forEach(r => {
    const year = r.Date.slice(0, 4);
    if (!rowsByYear[year]) rowsByYear[year] = [];
    rowsByYear[year].push(r);
  });

  const years = Object.keys(rowsByYear).sort().reverse();
  const tableEl = document.getElementById("annualTable");

  if (years.length === 0) {
    tableEl.innerHTML = `<tr><td style="padding:20px;color:var(--text-dim);">No data yet.</td></tr>`;
    return;
  }

  let html = `
    <thead>
      <tr>
        <th>Year</th><th>Revenue</th><th>COGS</th><th>Ad Spend</th><th>Net Profit</th><th>Net Margin</th><th>Orders</th>
      </tr>
    </thead>
    <tbody>
  `;

  years.forEach(year => {
    const rows = rowsByYear[year];
    const revenue = rows.reduce((s, r) => s + (r.netRevenueV2 || 0), 0);
    const cogs = rows.reduce((s, r) => s + (r.cogsV2 || 0), 0);
    const adSpend = rows.reduce((s, r) => s + (r.totalAdSpend || 0), 0);
    const netProfit = rows.reduce((s, r) => s + (r.netProfitV2 || 0), 0);
    const orders = rows.reduce((s, r) => s + (r.ordersFloat || 0), 0);
    const margin = revenue ? (netProfit / revenue) * 100 : 0;

    html += `
      <tr>
        <td>${year}</td>
        <td>${formatMoneyFull(revenue)}</td>
        <td>${formatMoneyFull(cogs)}</td>
        <td>${formatMoneyFull(adSpend)}</td>
        <td class="${netProfit >= 0 ? 'pos' : 'neg'}">${formatMoneyFull(netProfit)}</td>
        <td class="${margin >= 0 ? 'pos' : 'neg'}">${margin.toFixed(1)}%</td>
        <td>${orders}</td>
      </tr>
    `;
  });

  html += "</tbody>";
  tableEl.innerHTML = html;
}

// ---- Payouts view ----
function renderPayouts() {
  const payoutsData = allData["Payouts"] || {};
  const record = payoutsData[currentPayoutsTab];
  const el = document.getElementById("payoutsSummary");

  if (!record) {
    el.innerHTML = `<div style="padding:20px;color:var(--text-dim);grid-column:1/-1;">No payout data yet for ${currentPayoutsTab}.</div>`;
    document.getElementById("payoutsHistoryTable").innerHTML = "";
    return;
  }

  const balance = record.Balance || 0;
  const nextAmount = record.NextPayoutAmount || 0;
  const nextDate = record.NextPayoutDate || "";
  const nextDateLabel = nextDate
    ? new Date(nextDate + "T00:00:00").toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })
    : "None scheduled";

  el.innerHTML = `
    <div class="stat">
      <div class="stat-label">Available balance</div>
      <div class="stat-value pos">${formatMoneyFull(balance)}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Next payout</div>
      <div class="stat-value">${nextAmount ? formatMoneyFull(nextAmount) : "—"}</div>
      <div style="font-size:12px;color:var(--text-dim);margin-top:4px;">${nextDateLabel}</div>
    </div>
  `;

  renderPayoutsHistory(record.Payouts || []);
}

function statusPill(status) {
  const map = {
    SCHEDULED: { label: "Scheduled", color: "var(--warn-text)", bg: "var(--neutral-bg)" },
    IN_TRANSIT: { label: "In transit", color: "var(--text-dim)", bg: "var(--neutral-bg)" },
    PAID: { label: "Deposited", color: "var(--pos-text)", bg: "var(--pos-bg)" },
    FAILED: { label: "Failed", color: "var(--neg-text)", bg: "var(--neg-bg)" },
    CANCELLED: { label: "Cancelled", color: "var(--neg-text)", bg: "var(--neg-bg)" },
  };
  const s = map[status] || { label: status || "—", color: "var(--text-dim)", bg: "var(--neutral-bg)" };
  return `<span style="background:${s.bg};color:${s.color};font-size:11px;font-weight:600;padding:3px 10px;border-radius:10px;white-space:nowrap;">${s.label}</span>`;
}

function renderPayoutsHistory(payouts) {
  const tableEl = document.getElementById("payoutsHistoryTable");
  const showBrandColumn = currentPayoutsTab === "Blended";

  if (!payouts.length) {
    tableEl.innerHTML = `<tr><td style="padding:20px;color:var(--text-dim);">No payouts recorded yet.</td></tr>`;
    return;
  }

  const sorted = [...payouts].sort((a, b) => (a.Date < b.Date ? 1 : -1));

  let html = `
    <thead>
      <tr>
        <th>Payout date</th>
        ${showBrandColumn ? "<th>Brand</th>" : ""}
        <th>Status</th>
        <th>Amount</th>
      </tr>
    </thead>
    <tbody>
  `;

  sorted.forEach(p => {
    const dateLabel = new Date(p.Date + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
    html += `
      <tr>
        <td style="text-align:left;">${dateLabel}</td>
        ${showBrandColumn ? `<td style="text-align:left;">${p.Brand}</td>` : ""}
        <td>${statusPill(p.Status)}</td>
        <td>${formatMoneyFull(p.Amount || 0)}</td>
      </tr>
    `;
  });

  html += "</tbody>";
  tableEl.innerHTML = html;
}

// ---- Meta Ads view ----
const META_METRICS = [
  { key: "facebookImpressions", label: "Impressions", format: "number" },
  { key: "facebookReach", label: "Reach", format: "number" },
  { key: "facebookFrequency", label: "Frequency", format: "decimal" },
  { key: "facebookClicks", label: "Clicks", format: "number" },
  { key: "facebookCtr", label: "CTR", format: "percent" },
  { key: "facebookCpc", label: "CPC", format: "money" },
  { key: "facebookCpm", label: "CPM", format: "money" },
  { key: "facebookAdSpend", label: "Ad Spend", format: "money" },
  { key: "facebookRoas", label: "ROAS", format: "decimal" },
  { key: "facebookOrdersFloat", label: "Orders", format: "number" },
  { key: "facebookCpoFloat", label: "Cost / Order", format: "money" },
];

function formatMetricValue(key, value) {
  const metric = META_METRICS.find(m => m.key === key);
  if (value === null || value === undefined || value === "") return "—";
  if (!metric) return String(value);
  if (metric.format === "money") return formatMoneyFull(value);
  if (metric.format === "percent") return value.toFixed(2) + "%";
  if (metric.format === "decimal") return value.toFixed(2);
  return formatNumber(value);
}

function getMetaRows() {
  const rows = allData[currentMetaTab] || [];
  if (!metaCustomRange) {
    metaCustomRange = resolvePreset(metaPreset, rows);
  }
  return rows.filter(r => r.Date >= metaCustomRange.start && r.Date <= metaCustomRange.end);
}

function renderMetaAds() {
  const rows = getMetaRows().slice().sort((a, b) => (a.Date < b.Date ? -1 : 1));
  const gridEl = document.getElementById("metaAdsGrid");

  if (rows.length === 0) {
    gridEl.innerHTML = `<div style="padding:20px;color:var(--text-dim);font-size:13px;grid-column:1/-1;">No data for this range.</div>`;
    return;
  }

  const half = Math.max(1, Math.floor(rows.length / 2));
  const firstHalf = rows.slice(0, half);
  const secondHalf = rows.slice(half);

  gridEl.innerHTML = META_METRICS.map(m => {
    const values = rows.map(r => r[m.key]).filter(v => v !== null && v !== undefined && v !== "");
    if (values.length === 0) {
      return `
        <div class="ebitda-tile">
          <div class="ebitda-tile-label"><span class="ebitda-tile-icon" style="background:var(--text-dim)"></span>${m.label}</div>
          <div class="ebitda-tile-value">—</div>
          <div class="ebitda-tile-sub">No data</div>
        </div>
      `;
    }

    const isRate = m.format === "percent" || m.format === "decimal" || m.key === "facebookCpc" || m.key === "facebookCpm" || m.key === "facebookCpoFloat";
    const aggValue = isRate
      ? values.reduce((s, v) => s + v, 0) / values.length
      : values.reduce((s, v) => s + v, 0);

    const firstHalfVals = firstHalf.map(r => r[m.key]).filter(v => v !== null && v !== undefined && v !== "");
    const secondHalfVals = secondHalf.map(r => r[m.key]).filter(v => v !== null && v !== undefined && v !== "");
    const firstAvg = firstHalfVals.length ? firstHalfVals.reduce((s, v) => s + v, 0) / firstHalfVals.length : 0;
    const secondAvg = secondHalfVals.length ? secondHalfVals.reduce((s, v) => s + v, 0) / secondHalfVals.length : 0;
    const pctChange = firstAvg ? ((secondAvg - firstAvg) / firstAvg) * 100 : 0;

    // For cost/efficiency metrics, a decrease is good (trend arrow color flips)
    const lowerIsBetter = ["facebookCpc", "facebookCpm", "facebookCpoFloat", "facebookFrequency"].includes(m.key);
    const isGoodTrend = lowerIsBetter ? pctChange < 0 : pctChange > 0;
    const trendClass = Math.abs(pctChange) < 1 ? "" : (isGoodTrend ? "up" : "down");
    const trendArrow = pctChange > 0 ? "&#9650;" : (pctChange < 0 ? "&#9660;" : "");

    return `
      <div class="ebitda-tile meta-tile" data-metric="${m.key}" data-label="${m.label}">
        <div class="ebitda-tile-label"><span class="ebitda-tile-icon" style="background:var(--accent)"></span>${m.label}</div>
        <div class="ebitda-tile-value">${formatMetricValue(m.key, aggValue)}</div>
        <div class="meta-tile-trend ${trendClass}">${trendArrow ? trendArrow + " " + Math.abs(pctChange).toFixed(1) + "%" : "steady"}</div>
      </div>
    `;
  }).join("");

  gridEl.querySelectorAll(".meta-tile").forEach(tile => {
    tile.onclick = () => openMetricChart(tile.dataset.metric, tile.dataset.label, rows);
  });
}

function openMetricChart(metricKey, label, rows) {
  document.getElementById("chartModalTitle").textContent = label;
  const points = rows.map(r => ({ date: r.Date, value: r[metricKey] })).filter(p => p.value !== null && p.value !== undefined && p.value !== "");

  const wrapEl = document.getElementById("chartSvgWrap");
  if (points.length < 2) {
    wrapEl.innerHTML = `<div style="padding:20px;color:var(--text-dim);font-size:13px;">Not enough data points to chart yet.</div>`;
  } else {
    wrapEl.innerHTML = buildLineChartSvg(points, metricKey);
    wireChartTooltip();
  }

  document.getElementById("chartModalOverlay").classList.add("open");
}

function buildLineChartSvg(points, metricKey) {
  const width = 520, height = 220, padding = { top: 16, right: 16, bottom: 28, left: 44 };
  const chartW = width - padding.left - padding.right;
  const chartH = height - padding.top - padding.bottom;

  const values = points.map(p => p.value);
  const minV = Math.min(...values, 0);
  const maxV = Math.max(...values);
  const range = (maxV - minV) || 1;

  const xStep = chartW / Math.max(1, points.length - 1);
  const coords = points.map((p, i) => {
    const x = padding.left + i * xStep;
    const y = padding.top + chartH - ((p.value - minV) / range) * chartH;
    return { x, y, ...p };
  });

  const linePath = coords.map((c, i) => (i === 0 ? "M" : "L") + c.x.toFixed(1) + "," + c.y.toFixed(1)).join(" ");
  const areaPath = linePath + ` L${coords[coords.length - 1].x.toFixed(1)},${padding.top + chartH} L${coords[0].x.toFixed(1)},${padding.top + chartH} Z`;

  const firstLabel = new Date(points[0].date + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });
  const lastLabel = new Date(points[points.length - 1].date + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });

  const dots = coords.map(c => `<circle cx="${c.x.toFixed(1)}" cy="${c.y.toFixed(1)}" r="2.5" fill="var(--accent)" />`).join("");

  // Invisible larger hit targets per point, each carrying its data via data-* attrs
  // for the shared mousemove handler to read and position a tooltip against.
  const hitTargets = coords.map((c, i) => {
    const dateLabel = new Date(c.date + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
    const valueLabel = formatMetricValue(metricKey, c.value);
    return `<circle cx="${c.x.toFixed(1)}" cy="${c.y.toFixed(1)}" r="10" fill="transparent" class="chart-hit" data-date="${dateLabel}" data-value="${valueLabel}" />`;
  }).join("");

  return `
    <div id="chartTooltip" style="position:absolute;display:none;background:var(--panel-solid);border:1px solid var(--panel-border);border-radius:8px;padding:6px 10px;font-size:12px;pointer-events:none;box-shadow:0 4px 12px rgba(0,0,0,0.25);z-index:10;white-space:nowrap;"></div>
    <svg viewBox="0 0 ${width} ${height}" style="width:100%;height:auto;font-family:var(--font-body);overflow:visible;" id="chartSvg">
      <line x1="${padding.left}" y1="${padding.top}" x2="${padding.left}" y2="${padding.top + chartH}" stroke="var(--panel-border)" stroke-width="1" />
      <line x1="${padding.left}" y1="${padding.top + chartH}" x2="${width - padding.right}" y2="${padding.top + chartH}" stroke="var(--panel-border)" stroke-width="1" />
      <path d="${areaPath}" fill="var(--accent)" opacity="0.12" />
      <path d="${linePath}" fill="none" stroke="var(--accent)" stroke-width="2" />
      ${dots}
      <text x="${padding.left}" y="${height - 6}" fill="var(--text-dim)" font-size="10">${firstLabel}</text>
      <text x="${width - padding.right}" y="${height - 6}" fill="var(--text-dim)" font-size="10" text-anchor="end">${lastLabel}</text>
      <text x="${padding.left - 6}" y="${padding.top + 4}" fill="var(--text-dim)" font-size="10" text-anchor="end">${formatMetricValue(metricKey, Math.max(...points.map(p => p.value)))}</text>
      <text x="${padding.left - 6}" y="${padding.top + chartH}" fill="var(--text-dim)" font-size="10" text-anchor="end">${formatMetricValue(metricKey, Math.min(...points.map(p => p.value)))}</text>
      ${hitTargets}
    </svg>
  `;
}

function wireChartTooltip() {
  const svgEl = document.getElementById("chartSvg");
  const tooltipEl = document.getElementById("chartTooltip");
  if (!svgEl || !tooltipEl) return;

  svgEl.querySelectorAll(".chart-hit").forEach(hit => {
    hit.addEventListener("mouseenter", (e) => {
      tooltipEl.textContent = `${hit.dataset.date} — ${hit.dataset.value}`;
      tooltipEl.style.display = "block";
    });
    hit.addEventListener("mousemove", (e) => {
      const wrapRect = document.getElementById("chartSvgWrap").getBoundingClientRect();
      tooltipEl.style.left = (e.clientX - wrapRect.left + 12) + "px";
      tooltipEl.style.top = (e.clientY - wrapRect.top - 28) + "px";
    });
    hit.addEventListener("mouseleave", () => {
      tooltipEl.style.display = "none";
    });
  });
}


document.getElementById("chartModalClose").onclick = () => {
  document.getElementById("chartModalOverlay").classList.remove("open");
};

document.getElementById("chartModalOverlay").onclick = (e) => {
  if (e.target === e.currentTarget) document.getElementById("chartModalOverlay").classList.remove("open");
};

// ---- Main render ----
function render() {
  const pnlBrands = getPnlBrandNames();
  buildBrandPicker("calendar", pnlBrands, currentTab, (name) => { currentTab = name; render(); });
  buildBrandPicker("ebitda", pnlBrands, currentTab, (name) => { currentTab = name; render(); });
  buildBrandPicker("annual", pnlBrands, currentTab, (name) => { currentTab = name; render(); });
  buildBrandPicker("metaads", pnlBrands, currentMetaTab, (name) => { currentMetaTab = name; render(); });

  const payoutsBrands = getPayoutsBrandNames();
  buildBrandPicker("payouts", payoutsBrands, currentPayoutsTab, (name) => { currentPayoutsTab = name; render(); });

  buildRangePicker("ebitda", ebitdaPreset, ebitdaCustomRange, (preset, range) => {
    ebitdaPreset = preset;
    ebitdaCustomRange = range;
    render();
  });

  buildRangePicker("meta", metaPreset, metaCustomRange, (preset, range) => {
    metaPreset = preset;
    metaCustomRange = range;
    render();
  });

  const dateMap = getDataByDate();

  if (currentView === "calendar") {
    renderSummary(dateMap);
    renderCalendar(dateMap);
    const start = document.getElementById("rangeStart").value;
    const end = document.getElementById("rangeEnd").value;
    if (start && end) {
      const rows = Object.values(dateMap).filter(r => r.Date >= start && r.Date <= end);
      renderStatsInto("rangeSummary", rows, "Net Profit (Range)");
    } else {
      document.getElementById("rangeSummary").innerHTML = "";
    }
  } else if (currentView === "ebitda") {
    renderEbitda(dateMap);
  } else if (currentView === "annual") {
    renderAnnual(dateMap);
  } else if (currentView === "payouts") {
    renderPayouts();
  } else if (currentView === "metaads") {
    renderMetaAds();
  }
}

// ---- Load data ----
initTheme();

fetch("data.json")
  .then(res => res.json())
  .then(data => {
    allData = data;
    const blended = allData["Blended"] || [];
    if (blended.length > 0) {
      const dates = blended.map(r => r.Date).filter(Boolean).sort();
      const lastDateStr = dates[dates.length - 1];
      const [y, m] = lastDateStr.split("-").map(Number);
      currentYear = y;
      currentMonth = m - 1;
    }
    render();
  })
  .catch(err => {
    document.getElementById("grid").innerHTML = `<div style="padding:24px;color:var(--text-dim);grid-column:1/-1;">Couldn't load data.json — ${err}</div>`;
  });
