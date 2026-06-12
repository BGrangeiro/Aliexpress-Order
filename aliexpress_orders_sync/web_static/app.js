const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const elements = {
  account: $("#account-select"),
  responsible: $("#responsible-select"),
  openBrowser: $("#open-browser"),
  startMonitor: $("#start-monitor"),
  stopMonitor: $("#stop-monitor"),
  fullSync: $("#full-sync"),
  refreshOrders: $("#refresh-orders"),
  clearLogs: $("#clear-visible-logs"),
  clearFilters: $("#clear-filters"),
  connection: $("#connection-state"),
  status: $("#status-value"),
  statusDetail: $("#status-detail"),
  sidebarStatus: $("#sidebar-status-value"),
  sidebarDetail: $("#sidebar-status-detail"),
  pageHeading: $("#page-heading"),
  pageEyebrow: $("#page-eyebrow"),
  filterSummary: $("#filter-summary"),
  ordersCount: $("#orders-count"),
  ordersBody: $("#orders-body"),
  trackingBody: $("#tracking-body"),
  trackingResults: $("#tracking-results"),
  activityList: $("#activity-list"),
  filterAccount: $("#filter-account"),
  filterStatus: $("#filter-status"),
  filterTracking: $("#filter-tracking"),
  filterPayment: $("#filter-payment"),
  filterCurrency: $("#filter-currency"),
  filterDateFrom: $("#filter-date-from"),
  filterDateTo: $("#filter-date-to"),
  filterMinTotal: $("#filter-min-total"),
  filterMaxTotal: $("#filter-max-total"),
  filterSearch: $("#filter-search"),
  toast: $("#toast"),
  settingsModal: $("#settings-modal"),
  openSettings: $("#open-settings"),
  closeSettings: $("#close-settings"),
  accountForm: $("#account-form"),
  newAccountResponsible: $("#new-account-responsible"),
  newAccountName: $("#new-account-name"),
  newAccountEmail: $("#new-account-email"),
  settingsAccountsList: $("#settings-accounts-list"),
  settingsHome: $("#settings-home"),
  purchaseAccountsSettings: $("#purchase-accounts-settings"),
  openPurchaseAccounts: $("#open-purchase-accounts"),
  settingsBack: $("#settings-back"),
  editAccountKey: $("#edit-account-key"),
  accountFormTitle: $("#account-form-title"),
  accountSubmit: $("#account-submit"),
  cancelAccountEdit: $("#cancel-account-edit"),
};

const viewMeta = {
  overview: ["Operação", "Visão geral"],
  orders: ["Dados", "Pedidos"],
  tracking: ["Logística", "Rastreios"],
  activity: ["Sistema", "Atividade"],
};

const chartColors = ["#2f8cff", "#42c995", "#eab452", "#ef6a78", "#9a86f7", "#2ac4d6", "#7895ad"];
let accounts = [];
let responsibles = [];
let currentState = null;
let currentOrders = [];
let currentAnalytics = null;
let activeView = "overview";
let visibleLogsClearedAt = "";
let lastLogSignature = "";
let searchTimer = null;
let toastTimer = null;
let resizeTimer = null;

document.addEventListener("DOMContentLoaded", async () => {
  bindActions();
  await Promise.all([loadAccounts(), loadFilterOptions()]);
  if (window.lucide) window.lucide.createIcons();
  await Promise.all([refreshState(), refreshData()]);
  window.setInterval(refreshState, 2000);
  window.setInterval(refreshData, 15000);
});

function bindActions() {
  $$(".nav-item").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.view)));

  elements.account.addEventListener("change", async () => {
    await postCommand("/api/account", { account_key: selectedAccount() }, "Conta selecionada.");
    await refreshState();
  });
  elements.responsible.addEventListener("change", async () => {
    populateAccountSelectors();
    if (elements.account.value) {
      await postCommand("/api/account", { account_key: selectedAccount() }, "Responsável selecionado.");
    }
    await refreshData();
  });
  elements.openBrowser.addEventListener("click", () => postCommand("/api/browser/open", commandBody(), "AliExpress aberto."));
  elements.startMonitor.addEventListener("click", () => postCommand("/api/monitor/start", commandBody(), "Monitoramento iniciado."));
  elements.stopMonitor.addEventListener("click", () => postCommand("/api/monitor/stop", {}, "Parada solicitada."));
  elements.fullSync.addEventListener("click", () => postCommand("/api/sync/full", commandBody(), "Verificação completa iniciada."));
  elements.refreshOrders.addEventListener("click", refreshData);

  const immediateFilters = [
    elements.filterAccount, elements.filterStatus, elements.filterTracking,
    elements.filterPayment, elements.filterCurrency, elements.filterDateFrom,
    elements.filterDateTo,
  ];
  immediateFilters.forEach((control) => control.addEventListener("change", () => {
    clearPeriodSelection();
    refreshData();
  }));

  [elements.filterMinTotal, elements.filterMaxTotal, elements.filterSearch].forEach((control) => {
    control.addEventListener("input", () => {
      window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(refreshData, 400);
    });
  });

  $$(".date-presets button").forEach((button) => button.addEventListener("click", () => setPeriod(button.dataset.period)));
  elements.clearFilters.addEventListener("click", clearFilters);
  elements.clearLogs.addEventListener("click", () => {
    const logs = currentState?.logs || [];
    visibleLogsClearedAt = logs.length ? logs[logs.length - 1].timestamp : new Date().toISOString();
    renderLogs(logs);
  });
  elements.openSettings.addEventListener("click", openSettings);
  elements.closeSettings.addEventListener("click", closeSettings);
  elements.settingsModal.addEventListener("click", (event) => {
    if (event.target === elements.settingsModal) closeSettings();
  });
  elements.accountForm.addEventListener("submit", createAccount);
  elements.openPurchaseAccounts.addEventListener("click", openPurchaseAccounts);
  elements.settingsBack.addEventListener("click", showSettingsHome);
  elements.cancelAccountEdit.addEventListener("click", resetAccountForm);
  elements.settingsAccountsList.addEventListener("click", handleAccountAction);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !elements.settingsModal.hidden) closeSettings();
  });

  window.addEventListener("resize", () => {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(renderCharts, 120);
  });
}

async function loadAccounts() {
  const data = await request("/api/accounts");
  accounts = data.accounts || [];
  responsibles = data.responsibles || [];
  const selectedResponsible = elements.responsible.value;
  elements.responsible.replaceChildren();
  elements.newAccountResponsible.replaceChildren();
  for (const responsible of responsibles) {
    elements.responsible.append(option(responsible, responsible));
    elements.newAccountResponsible.append(option(responsible, responsible));
  }
  if (selectedResponsible && responsibles.includes(selectedResponsible)) {
    elements.responsible.value = selectedResponsible;
  }
  populateAccountSelectors();
  renderSettingsAccounts();
}

function populateAccountSelectors() {
  const responsible = selectedResponsible();
  const filtered = accounts.filter((account) => account.responsible.toLowerCase() === responsible.toLowerCase());
  const previousAccount = elements.account.value;
  elements.account.replaceChildren();
  elements.filterAccount.replaceChildren(option("", "Todos do responsável"));
  for (const account of filtered) {
    const label = `${account.display_name} · ${account.email}`;
    elements.account.append(option(account.key, label));
    elements.filterAccount.append(option(account.key, label));
  }
  if (filtered.some((account) => account.key === previousAccount)) {
    elements.account.value = previousAccount;
  }
}

async function loadFilterOptions() {
  const data = await request("/api/filter-options");
  for (const status of data.statuses || []) elements.filterStatus.append(option(status, status));
  for (const payment of data.payment_methods || []) elements.filterPayment.append(option(payment, payment));
  for (const currency of data.currencies || []) elements.filterCurrency.append(option(currency, currency));
}

function option(value, text) {
  const item = document.createElement("option");
  item.value = value;
  item.textContent = text;
  return item;
}

async function refreshState() {
  try {
    currentState = await request("/api/state");
    setConnection(true);
    renderState(currentState);
  } catch (_error) {
    setConnection(false);
  }
}

async function refreshData() {
  elements.refreshOrders?.classList.add("rotating");
  try {
    const query = filtersQuery();
    const [ordersData, analytics] = await Promise.all([
      request(`/api/orders?${query}&limit=1000`),
      request(`/api/analytics?${query}`),
    ]);
    currentOrders = ordersData.orders || [];
    currentAnalytics = analytics;
    renderAll();
  } catch (error) {
    showToast(error.message, true);
  } finally {
    elements.refreshOrders?.classList.remove("rotating");
  }
}

function renderAll() {
  renderFilterSummary();
  renderKpis();
  renderCharts();
  renderRankings();
  renderOrders();
  renderTracking();
}

function renderState(state) {
  if (state.selected_account_key && elements.account.value !== state.selected_account_key) {
    const account = accounts.find((item) => item.key === state.selected_account_key);
    if (account) {
      elements.responsible.value = account.responsible;
      populateAccountSelectors();
      elements.account.value = state.selected_account_key;
    }
  }
  elements.status.textContent = state.status;
  elements.statusDetail.textContent = state.status_detail;
  elements.sidebarStatus.textContent = state.status;
  elements.sidebarDetail.textContent = state.status_detail;
  elements.account.disabled = state.busy || state.monitoring;
  elements.openBrowser.disabled = state.busy || state.monitoring;
  elements.startMonitor.disabled = state.busy || state.monitoring;
  elements.stopMonitor.disabled = !state.monitoring;
  elements.fullSync.disabled = state.busy || state.monitoring;

  $("#activity-account").textContent = state.selected_account?.email || "-";
  $("#last-check-label").textContent = formatDateTime(state.last_check);
  $("#next-check-label").textContent = formatDateTime(state.next_check);
  $("#last-result-label").textContent =
    `${state.last_result.read} lidos · ${state.last_result.created} novos · ${state.last_result.updated} atualizados`;
  $("#database-label").textContent = state.database_path || "-";
  renderLogs(state.logs || []);
}

function renderKpis() {
  const summary = currentAnalytics?.summary || {};
  const total = summary.total_orders || 0;
  const currency = currentAnalytics?.currencies?.[0]?.currency || "BRL";
  $("#kpi-orders").textContent = formatNumber(total);
  $("#kpi-volume").textContent = formatMoney(summary.gross_value || 0, currency);
  $("#kpi-average").textContent = formatMoney(summary.average_ticket || 0, currency);
  $("#kpi-items").textContent = formatNumber(summary.total_items || 0);
  $("#kpi-progress").textContent = formatNumber(summary.in_progress || 0);
  $("#kpi-canceled").textContent = formatNumber(summary.canceled || 0);
  $("#kpi-progress-rate").textContent = `${percentage(summary.in_progress, total)}% dos pedidos`;
  $("#kpi-canceled-rate").textContent = `${percentage(summary.canceled, total)}% dos pedidos`;
  $("#kpi-currency").textContent = currentAnalytics?.currencies?.length > 1
    ? `${currentAnalytics.currencies.length} moedas no resultado`
    : `Valores em ${currency}`;
  $("#kpi-period").textContent = activePeriodLabel();
}

function renderCharts() {
  if (!currentAnalytics || activeView !== "overview") return;
  drawTrendChart($("#trend-chart"), currentAnalytics.monthly || []);
  drawDonutChart($("#status-chart"), currentAnalytics.statuses || []);
  renderStatusLegend(currentAnalytics.statuses || []);
  $("#status-total").textContent = formatNumber(currentAnalytics.summary?.total_orders || 0);
  $("#trend-total").textContent = `${formatNumber(currentAnalytics.summary?.total_orders || 0)} pedidos`;
}

function drawTrendChart(canvas, rows) {
  const { ctx, width, height } = prepareCanvas(canvas);
  if (!ctx) return;
  ctx.clearRect(0, 0, width, height);
  if (!rows.length) return drawEmptyChart(ctx, width, height);

  const padding = { left: 52, right: 18, top: 18, bottom: 38 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const values = rows.map((row) => Number(row.total_value || 0));
  const counts = rows.map((row) => Number(row.orders_count || 0));
  const maxValue = Math.max(...values, 1);
  const maxCount = Math.max(...counts, 1);
  const points = values.map((value, index) => ({
    x: padding.left + (rows.length === 1 ? plotWidth / 2 : (index / (rows.length - 1)) * plotWidth),
    y: padding.top + plotHeight - (value / maxValue) * plotHeight,
  }));

  ctx.strokeStyle = "#1f3850";
  ctx.lineWidth = 1;
  ctx.font = "10px Segoe UI";
  ctx.fillStyle = "#7890a6";
  for (let i = 0; i <= 4; i += 1) {
    const y = padding.top + (plotHeight / 4) * i;
    ctx.beginPath(); ctx.moveTo(padding.left, y); ctx.lineTo(width - padding.right, y); ctx.stroke();
    const label = formatCompact(maxValue - (maxValue / 4) * i);
    ctx.fillText(label, 4, y + 3);
  }

  rows.forEach((row, index) => {
    const x = points[index].x;
    const barHeight = (counts[index] / maxCount) * (plotHeight * .36);
    ctx.fillStyle = "rgba(42,196,214,.22)";
    ctx.fillRect(x - 9, padding.top + plotHeight - barHeight, 18, barHeight);
    ctx.fillStyle = "#7890a6";
    ctx.textAlign = "center";
    ctx.fillText(monthLabel(row.month), x, height - 13);
  });

  ctx.beginPath();
  points.forEach((point, index) => index ? ctx.lineTo(point.x, point.y) : ctx.moveTo(point.x, point.y));
  ctx.strokeStyle = "#2f8cff";
  ctx.lineWidth = 3;
  ctx.stroke();

  points.forEach((point) => {
    ctx.beginPath(); ctx.arc(point.x, point.y, 4, 0, Math.PI * 2);
    ctx.fillStyle = "#07111f"; ctx.fill();
    ctx.strokeStyle = "#68aeff"; ctx.lineWidth = 2; ctx.stroke();
  });
  ctx.textAlign = "left";
}

function drawDonutChart(canvas, rows) {
  const { ctx, width, height } = prepareCanvas(canvas);
  if (!ctx) return;
  ctx.clearRect(0, 0, width, height);
  const total = rows.reduce((sum, row) => sum + Number(row.value || 0), 0);
  if (!total) return drawEmptyChart(ctx, width, height);
  const centerX = width / 2;
  const centerY = height / 2;
  const radius = Math.min(width, height) * .39;
  let angle = -Math.PI / 2;
  rows.forEach((row, index) => {
    const slice = (Number(row.value || 0) / total) * Math.PI * 2;
    ctx.beginPath();
    ctx.arc(centerX, centerY, radius, angle, angle + slice);
    ctx.strokeStyle = chartColors[index % chartColors.length];
    ctx.lineWidth = Math.max(18, radius * .24);
    ctx.stroke();
    angle += slice;
  });
}

function prepareCanvas(canvas) {
  if (!canvas) return {};
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return {};
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(rect.width * ratio);
  canvas.height = Math.round(rect.height * ratio);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  return { ctx, width: rect.width, height: rect.height };
}

function drawEmptyChart(ctx, width, height) {
  ctx.fillStyle = "#7890a6";
  ctx.font = "11px Segoe UI";
  ctx.textAlign = "center";
  ctx.fillText("Nenhum dado para o filtro atual", width / 2, height / 2);
}

function renderStatusLegend(rows) {
  const total = rows.reduce((sum, row) => sum + Number(row.value || 0), 0);
  $("#status-legend").innerHTML = rows.map((row, index) => `
    <div class="legend-item">
      <span class="legend-dot" style="background:${chartColors[index % chartColors.length]}"></span>
      <span title="${escapeHtml(row.label)}">${escapeHtml(row.label || "Não identificado")}</span>
      <strong>${row.value} · ${percentage(row.value, total)}%</strong>
    </div>
  `).join("") || '<div class="empty-state">Sem dados</div>';
}

function renderRankings() {
  const currency = currentAnalytics?.currencies?.[0]?.currency || "BRL";
  renderRanking($("#accounts-ranking"), currentAnalytics?.accounts || [], "total_value", (row) => formatMoney(row.total_value, currency));
  renderRanking($("#payments-ranking"), currentAnalytics?.payments || [], "value", (row) => `${row.value} pedidos`);

  const products = currentAnalytics?.top_products || [];
  $("#products-ranking").innerHTML = products.map((row, index) => `
    <div class="product-row">
      <span class="product-index">${index + 1}</span>
      <span class="product-name" title="${escapeHtml(row.label)}">${escapeHtml(row.label)}</span>
      <span class="product-meta">${row.items_count} itens</span>
      <span class="product-total">${formatMoney(row.total_value, currency)}</span>
    </div>
  `).join("") || '<div class="empty-state">Sem produtos para exibir</div>';
}

function renderRanking(container, rows, valueKey, valueFormatter) {
  const max = Math.max(...rows.map((row) => Number(row[valueKey] || 0)), 1);
  container.innerHTML = rows.slice(0, 7).map((row) => `
    <div class="ranking-item">
      <span class="ranking-label" title="${escapeHtml(row.label)}">${escapeHtml(row.label)}</span>
      <span class="ranking-track"><span class="ranking-fill" style="width:${Math.max(3, (Number(row[valueKey] || 0) / max) * 100)}%"></span></span>
      <span class="ranking-value">${valueFormatter(row)}</span>
    </div>
  `).join("") || '<div class="empty-state">Sem dados</div>';
}

function renderOrders() {
  elements.ordersCount.textContent = `${formatNumber(currentOrders.length)} registros`;
  elements.ordersBody.innerHTML = currentOrders.map((order) => `
    <tr>
      <td>${escapeHtml(order.order_date)}</td>
      <td class="description" title="${escapeHtml(order.description)}">${escapeHtml(order.description)}</td>
      <td>${order.quantity}</td>
      <td>${formatMoney(order.total, order.currency)}</td>
      <td>${formatMoney(order.unit_value, order.currency)}</td>
      <td>${escapeHtml(order.responsible || "-")}</td>
      <td>${escapeHtml(accountName(order))}</td>
      <td><span class="status-pill ${statusClass(order.status)}" title="${escapeHtml(order.status)}">${escapeHtml(order.status || "-")}</span></td>
      <td>${trackingHtml(order)}</td>
      <td>${escapeHtml(order.payment_method || "-")}</td>
      <td class="order-id">${escapeHtml(order.order_id)}</td>
    </tr>
  `).join("") || emptyRow(11, "Nenhum pedido encontrado para estes filtros.");
}

function renderTracking() {
  const tracking = currentAnalytics?.tracking || {};
  $("#tracking-none").textContent = formatNumber(tracking.none || 0);
  $("#tracking-single").textContent = formatNumber(tracking.single || 0);
  $("#tracking-multiple").textContent = formatNumber(tracking.multiple || 0);
  $("#tracking-total").textContent = formatNumber((tracking.single || 0) + (tracking.multiple || 0));
  $("#tracking-nav-count").textContent = formatNumber(tracking.multiple || 0);

  const tracked = currentOrders.filter((order) => order.tracking_numbers?.length);
  elements.trackingResults.textContent = `${formatNumber(tracked.length)} pedidos`;
  elements.trackingBody.innerHTML = tracked.map((order) => `
    <tr>
      <td class="order-id">${escapeHtml(order.order_id)}</td>
      <td class="tracking-product" title="${escapeHtml(order.description)}">${escapeHtml(order.description)}</td>
      <td>${escapeHtml(accountName(order))}</td>
      <td><span class="status-pill ${statusClass(order.status)}">${escapeHtml(order.status || "-")}</span></td>
      <td>${order.tracking_count}</td>
      <td>${trackingHtml(order)}</td>
    </tr>
  `).join("") || emptyRow(6, "Nenhum rastreio encontrado para estes filtros.");
}

function trackingHtml(order) {
  if (!order.tracking_numbers?.length) return '<span class="muted-value">Ainda não disponível</span>';
  const count = order.tracking_count > 1 ? `<span class="package-count">${order.tracking_count} pacotes</span>` : "";
  return `<div class="tracking-list">${count}${order.tracking_numbers.map((number) =>
    `<span class="tracking-code">${escapeHtml(number)}</span>`).join("")}</div>`;
}

function renderLogs(logs) {
  const visible = visibleLogsClearedAt ? logs.filter((entry) => entry.timestamp > visibleLogsClearedAt) : logs;
  const recent = visible.slice(-120).reverse();
  const signature = recent.map((entry) => `${entry.timestamp}:${entry.message}`).join("|");
  if (signature === lastLogSignature) return;
  lastLogSignature = signature;
  elements.activityList.innerHTML = recent.map((entry) => `
    <div class="activity-item ${entry.level || "info"}">
      <time>${formatDateTime(entry.timestamp)}</time>
      <p>${escapeHtml(entry.message)}</p>
    </div>
  `).join("") || '<div class="empty-state">Sem atividade</div>';
}

function renderFilterSummary() {
  const labels = [selectedResponsible()];
  if (elements.filterAccount.value) labels.push(elements.filterAccount.selectedOptions[0]?.textContent);
  if (elements.filterStatus.value) labels.push(elements.filterStatus.value);
  if (elements.filterTracking.value !== "all") labels.push(elements.filterTracking.selectedOptions[0]?.textContent);
  if (elements.filterPayment.value) labels.push(elements.filterPayment.value);
  if (elements.filterCurrency.value) labels.push(elements.filterCurrency.value);
  if (elements.filterSearch.value.trim()) labels.push(`Busca: ${elements.filterSearch.value.trim()}`);
  elements.filterSummary.textContent = labels.length ? labels.join(" · ") : "Todos os pedidos";
}

function switchView(view) {
  activeView = view;
  $$(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === view));
  $$(".view-panel").forEach((panel) => panel.classList.toggle("active", panel.id === `view-${view}`));
  elements.pageEyebrow.textContent = viewMeta[view][0];
  elements.pageHeading.textContent = viewMeta[view][1];
  if (view === "overview") window.setTimeout(renderCharts, 20);
}

function setPeriod(period) {
  $$(".date-presets button").forEach((button) => button.classList.toggle("active", button.dataset.period === period));
  const today = new Date();
  const iso = (date) => date.toISOString().slice(0, 10);
  if (period === "all") {
    elements.filterDateFrom.value = "";
    elements.filterDateTo.value = "";
  } else if (period === "year") {
    elements.filterDateFrom.value = `${today.getFullYear()}-01-01`;
    elements.filterDateTo.value = iso(today);
  } else {
    const start = new Date(today);
    start.setDate(start.getDate() - Number(period));
    elements.filterDateFrom.value = iso(start);
    elements.filterDateTo.value = iso(today);
  }
  refreshData();
}

function clearPeriodSelection() {
  $$(".date-presets button").forEach((button) => button.classList.remove("active"));
}

function clearFilters() {
  elements.filterAccount.value = "";
  elements.filterStatus.value = "";
  elements.filterTracking.value = "all";
  elements.filterPayment.value = "";
  elements.filterCurrency.value = "";
  elements.filterDateFrom.value = "";
  elements.filterDateTo.value = "";
  elements.filterMinTotal.value = "";
  elements.filterMaxTotal.value = "";
  elements.filterSearch.value = "";
  setPeriod("all");
}

function filtersQuery() {
  const params = new URLSearchParams({
    account_key: elements.filterAccount.value,
    responsible: selectedResponsible(),
    status: elements.filterStatus.value,
    tracking: elements.filterTracking.value,
    payment_method: elements.filterPayment.value,
    currency: elements.filterCurrency.value,
    date_from: elements.filterDateFrom.value,
    date_to: elements.filterDateTo.value,
    search: elements.filterSearch.value.trim(),
  });
  if (elements.filterMinTotal.value) params.set("min_total", elements.filterMinTotal.value);
  if (elements.filterMaxTotal.value) params.set("max_total", elements.filterMaxTotal.value);
  return params.toString();
}

async function postCommand(url, body, successMessage) {
  try {
    await request(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    showToast(successMessage);
    await refreshState();
  } catch (error) {
    showToast(error.message, true);
  }
}

async function request(url, options = {}) {
  const response = await fetch(url, options);
  let data = {};
  try { data = await response.json(); } catch (_error) { data = {}; }
  if (!response.ok) throw new Error(data.detail || `Erro ${response.status}`);
  return data;
}

function accountName(order) {
  return accounts.find((item) => item.key === order.account_key)?.display_name || order.responsible || order.account_key;
}
function selectedAccount() { return elements.account.value || null; }
function selectedResponsible() { return elements.responsible.value || responsibles[0] || ""; }
function commandBody() { return { account_key: selectedAccount() }; }
function emptyRow(columns, text) { return `<tr class="empty-row"><td colspan="${columns}">${text}</td></tr>`; }
function percentage(value, total) { return total ? Math.round((Number(value || 0) / total) * 100) : 0; }
function formatNumber(value) { return new Intl.NumberFormat("pt-BR").format(Number(value || 0)); }
function formatCompact(value) { return new Intl.NumberFormat("pt-BR", { notation: "compact", maximumFractionDigits: 1 }).format(value); }
function formatMoney(value, currency = "BRL") {
  if (value === null || value === undefined) return "-";
  const normalized = ["BRL", "USD", "EUR"].includes(currency) ? currency : "BRL";
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: normalized }).format(value);
}
function monthLabel(value) {
  if (!value) return "";
  const [year, month] = value.split("-");
  return `${month}/${year.slice(2)}`;
}
function activePeriodLabel() {
  const active = $(".date-presets button.active");
  return active?.textContent || "Período personalizado";
}
function formatDateTime(value) {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
function statusClass(status) {
  const normalized = String(status || "").toLowerCase();
  if (/(completed|delivered|entregue|conclu)/.test(normalized)) return "success";
  if (/(canceled|cancelled|cancelado|expired|expirado)/.test(normalized)) return "danger";
  if (/(awaiting|aguardando|to pay|a pagar|transit|caminho|shipped|enviado)/.test(normalized)) return "warning";
  return "";
}
function setConnection(online) {
  elements.connection.classList.toggle("offline", !online);
  elements.connection.lastChild.textContent = online ? " Online" : " Offline";
}
function escapeHtml(value) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}
function showToast(message, isError = false) {
  window.clearTimeout(toastTimer);
  elements.toast.textContent = message;
  elements.toast.classList.toggle("error", isError);
  elements.toast.classList.add("visible");
  toastTimer = window.setTimeout(() => elements.toast.classList.remove("visible"), 3200);
}

function openSettings() {
  showSettingsHome();
  renderSettingsAccounts();
  elements.settingsModal.hidden = false;
}

function closeSettings() {
  elements.settingsModal.hidden = true;
  resetAccountForm();
}

function showSettingsHome() {
  elements.settingsHome.hidden = false;
  elements.purchaseAccountsSettings.hidden = true;
  elements.settingsBack.hidden = true;
  $("#settings-title").textContent = "Central de configurações";
}

function openPurchaseAccounts() {
  elements.settingsHome.hidden = true;
  elements.purchaseAccountsSettings.hidden = false;
  elements.settingsBack.hidden = false;
  $("#settings-title").textContent = "Contas de compra";
  elements.newAccountResponsible.value = selectedResponsible();
  elements.newAccountName.focus();
}

function renderSettingsAccounts() {
  $("#accounts-total").textContent = `${accounts.length} contas`;
  elements.settingsAccountsList.innerHTML = accounts.map((account) => `
    <div class="settings-account">
      <span class="settings-account-icon"><i data-lucide="user-round"></i></span>
      <span class="settings-account-copy">
        <strong>${escapeHtml(account.display_name)}</strong>
        <span>${escapeHtml(account.email)}</span>
      </span>
      <span class="settings-account-actions">
        <span class="responsible-tag">${escapeHtml(account.responsible)}</span>
        <button class="mini-icon-button" type="button" data-action="edit" data-key="${escapeHtml(account.key)}" title="Editar conta" aria-label="Editar ${escapeHtml(account.display_name)}">
          <i data-lucide="pencil"></i>
        </button>
        <button class="mini-icon-button danger" type="button" data-action="delete" data-key="${escapeHtml(account.key)}" title="Excluir conta" aria-label="Excluir ${escapeHtml(account.display_name)}">
          <i data-lucide="trash-2"></i>
        </button>
      </span>
    </div>
  `).join("") || '<div class="empty-state">Nenhuma conta cadastrada</div>';
  if (window.lucide) window.lucide.createIcons();
}

async function createAccount(event) {
  event.preventDefault();
  const body = {
    responsible: elements.newAccountResponsible.value,
    display_name: elements.newAccountName.value.trim(),
    email: elements.newAccountEmail.value.trim(),
  };
  try {
    const editKey = elements.editAccountKey.value;
    await request(editKey ? `/api/accounts/${encodeURIComponent(editKey)}` : "/api/accounts", {
      method: editKey ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    resetAccountForm();
    await loadAccounts();
    elements.responsible.value = body.responsible;
    populateAccountSelectors();
    elements.newAccountResponsible.value = body.responsible;
    showToast(editKey ? "Conta atualizada com sucesso." : "Conta adicionada com sucesso.");
  } catch (error) {
    showToast(error.message, true);
  }
}

function handleAccountAction(event) {
  const button = event.target.closest("[data-action]");
  if (!button) return;
  const account = accounts.find((item) => item.key === button.dataset.key);
  if (!account) return;
  if (button.dataset.action === "edit") {
    elements.editAccountKey.value = account.key;
    elements.newAccountResponsible.value = account.responsible;
    elements.newAccountName.value = account.display_name;
    elements.newAccountEmail.value = account.email;
    elements.accountFormTitle.textContent = "Editar conta";
    elements.accountSubmit.querySelector("span").textContent = "Salvar alterações";
    elements.cancelAccountEdit.hidden = false;
    elements.newAccountName.focus();
    return;
  }
  if (button.dataset.action === "delete") deleteAccount(account);
}

async function deleteAccount(account) {
  const confirmed = window.confirm(
    `Excluir a conta "${account.display_name}"?\n\nOs pedidos já salvos serão preservados.`
  );
  if (!confirmed) return;
  try {
    await request(`/api/accounts/${encodeURIComponent(account.key)}`, { method: "DELETE" });
    await loadAccounts();
    if (!accounts.some((item) => item.responsible === selectedResponsible())) {
      elements.responsible.value = responsibles[0] || "";
    }
    populateAccountSelectors();
    resetAccountForm();
    await refreshData();
    showToast("Conta excluída. O histórico de pedidos foi preservado.");
  } catch (error) {
    showToast(error.message, true);
  }
}

function resetAccountForm() {
  elements.accountForm.reset();
  elements.editAccountKey.value = "";
  elements.accountFormTitle.textContent = "Nova conta";
  elements.accountSubmit.querySelector("span").textContent = "Adicionar conta";
  elements.cancelAccountEdit.hidden = true;
  if (responsibles.includes(selectedResponsible())) {
    elements.newAccountResponsible.value = selectedResponsible();
  }
}
