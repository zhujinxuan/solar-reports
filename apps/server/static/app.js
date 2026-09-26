/* ============================================================
   光伏项目财务模型 — 前端逻辑（无构建步骤，原生 JS + 内联 SVG）
   数据源契约：
     GET  /api/schema                     → { domains: [DomainSchema] }
     POST /api/domains/compute {version, inputs?}  → { domains: [...含 items[].cells] }
     GET  /api/download/domains.xlsx?version=v2
   ============================================================ */
"use strict";

/* ---------- API ---------- */
const API = {
  schema: "api/schema",
  compute: "api/domains/compute",
  download: (version) => `api/download/domains.xlsx?version=${encodeURIComponent(version)}`,
};

async function fetchJSON(url, options) {
  const resp = await fetch(url, options);
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try {
      const body = await resp.json();
      if (body && body.detail) detail += `：${typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail)}`;
    } catch { /* 忽略非 JSON 响应体 */ }
    throw new Error(detail);
  }
  return resp.json();
}

/* ---------- 领域静态布局（9 个领域固定，几何位置硬编码；边由 schema 决定） ---------- */
const NODE_W = 150;
const NODE_H = 64;
const DOMAIN_LAYOUT = [
  { key: "params",    x: 30,   y: 168, layer: 0, fallbackLabel: "参数表",       sheet: "参数",     depends: [] },
  { key: "invest",    x: 210,  y: 88,  layer: 1, fallbackLabel: "投资计划",     sheet: "投资计划", depends: ["params"] },
  { key: "debt",      x: 210,  y: 248, layer: 1, fallbackLabel: "还贷",         sheet: "还贷",     depends: ["params", "invest"] },
  { key: "cost",      x: 390,  y: 168, layer: 2, fallbackLabel: "成本",         sheet: "成本",     depends: ["params", "invest", "debt"] },
  { key: "pnl",       x: 570,  y: 168, layer: 3, fallbackLabel: "损益表 (PnL)", sheet: "损益",     depends: ["cost", "debt"] },
  { key: "cashflow",  x: 750,  y: 88,  layer: 4, fallbackLabel: "现金流量",     sheet: "现金流量", depends: ["pnl", "invest", "debt"] },
  { key: "finplan",   x: 750,  y: 248, layer: 4, fallbackLabel: "财务计划",     sheet: "财务计划", depends: ["pnl", "debt"] },
  { key: "balance",   x: 930,  y: 168, layer: 5, fallbackLabel: "资产负债",     sheet: "资产负债", depends: ["cashflow", "finplan"] },
  { key: "valuation", x: 1110, y: 168, layer: 6, fallbackLabel: "估值结果",     sheet: "估值结果", depends: ["cashflow", "pnl", "balance"] },
];
const LAYER_CAPTIONS = ["参 数", "投 资 / 融 资", "成 本", "损 益", "现 金 / 计 划", "负 债 表", "估 值"];

/* ---------- 全局状态 ---------- */
const state = {
  version: "v2",
  schema: null,          // { domains: [...] }
  computed: null,        // { domains: [...含 cells] }
  schemaPromise: null,
  computePromise: null,
  selectedDomain: null,  // 当前选中的领域 key
  zoom: { scale: 1, cx: 645, cy: 200 },
};

const SVG_BASE = { w: 1290, h: 400 };

/* ---------- 工具 ---------- */
function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null) continue;
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k === "html") node.innerHTML = v;
      else node.setAttribute(k, v);
    }
  }
  for (const child of children) {
    if (child == null) continue;
    if (Array.isArray(child)) { for (const c of child) { if (c != null) node.append(c); } continue; }
    node.append(child);
  }
  return node;
}

/** Excel 列字母 → 序号（A=1, Z=26, AA=27 …） */
function colToIndex(letters) {
  let n = 0;
  for (const ch of letters) n = n * 26 + (ch.charCodeAt(0) - 64);
  return n;
}

function isErrValue(v) {
  return v != null && typeof v === "object" && typeof v.error === "string";
}

function formatValue(v) {
  if (v == null) return "—";
  if (isErrValue(v)) return v.error;
  if (typeof v === "boolean") return v ? "是" : "否";
  if (typeof v === "number") {
    if (!Number.isFinite(v)) return String(v);
    if (Number.isInteger(v) && Math.abs(v) < 1e15) return v.toLocaleString("zh-CN");
    return v.toLocaleString("zh-CN", { maximumFractionDigits: 4 });
  }
  return String(v);
}

function formatKPI(v) {
  if (typeof v !== "number" || !Number.isFinite(v)) return formatValue(v);
  const abs = Math.abs(v);
  const digits = abs >= 100 ? 0 : abs >= 1 ? 2 : 4;
  return v.toLocaleString("zh-CN", { maximumFractionDigits: digits });
}

/** 加载/错误状态渲染。retry 为可点击的重试回调。 */
function showLoading(container, text) {
  container.replaceChildren(
    el("div", { class: "loading", role: "status" },
      el("span", { class: "spinner", "aria-hidden": "true" }),
      el("span", { text: text || "加载中，请稍候…" }))
  );
}

function showError(container, message, retry) {
  const box = el("div", { class: "error-box", role: "alert" },
    el("span", { class: "error-text", text: "出错了" }),
    el("span", { class: "error-detail", text: message }),
  );
  if (retry) {
    const btn = el("button", { type: "button", class: "btn", text: "重试" });
    btn.addEventListener("click", retry);
    box.append(btn);
  }
  container.replaceChildren(box);
}

function clearStatus(container) { container.replaceChildren(); }

/* ---------- 数据加载（带缓存） ---------- */
function loadSchema() {
  if (!state.schemaPromise) {
    state.schemaPromise = fetchJSON(API.schema).then((data) => {
      state.schema = data;
      return data;
    }).catch((err) => { state.schemaPromise = null; throw err; });
  }
  return state.schemaPromise;
}

/** 读取参数表单 → ModelInputs 覆盖字段（仅收录有限数值；空/非法输入跳过，服务端用默认值）。 */
function collectParamInputs() {
  const inputs = {};
  for (const input of document.querySelectorAll('#param-form input[name]')) {
    const v = Number.parseFloat(input.value);
    if (Number.isFinite(v)) inputs[input.name] = v;
  }
  return inputs;
}

function runCompute() {
  if (!state.computePromise) {
    state.computePromise = fetchJSON(API.compute, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version: state.version, inputs: collectParamInputs() }),
    }).then((data) => {
      state.computed = data;
      return data;
    }).catch((err) => { state.computePromise = null; throw err; });
  }
  return state.computePromise;
}

function computedDomain(key) {
  if (!state.computed) return null;
  return state.computed.domains.find((d) => d.key === key) || null;
}

function schemaDomain(key) {
  if (!state.schema) return null;
  return state.schema.domains.find((d) => d.key === key) || null;
}

/* ============================================================
   标签页切换
   ============================================================ */
function initTabs() {
  const tabs = Array.from(document.querySelectorAll('[role="tab"]'));
  function activate(tab, focusPanel) {
    for (const t of tabs) {
      const selected = t === tab;
      t.setAttribute("aria-selected", String(selected));
      t.tabIndex = selected ? 0 : -1;
      const panel = document.getElementById(t.getAttribute("aria-controls"));
      panel.hidden = !selected;
    }
    if (tab.id === "tab-flow") onFlowTabShown();
    if (focusPanel) {
      document.getElementById(tab.getAttribute("aria-controls")).focus({ preventScroll: true });
    }
  }
  for (const tab of tabs) {
    tab.addEventListener("click", () => activate(tab, false));
  }
  // 方向键在标签间移动（WAI-ARIA tab 模式）
  const tablist = document.querySelector('[role="tablist"]');
  tablist.addEventListener("keydown", (e) => {
    const i = tabs.indexOf(document.activeElement);
    if (i < 0) return;
    let next = null;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") next = tabs[(i + 1) % tabs.length];
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") next = tabs[(i - 1 + tabs.length) % tabs.length];
    else if (e.key === "Home") next = tabs[0];
    else if (e.key === "End") next = tabs[tabs.length - 1];
    if (next) { e.preventDefault(); next.focus(); activate(next, false); }
  });
}

/* ============================================================
   Tab 1：计算
   ============================================================ */
function initComputeTab() {
  const form = document.getElementById("param-form");
  const status = document.getElementById("compute-status");
  const btn = document.getElementById("run-compute");

  async function execute() {
    btn.disabled = true;
    btn.textContent = "计算中…";
    showLoading(status, "正在执行服务端 v2 全模型计算，通常需要数秒…");
    try {
      const data = await runCompute();
      clearStatus(status);
      renderKPIs(data);
      renderDomainTables(data);
    } catch (err) {
      showError(status, `计算请求失败（${err.message}）。请确认服务端已启动后重试。`, execute);
    } finally {
      btn.disabled = false;
      btn.textContent = "运行计算";
    }
  }

  // 参数一旦被修改，缓存的计算结果即失效（流程页/领域表随当前参数重新计算）
  form.addEventListener("input", () => {
    state.computePromise = null;
    state.computed = null;
  });

  form.addEventListener("submit", (e) => { e.preventDefault(); execute(); });
}

/* KPI：显式绑定（领域 key + item key + 单位语义），杜绝正则误配。
   取值规则：按列序取首个数值单元（标量项即其本身；年序列项为首年，note 标注）。
   unitHint:
     "number"     —— 普通数值，按 item.unit 显示；
     "fraction"   —— 小数为比例（0.0956），显示为 9.56%（实测 cashflow:equity_irr H61=0.0956）；
     "percent100" —— 工作簿已是 ×100 写法（6.129），直接加 %（实测 cashflow:project_irr I29=6.129）。 */
const KPI_BINDINGS = [
  { title: "总投资",           domain: "invest",    itemKey: "total_investment", unitHint: "number", agg: "sum", note: "各期合计" },
  { title: "年发电量",         domain: "pnl",       itemKey: "power_generation", unitHint: "number", note: "首年" },
  { title: "销售收入",         domain: "pnl",       itemKey: "sales_revenue",    unitHint: "number", note: "首年" },
  { title: "净利润",           domain: "pnl",       itemKey: "net_profit",       unitHint: "number", note: "首年" },
  { title: "资本金IRR",        domain: "cashflow",  itemKey: "equity_irr",       unitHint: "fraction" },
  { title: "股权估值（收益法）", domain: "valuation", itemKey: "val_sale_price_inc", unitHint: "number", note: "首年" },
];

function firstNumericCell(item) {
  if (!item || !Array.isArray(item.cells)) return null;
  const cells = [...item.cells].sort((a, b) => colToIndex(a.col) - colToIndex(b.col) || a.row - b.row);
  for (const c of cells) {
    if (typeof c.value === "number" && Number.isFinite(c.value)) return c.value;
  }
  return null;
}

/* 期序列/年序列合计：总投资等头部指标取各期之和（C 列合计语义），
   而非首个单元（首期为建设期，常为 0）。 */
function sumNumericCells(item) {
  if (!item || !Array.isArray(item.cells)) return null;
  let total = 0;
  let seen = false;
  for (const c of item.cells) {
    if (typeof c.value === "number" && Number.isFinite(c.value)) {
      total += c.value;
      seen = true;
    }
  }
  return seen ? total : null;
}

function bindKPIItem(data, binding) {
  const domain = data.domains.find((d) => d.key === binding.domain);
  if (!domain) return null;
  const item = (domain.items || []).find((it) => it.key === binding.itemKey);
  if (!item) return null;
  const value = binding.agg === "sum" ? sumNumericCells(item) : firstNumericCell(item);
  return value == null ? null : { item, value };
}

/** 按 unitHint 渲染 KPI 数值（含单位）。 */
function formatKPIWithHint(value, unitHint, unit) {
  if (unitHint === "fraction") {
    return { text: (value * 100).toLocaleString("zh-CN", { maximumFractionDigits: 2 }), unit: "%" };
  }
  if (unitHint === "percent100") {
    return { text: value.toLocaleString("zh-CN", { maximumFractionDigits: 2 }), unit: "%" };
  }
  return { text: formatKPI(value), unit: unit && unit !== "-" ? unit : "" };
}

function renderKPIs(data) {
  const area = document.getElementById("kpi-area");
  const grid = document.getElementById("kpi-grid");
  grid.replaceChildren();
  let found = 0;
  for (const binding of KPI_BINDINGS) {
    const hit = bindKPIItem(data, binding);
    if (!hit) continue;
    found += 1;
    const { item, value } = hit;
    const display = formatKPIWithHint(value, binding.unitHint, item.unit);
    grid.append(
      el("div", { class: "kpi-card" },
        el("div", { class: "kpi-label", text: binding.title }),
        el("div", { class: "kpi-value" },
          document.createTextNode(display.text),
          display.unit ? el("span", { class: "kpi-unit", text: display.unit }) : null),
        el("div", { class: "kpi-note" },
          document.createTextNode(`${item.label} · `),
          el("code", { text: `${binding.domain}:${item.key}` }),
          binding.note ? document.createTextNode(` · ${binding.note}`) : null))
    );
  }
  if (found === 0) {
    grid.append(el("p", { class: "field-note", text: "未在结果中匹配到头部指标项，请查看下方分领域明细。" }));
  }
  area.hidden = false;
}

/* 分领域紧凑表：项目 | 单位 | 首年值 | 合计值（若有 AF 合计列则单独列出） */
function renderDomainTables(data) {
  const section = document.getElementById("domain-tables");
  const body = document.getElementById("domain-tables-body");
  body.replaceChildren();

  for (const domain of data.domains) {
    const items = domain.items || [];
    const rows = items.map((item) => {
      const byCol = new Map();
      for (const c of item.cells || []) byCol.set(c.col, c.value);
      const first = firstNumericCell(item);
      const total = byCol.get("AF");
      return { item, first, total };
    });

    const hasTotal = rows.some((r) => r.total != null && !isErrValue(r.total));
    const thead = el("thead", null,
      el("tr", null,
        el("th", { scope: "col", text: "项目" }),
        el("th", { scope: "col", text: "单位" }),
        el("th", { scope: "col", class: "num", text: "首个数值" }),
        hasTotal ? el("th", { scope: "col", class: "num", text: "合计" }) : null));

    const tbody = el("tbody", null,
      rows.map(({ item, first, total }) =>
        el("tr", null,
          el("td", null, el("span", { class: "item-label", text: item.label }), el("code", { class: "item-key", text: item.key })),
          el("td", { text: item.unit || "-" }),
          el("td", { class: "num", text: first != null ? formatValue(first) : "—" }),
          hasTotal ? el("td", { class: "num", text: total != null ? formatValue(total) : "—" }) : null)));

    body.append(
      el("article", { class: "domain-block" },
        el("header", null,
          el("h3", { text: domain.label }),
          el("span", { class: "sheet-tag", text: `工作表：${domain.sheet} · ${items.length} 项` })),
        el("div", { class: "table-scroll" },
          el("table", { class: "data" }, thead, tbody))));
  }
  section.hidden = false;
}

/* ============================================================
   Tab 2：流程与公式
   ============================================================ */
const SVG_NS = "http://www.w3.org/2000/svg";
let flowInitialized = false;

function svgEl(tag, attrs, ...children) {
  const node = document.createElementNS(SVG_NS, tag);
  if (attrs) for (const [k, v] of Object.entries(attrs)) { if (v != null) node.setAttribute(k, v); }
  for (const child of children) if (child != null) node.append(child);
  return node;
}

function svgText(attrs, text) {
  const t = svgEl("text", attrs);
  t.textContent = text;
  return t;
}

/** 边的来源：优先使用 /api/schema 的 depends_on，缺失时用硬编码兜底。 */
function domainDeps(key) {
  const sd = schemaDomain(key);
  if (sd && Array.isArray(sd.depends_on) && sd.depends_on.length) return [...sd.depends_on];
  const layout = DOMAIN_LAYOUT.find((d) => d.key === key);
  return layout ? layout.depends : [];
}

function domainLabel(key) {
  const sd = schemaDomain(key);
  if (sd) return sd.label;
  const layout = DOMAIN_LAYOUT.find((d) => d.key === key);
  return layout ? layout.fallbackLabel : key;
}

function domainSheet(key) {
  const sd = schemaDomain(key);
  if (sd) return sd.sheet;
  const layout = DOMAIN_LAYOUT.find((d) => d.key === key);
  return layout ? layout.sheet : "";
}

function nodeCenter(layout) { return { x: layout.x + NODE_W / 2, y: layout.y + NODE_H / 2 }; }

function edgePath(fromLayout, toLayout) {
  const x1 = fromLayout.x + NODE_W;
  const y1 = fromLayout.y + NODE_H / 2;
  const x2 = toLayout.x;
  const y2 = toLayout.y + NODE_H / 2;
  const dx = Math.max(24, (x2 - x1) / 2);
  return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
}

function renderDiagram() {
  const svg = document.getElementById("diagram");
  svg.replaceChildren();

  // 箭头标记
  const defs = svgEl("defs");
  const marker = svgEl("marker", {
    id: "arrow", viewBox: "0 0 10 10", refX: "9", refY: "5",
    markerWidth: "7", markerHeight: "7", orient: "auto-start-reverse",
  });
  marker.append(svgEl("path", { d: "M 0 0 L 10 5 L 0 10 z", fill: "#b9b4a9" }));
  defs.append(marker);
  const markerActive = svgEl("marker", {
    id: "arrow-active", viewBox: "0 0 10 10", refX: "9", refY: "5",
    markerWidth: "7", markerHeight: "7", orient: "auto-start-reverse",
  });
  markerActive.append(svgEl("path", { d: "M 0 0 L 10 5 L 0 10 z", fill: "#0f766e" }));
  defs.append(markerActive);
  svg.append(defs);

  // 层标题
  for (let layer = 0; layer < LAYER_CAPTIONS.length; layer++) {
    const layouts = DOMAIN_LAYOUT.filter((d) => d.layer === layer);
    if (!layouts.length) continue;
    const cx = layouts.reduce((s, d) => s + nodeCenter(d).x, 0) / layouts.length;
    svg.append(svgText({ class: "layer-caption", x: cx, y: 22, "text-anchor": "middle", "aria-hidden": "true" }, LAYER_CAPTIONS[layer]));
  }

  // 边（先画，置于节点下层）
  const edgesGroup = svgEl("g", { "aria-hidden": "true" });
  for (const to of DOMAIN_LAYOUT) {
    for (const depKey of domainDeps(to.key)) {
      const from = DOMAIN_LAYOUT.find((d) => d.key === depKey);
      if (!from) continue;
      const path = svgEl("path", {
        class: "edge", d: edgePath(from, to),
        "marker-end": "url(#arrow)",
        "data-from": from.key, "data-to": to.key,
      });
      const title = svgEl("title");
      title.textContent = `${domainLabel(from.key)} → ${domainLabel(to.key)}`;
      path.append(title);
      edgesGroup.append(path);
    }
  }
  svg.append(edgesGroup);

  // 节点
  for (const layout of DOMAIN_LAYOUT) {
    const g = svgEl("g", {
      class: "node",
      tabindex: "0",
      role: "button",
      "data-key": layout.key,
      "aria-label": `领域：${domainLabel(layout.key)}（工作表：${domainSheet(layout.key)}）。按 Enter 或空格查看公式明细。`,
      "aria-pressed": state.selectedDomain === layout.key ? "true" : "false",
    });
    if (state.selectedDomain === layout.key) g.classList.add("selected");
    g.append(svgEl("rect", { class: "body", x: layout.x, y: layout.y, width: NODE_W, height: NODE_H, rx: 6 }));
    const cx = layout.x + NODE_W / 2;
    g.append(svgText({ class: "node-label", x: cx, y: layout.y + 24, "text-anchor": "middle" }, domainLabel(layout.key)));
    g.append(svgText({ class: "node-key", x: cx, y: layout.y + 40, "text-anchor": "middle" }, layout.key));
    g.append(svgText({ class: "node-sheet", x: cx, y: layout.y + 54, "text-anchor": "middle" }, `工作表：${domainSheet(layout.key)}`));

    g.addEventListener("click", () => selectDomain(layout.key));
    g.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); selectDomain(layout.key); }
    });
    g.addEventListener("mouseenter", () => highlightNeighbors(layout.key));
    g.addEventListener("mouseleave", clearHighlight);
    g.addEventListener("focus", () => highlightNeighbors(layout.key));
    g.addEventListener("blur", clearHighlight);
    svg.append(g);
  }
}

/** 悬停/聚焦：高亮直接上下游，其余降透明度。 */
function highlightNeighbors(key) {
  const ups = new Set(domainDeps(key));
  const downs = new Set(DOMAIN_LAYOUT.filter((d) => domainDeps(d.key).includes(key)).map((d) => d.key));
  const svg = document.getElementById("diagram");
  for (const node of svg.querySelectorAll(".node")) {
    const k = node.getAttribute("data-key");
    node.classList.remove("up", "down", "dim");
    if (k === key) continue;
    if (ups.has(k)) node.classList.add("up");
    else if (downs.has(k)) node.classList.add("down");
    else node.classList.add("dim");
  }
  for (const edge of svg.querySelectorAll(".edge")) {
    const from = edge.getAttribute("data-from");
    const to = edge.getAttribute("data-to");
    edge.classList.remove("active", "dim");
    if (from === key || to === key) {
      edge.classList.add("active");
      edge.setAttribute("marker-end", "url(#arrow-active)");
    } else {
      edge.classList.add("dim");
      edge.setAttribute("marker-end", "url(#arrow)");
    }
  }
}

function clearHighlight() {
  const svg = document.getElementById("diagram");
  for (const node of svg.querySelectorAll(".node")) node.classList.remove("up", "down", "dim");
  for (const edge of svg.querySelectorAll(".edge")) {
    edge.classList.remove("active", "dim");
    edge.setAttribute("marker-end", "url(#arrow)");
  }
}

/* ---------- 详情面板 ---------- */
async function selectDomain(key) {
  state.selectedDomain = key;
  // 同步节点选中样式
  const svg = document.getElementById("diagram");
  for (const node of svg.querySelectorAll(".node")) {
    const selected = node.getAttribute("data-key") === key;
    node.classList.toggle("selected", selected);
    node.setAttribute("aria-pressed", String(selected));
  }
  renderPanel(key);
  // 数值惰性加载：选中后触发一次 compute（全局缓存）
  if (!state.computed) {
    const body = document.querySelector("#detail-panel .panel-body");
    if (body) showLoading(body, "正在加载该领域的计算数值…");
    try {
      await runCompute();
    } catch (err) {
      if (body) showError(body, `数值加载失败（${err.message}）。公式与项目结构不受影响。`, () => selectDomain(key));
      return;
    }
    if (state.selectedDomain === key) renderPanel(key); // 用数值重绘
  }
}

function renderPanel(key) {
  const panel = document.getElementById("detail-panel");
  const sd = schemaDomain(key);
  const cd = computedDomain(key);
  const layout = DOMAIN_LAYOUT.find((d) => d.key === key);

  const label = domainLabel(key);
  const sheet = domainSheet(key);
  const items = sd ? sd.items : [];
  const computedItems = new Map((cd ? cd.items : []).map((it) => [it.key, it]));

  const closeBtn = el("button", { type: "button", class: "btn", text: "关闭", "aria-label": "关闭详情面板" });
  closeBtn.addEventListener("click", () => {
    state.selectedDomain = null;
    renderDiagram();
    panel.replaceChildren(el("div", { class: "panel-empty" },
      el("p", { text: "选择左侧流程图中的领域节点，查看该领域的项目、公式与逐年数值。" })));
  });

  const header = el("header", null,
    el("div", null,
      el("h3", { text: label }),
      el("div", { class: "panel-meta" },
        document.createTextNode(`工作表：${sheet} · 领域键 `),
        el("code", { text: key }))),
    el("div", { class: "panel-actions" },
      el("a", { class: "btn btn-primary", href: API.download(state.version), download: "", text: "下载 Excel" }),
      closeBtn));

  const deps = domainDeps(key);
  const depLine = el("div", { class: "dep-line" },
    document.createTextNode(deps.length
      ? `上游依赖：${deps.map((d) => domainLabel(d)).join("、")}`
      : "上游依赖：无（管道起点）"));

  // 明细表：项目 | 公式 | 单位 | 各列数值
  const allCols = new Set();
  for (const it of computedItems.values()) for (const c of it.cells || []) allCols.add(c.col);
  const cols = [...allCols].sort((a, b) => colToIndex(a) - colToIndex(b));

  const thead = el("thead", null,
    el("tr", null,
      el("th", { scope: "col", text: "项目" }),
      el("th", { scope: "col", text: "公式" }),
      el("th", { scope: "col", text: "单位" }),
      cols.map((c) => el("th", { scope: "col", class: "num", text: c }))));

  const tbody = el("tbody");
  if (!items.length) {
    tbody.append(el("tr", null, el("td", { colspan: String(3 + cols.length), text: "该领域的计算模式（Schema）尚未提供。" })));
  }
  for (const item of items) {
    const ci = computedItems.get(item.key);
    const byCol = new Map((ci ? ci.cells : []).map((c) => [c.col, c.value]));
    const isYearRow = /year|年份/.test(item.key) || item.label === "年份";
    const tr = el("tr", isYearRow ? { class: "year-row" } : null,
      el("td", null,
        el("span", { class: "item-label", text: item.label }),
        el("code", { class: "item-key", text: item.key })),
      el("td", { class: "formula", text: item.formula }),
      el("td", { text: item.unit || "-" }),
      cols.map((c) => {
        const v = byCol.get(c);
        const isErr = isErrValue(v);
        // 年份行不做千分位分组（显示 2021 而非 2,021）
        const text = v === undefined ? "" : (isYearRow && typeof v === "number" ? String(v) : formatValue(v));
        return el("td", { class: isErr ? "cell-err" : "num", text });
      }));
    tbody.append(tr);
  }

  const bodyEl = el("div", { class: "panel-body" },
    el("div", { class: "table-scroll" },
      el("table", { class: "data" }, thead, tbody)));

  panel.replaceChildren(header, depLine, bodyEl);
}

/* ---------- 缩放 ---------- */
function applyZoom() {
  const svg = document.getElementById("diagram");
  const { scale, cx, cy } = state.zoom;
  const w = SVG_BASE.w / scale;
  const h = SVG_BASE.h / scale;
  const x = Math.min(Math.max(cx - w / 2, 0), SVG_BASE.w - w);
  const y = Math.min(Math.max(cy - h / 2, 0), SVG_BASE.h - h);
  svg.setAttribute("viewBox", `${x} ${y} ${w} ${h}`);
}

function initZoom() {
  document.getElementById("zoom-in").addEventListener("click", () => {
    state.zoom.scale = Math.min(state.zoom.scale * 1.25, 4);
    applyZoom();
  });
  document.getElementById("zoom-out").addEventListener("click", () => {
    state.zoom.scale = Math.max(state.zoom.scale / 1.25, 1);
    applyZoom();
  });
  document.getElementById("zoom-reset").addEventListener("click", () => {
    state.zoom = { scale: 1, cx: SVG_BASE.w / 2, cy: SVG_BASE.h / 2 };
    applyZoom();
  });
}

/* ---------- 流程页首次展示：加载 schema 并渲染图 ---------- */
function onFlowTabShown() {
  if (flowInitialized) return;
  const status = document.getElementById("flow-status");

  async function load() {
    showLoading(status, "正在加载领域计算模式（Schema）…");
    try {
      await loadSchema();
      clearStatus(status);
    } catch (err) {
      // schema 不可用：使用内置兜底结构渲染，同时给出可重试的错误提示
      showError(status, `Schema 加载失败（${err.message}），已按内置结构渲染流程图；领域明细可能不完整。`, load);
    }
    flowInitialized = true;
    renderDiagram();
    initZoom();
    document.getElementById("download-excel").href = API.download(state.version);
  }

  load();
}

/* ---------- 启动 ---------- */
document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  initComputeTab();
});
