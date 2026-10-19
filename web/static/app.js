// 无构建步骤；所有数值一律来自 API，前端不做任何计算。
const $ = (id) => document.getElementById(id);

async function loadCatalog() {
  const r = await fetch("/api/catalog");
  const body = await r.json();
  HP.catalog = body.presets;
  // 指标表的中文标签与类型：**只从服务端取**，前端不另写一份（见 showResult 的说明）
  HP.metricMeta = body.metric_meta;
  const engines = {};
  for (const p of HP.catalog) engines[p.engine] = (engines[p.engine] || 0) + 1;
  $("engine-summary").textContent = Object.entries(engines)
    .map(([k, v]) => `${k} ${v}`).join(" · ") + ` · 共 ${HP.catalog.length}`;
  renderCatalog("");
}

// ── 状态 ──
// 编辑值与"预设本身"分开存：筛选重建 DOM 时不丢用户的改动（见审计 P0-A）。
const HP = { catalog: [], selected: null, runId: null, poll: null, trades: [],
             tradeIdx: -1,       // 当前正在看第几笔（-1 = 还没选）
             startedAt: null, logOffset: 0, equity: null, configs: [],
             metricMeta: {},     // 规范指标的 {label, kind}，来自 /api/catalog
             edits: new Map(),   // "engine/preset" -> {未提交的键: 值}
             history: [] };      // 运行历史（见审计 P1-E）

const presetKey = (p) => `${p.engine}/${p.preset}`;

// 按元数据的 type 渲染控件（见审计 P0-D）。
// Task 1 建好的 type/range/choices/unit/label 就是为这里准备的——之前完全没用上。
function controlFor(key, meta, value, pkey) {
  const wrap = document.createElement("label");
  const unit = meta.unit ? `（${meta.unit}）` : "";
  wrap.appendChild(document.createTextNode(`${meta.label || key}${unit}`));
  let input;
  const type = meta.type;
  if (type === "bool") {
    input = document.createElement("input");
    input.type = "checkbox";
    input.checked = Boolean(value);
  } else if ((type === "int" || type === "float") && typeof value !== "object") {
    input = document.createElement("input");
    input.type = "number";
    input.step = type === "int" ? "1" : "any";
    if (Array.isArray(meta.range)) { input.min = meta.range[0]; input.max = meta.range[1]; }
    input.value = value;
  } else if (type === "str" && Array.isArray(meta.choices)) {
    input = document.createElement("select");
    for (const c of meta.choices) {
      const o = document.createElement("option");
      o.value = c; o.textContent = c;
      if (String(value) === String(c)) o.selected = true;
      input.appendChild(o);
    }
  } else {
    // list / dict（如 signal / regime / periods）：文本编辑 JSON，保留原样展示
    input = document.createElement("input");
    input.value = JSON.stringify(value);
  }
  input.dataset.key = key;
  input.addEventListener("change", () => {
    let v;
    if (input.type === "checkbox") v = input.checked;
    else if (input.type === "number") v = input.step === "1" ? parseInt(input.value, 10) : parseFloat(input.value);
    else if (input.tagName === "SELECT") v = input.value;
    else { try { v = JSON.parse(input.value); } catch { alert(`参数 ${key} 不是合法 JSON`); return; } }
    const cur = HP.edits.get(pkey) || {};
    cur[key] = v;
    HP.edits.set(pkey, cur);
    renderCatalog($("filter").value);   // 重渲染以更新"已修改"标记
  });
  wrap.appendChild(input);
  return wrap;
}

function renderCatalog(filter) {
  const box = $("preset-list");
  // 记住展开状态，重建后恢复——否则筛选会把用户正看的那个折叠回去
  const open = new Set([...box.querySelectorAll("details[open]")].map((d) => d.dataset.key));
  box.innerHTML = "";
  let shownEngine = null;
  for (const p of HP.catalog) {
    // 筛选同时匹配**引擎名**——否则打 "chase" 什么也筛不出来，而用户往往先想的是引擎
    if (filter) {
      const f = filter.toLowerCase();
      if (!p.preset.toLowerCase().includes(f) && !p.engine.toLowerCase().includes(f)) continue;
    }
    // 引擎分组表头：101 项平铺（其中 short_reversal 占 75）时，没有表头等于让用户自己数
    if (p.engine !== shownEngine) {
      shownEngine = p.engine;
      const h = document.createElement("div");
      h.className = "engine-head";
      h.textContent = `${p.engine}（${HP.catalog.filter((x) => x.engine === p.engine).length}）`;
      box.appendChild(h);
    }
    const pkey = presetKey(p);
    const edits = HP.edits.get(pkey) || {};
    const det = document.createElement("details");
    det.className = "preset";
    det.dataset.key = pkey;
    if (open.has(pkey)) det.open = true;
    const n = p.declared_n_comparisons ?? "—";
    const changedN = Object.keys(edits).length;
    det.innerHTML = `<summary><b>${p.preset}</b>
        <span class="hint">${p.engine} · n_comparisons=${n} + 人工 ${p.manual_trials} 次`
      + (changedN ? ` · <b class="mod">已改 ${changedN}</b>` : "")
      + `</span></summary>`;
    const grid = document.createElement("div");
    grid.className = "params";
    for (const [k, v] of Object.entries(p.tunable)) {
      const el = document.createElement("div");
      el.className = "p" + (k in edits ? " mod" : "");
      el.title = (p.metadata[k] || {}).help || "";
      el.appendChild(controlFor(k, p.metadata[k] || {}, k in edits ? edits[k] : v, pkey));
      grid.appendChild(el);
    }
    for (const [k, v] of Object.entries(p.declarations)) {
      const el = document.createElement("div");
      el.className = "p decl";
      el.textContent = `${k} = ${JSON.stringify(v)}`;
      grid.appendChild(el);
    }
    const reset = document.createElement("button");
    reset.type = "button";
    reset.textContent = "恢复默认";
    reset.disabled = !changedN;
    reset.addEventListener("click", () => { HP.edits.delete(pkey); renderCatalog($("filter").value); });
    grid.appendChild(reset);
    det.appendChild(grid);
    det.addEventListener("toggle", () => {
      if (det.open) HP.selected = p;
      else if (HP.selected === p) HP.selected = null;
    });
    box.appendChild(det);
  }
}

// 只提交**真正改了的**键（见审计 P0-C）。
// 之前把表单里每个字段都塞进 overrides，于是原样重跑也被记成一次 trial，
// 且 param_diff 是整份参数、看不出改了什么。§5 管的是"试过多少**配置**"。
function changedOverrides(preset) {
  const edits = HP.edits.get(presetKey(preset)) || {};
  const out = {};
  for (const [k, v] of Object.entries(edits)) {
    if (JSON.stringify(v) !== JSON.stringify(preset.tunable[k])) out[k] = v;
  }
  return out;
}

async function startRun() {
  if (!HP.selected) { alert("请先展开一个预设"); return; }
  const body = {
    engine: HP.selected.engine,
    preset: HP.selected.preset,
    overrides: changedOverrides(HP.selected),
    start: $("start").value,
    end: $("end").value,
    mode: $("mode").value,
  };
  const r = await fetch("/api/runs", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) { $("run-status").textContent = `提交失败：${(await r.json()).detail}`; return; }
  HP.runId = (await r.json()).run_id;
  HP.startedAt = Date.now();
  HP.logOffset = 0;
  $("log").textContent = "";
  $("log-wrap").open = true;
  $("run").disabled = true;
  $("result").hidden = true;
  pollRun();
}

function pollRun() {
  clearInterval(HP.poll);
  $("cancel").disabled = false;
  HP.poll = setInterval(async () => {
    const r = await fetch(`/api/runs/${HP.runId}`);
    const j = await r.json();
    await pollLog();
    // 单 worker：排队位置是用户能看到的唯一等待依据；并全程显示已耗时
    const waited = HP.startedAt
      ? `　已等 ${Math.round((Date.now() - HP.startedAt) / 1000)}s` : "";
    const pos = j.status === "queued" && j.queue_position !== null
      ? `　前面还有 ${j.queue_position} 个` : "";
    $("run-status").textContent =
      `#${HP.runId} ${j.status}${pos}${waited}` + (j.error ? ` — ${j.error}` : "");
    if (j.status === "done") {
      clearInterval(HP.poll); $("run").disabled = false; $("cancel").disabled = true;
      await showResult(j);
      await loadHistory();                    // 新结果立刻出现在历史里
    }
    if (j.status === "failed" || j.status === "cancelled") {
      clearInterval(HP.poll); $("run").disabled = false; $("cancel").disabled = true;
      await loadHistory();                    // 被取消的运行也要出现在历史里（它是一次试验）
    }
  }, 1000);
}

async function cancelRun() {
  if (!HP.runId) return;
  $("cancel").disabled = true;
  const r = await fetch(`/api/runs/${HP.runId}/cancel`, { method: "POST" });
  if (!r.ok) { $("run-status").textContent = `取消失败：${(await r.json()).detail}`; return; }
  const j = await r.json();
  $("run-status").textContent = `#${HP.runId} ${j.status}（已请求取消）`;
}

async function pollLog() {
  if (!HP.runId) return true;
  const r = await fetch(`/api/runs/${HP.runId}/log?offset=${HP.logOffset}`);
  if (!r.ok) return true;
  const d = await r.json();
  if (d.text) {
    const el = $("log");
    el.textContent += d.text;
    el.scrollTop = el.scrollHeight;      // 跟着最新一行走
    HP.logOffset = d.offset;
  }
  return d.done;
}

async function showResult(job) {
  $("result").hidden = false;
  // 先清掉上一轮的横幅——否则每跑一次 preview 就多叠一条（审计 K）
  $("result").querySelectorAll(".warn").forEach((el) => el.remove());
  if (job.mode === "preview") {
    const w = document.createElement("div");
    w.className = "warn";
    // textContent 不解析 markdown，别在文案里写 ** 星号
    w.textContent = "preview 模式（仅最近 90 天）：这些数字不可与 full 模式比较，不得作为业绩依据。";
    $("metrics").before(w);
  }
  // 指标表：标签与类型都来自 `/api/catalog` 的 `metric_meta`（**单一来源**）——
  // 前端不得另写一份标签表，两份必然漂移，而漂移的表现是"某一格格式不对"，没人会注意到。
  //
  // 三条曾在此处出错的规则：
  //  ① 原写法 `.filter(([, v]) => typeof v === "number")` 会把 `None` **整个丢掉** ——
  //     于是"这个引擎不产出年化"与"平台忘了算"在界面上**长得一样**。
  //     §0 的规则是**如实表示缺失**，故渲染成 "—" 并保留那个格子。
  //  ② 原写法对指标一律固定四位小数（一把梭），会把 `trades_count` 渲染成 `74.0000`、
  //     `final_capital` 渲染成 `1500000.0000`。**单位是数据的一部分**，按 `kind` 分别格式化。
  //  ③ 键的顺序取自 `metric_meta`（服务端 `CANONICAL_KEYS` 的顺序），前端不再自己排。
  const meta = HP.metricMeta || {};
  const order = Object.keys(meta);
  $("metrics").innerHTML = order.map((k) => {
    const m = meta[k];
    const v = (job.metrics || {})[k];
    const cell = fmtMetric(v, m.kind);
    return `<div class="m${cell === "—" ? " absent" : ""}">${m.label}<br><b>${cell}</b></div>`;
  }).join("");
  await loadTrades();
  await loadEquity();
  await loadDailyTables();
}

// 按**单位**渲染，而不是一把梭套固定小数位。
// `kind` 来自服务端的 METRIC_KINDS；未知 kind 退化成 ratio，
// 这样"加了指标却忘了声明类型"表现为**数字格式有点怪**，而不是整页崩掉。
function fmtMetric(v, kind) {
  if (v === null || v === undefined) return "—";       // 缺失：如实显示，不是 0
  if (kind === "pct") return (v * 100).toFixed(2) + "%";
  if (kind === "money") return v.toLocaleString("zh-CN", { maximumFractionDigits: 0 });
  if (kind === "count") return String(v);
  if (kind === "days") return v.toFixed(1) + " 天";
  return v.toFixed(2);                                  // ratio（夏普、盈亏比）
}

async function loadDailyTables() {
  // 每日收益：复用 loadEquity 已取到的那一份。
  // `/api/runs/{id}/equity` 会真的查库计算基准序列，拉两次就是把同一份计算做两遍。
  if (HP.equity) {
    const rows = HP.equity.daily_returns || [];
    $("dr-count").textContent = rows.length;
    $("daily-returns").querySelector("thead").innerHTML = "<tr><th>日期</th><th>当日收益</th></tr>";
    $("daily-returns").querySelector("tbody").innerHTML = rows.map((r) =>
      `<tr><td>${r.date}</td><td>${(r.value * 100).toFixed(3)}%</td></tr>`).join("");
  }
  // 每日持仓
  const pr = await fetch(`/api/runs/${HP.runId}/positions`);
  if (!pr.ok) return;
  const p = await pr.json();
  $("positions").querySelector("thead").innerHTML =
    "<tr><th>日期</th><th>持仓数</th><th>标的</th></tr>";
  $("positions").querySelector("tbody").innerHTML = p.rows.map((r) =>
    `<tr><td>${r.date}</td><td>${r.count}</td>`
    + `<td>${r.holdings.length ? r.holdings.map((h) => h.thscode).join(" ") : "空仓"}</td></tr>`).join("");
}

// 净值曲线：策略 vs 基准，附回撤副图。**这是回测的头部图表**
// （对标聚宽的"收益曲线"；聚宽默认画沪深300，本仓库没有指数数据，故用等权主板篮子并如实标注）。
async function loadEquity() {
  const r = await fetch(`/api/runs/${HP.runId}/equity`);
  if (!r.ok) {
    HP.equity = null;
    $("equity-chart").innerHTML = ""; $("equity-summary").textContent = "";
    $("equity-caveat").textContent = "本次运行没有可用的净值曲线";
    return;
  }
  const d = await r.json();
  HP.equity = d;      // 存下来：每日收益表要用同一份，
                      // 再拉一次会让服务端把**基准查询**白算一遍
  // 只做**呈现**格式化（×100 加百分号），不做任何派生统计——数字一律来自 API
  const pct = (v) => (v === null || v === undefined ? "—" : (v * 100).toFixed(2) + "%");
  $("equity-summary").innerHTML =
    `策略 <b>${pct(d.strategy_return)}</b>　基准（${d.benchmark_label}） <b>${pct(d.benchmark_return)}</b>　`
    + `超额 <b>${pct(d.excess_return)}</b>`;
  $("equity-caveat").textContent = d.excess_caveat;

  const dates = d.strategy.map((p) => p.date);
  const bmap = new Map(d.benchmark.map((p) => [p.date, p.value]));
  echarts.init($("equity-chart")).setOption({
    backgroundColor: "transparent", animation: false,
    tooltip: { trigger: "axis" },
    legend: { textStyle: { color: "#bbb" }, top: 0 },
    grid: [{ left: 60, right: 20, top: 30, height: "58%" },
           { left: 60, right: 20, top: "74%", height: "18%" }],
    xAxis: [{ type: "category", data: dates },
            { type: "category", gridIndex: 1, data: dates, axisLabel: { show: false } }],
    yAxis: [{ scale: true, splitLine: { lineStyle: { color: "#2a2a2a" } } },
            { gridIndex: 1, max: 1, splitLine: { show: false } }],
    series: [
      { name: "策略", type: "line", symbol: "none", data: d.strategy.map((p) => p.value),
        lineStyle: { width: 2, color: "#4da3ff" } },
      { name: d.benchmark_label, type: "line", symbol: "none", connectNulls: true,
        data: dates.map((x) => (bmap.has(x) ? bmap.get(x) : null)),
        lineStyle: { width: 1, color: "#ffa726" } },
      { name: "回撤", type: "line", xAxisIndex: 1, yAxisIndex: 1, symbol: "none",
        data: d.drawdown.map((p) => p.value),
        areaStyle: { opacity: 0.25 }, lineStyle: { width: 0, color: "#ff5252" },
        itemStyle: { color: "#ff5252" } },
    ],
  });
}

async function loadTrades() {
  const r = await fetch(`/api/runs/${HP.runId}/trades`);
  const data = await r.json();
  HP.trades = data.rows;
  const cols = data.columns.filter((c) => c !== "i");
  $("trades").querySelector("thead").innerHTML =
    `<tr>${cols.map((c) => `<th>${c}</th>`).join("")}</tr>`;
  $("trades").querySelector("tbody").innerHTML = data.rows.map((row) =>
    `<tr data-i="${row.i}">${cols.map((c) => `<td>${row[c] ?? ""}</td>`).join("")}</tr>`
  ).join("");
  // 新一次运行：清掉上一笔的选中与位置
  HP.tradeIdx = -1;
  $("trade-pos").textContent = "";
  $("prev-trade").disabled = true;
  $("next-trade").disabled = true;
  $("trades").querySelector("tbody").onclick = (e) => {
    const tr = e.target.closest("tr");
    if (tr) setTrade(Number(tr.dataset.i));
  };
}

async function loadChart(i) {
  const r = await fetch(`/api/runs/${HP.runId}/trades/${i}/chart`);
  const d = await r.json();
  renderChart(d);
}

function setTrade(i) {
  if (!HP.trades.length) return;
  HP.tradeIdx = Math.max(0, Math.min(i, HP.trades.length - 1));
  $("trade-pos").textContent = `第 ${HP.tradeIdx + 1} / ${HP.trades.length} 笔`;
  $("prev-trade").disabled = HP.tradeIdx === 0;
  $("next-trade").disabled = HP.tradeIdx >= HP.trades.length - 1;
  const cur = HP.trades[HP.tradeIdx].i;
  for (const tr of $("trades").querySelectorAll("tbody tr")) {
    tr.classList.toggle("sel", Number(tr.dataset.i) === cur);
  }
  return loadChart(cur);
}

function renderChart(d) {
  // Task 8 实现：K 线 + MA + MACD + 入场/出场标记 + SL/TP 两条横线
}

async function loadConfigs() {
  const r = await fetch("/api/configs");
  HP.configs = (await r.json()).configs;
  renderConfigs();
}

function renderConfigs() {
  const box = $("config-list");
  box.innerHTML = "";
  if (!HP.configs.length) {
    box.innerHTML = '<span class="hint">还没有配置。展开一个预设、改几个参数，再点上面的按钮保存。</span>';
    return;
  }
  for (const c of HP.configs) {
    const row = document.createElement("div");
    row.className = "cfg";
    const n = Object.keys(c.overrides || {}).length;
    row.innerHTML = `<span class="nm">${c.name}</span>
      <span class="hint">${c.preset} · 改 ${n} 项${c.note ? " · " + c.note : ""}</span>`;
    if (c.preset_drifted) {
      // 预设本身变了：不静默、也不阻断——只是"同一个配置"跑出来的参数已经不同了（§0）
      const w = document.createElement("span");
      w.className = "drift";
      w.textContent = "⚠ 预设已变动";
      w.title = "保存之后该预设本身被改过，此配置现在的实际参数与保存时不同";
      row.appendChild(w);
    }
    const ops = document.createElement("span");
    ops.className = "ops";
    const mk = (label, fn, title) => {
      const b = document.createElement("button");
      b.type = "button"; b.textContent = label; b.title = title || "";
      b.addEventListener("click", fn);
      return b;
    };
    ops.appendChild(mk("载入", () => loadConfigIntoForm(c), "载入到上方表单"));
    ops.appendChild(mk("复制", () => {
      const newName = prompt("新配置名", `${c.name} 副本`);
      if (newName) fetch(`/api/configs/${encodeURIComponent(c.name)}/duplicate`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ new_name: newName }),
      }).then(loadConfigs).catch(() => {});
    }, "复制成一份新配置"));
    ops.appendChild(mk("删除", () => {
      if (!confirm(`删除配置「${c.name}」？`)) return;
      fetch(`/api/configs/${encodeURIComponent(c.name)}`, { method: "DELETE" })
        .then(loadConfigs).catch(() => {});
    }));
    row.appendChild(ops);
    box.appendChild(row);
  }
}

function loadConfigIntoForm(c) {
  const p = HP.catalog.find((x) => x.engine === c.engine && x.preset === c.preset);
  if (!p) { $("run-status").textContent = `载入失败：目录里找不到 ${c.engine}/${c.preset}`; return; }
  HP.edits.set(presetKey(p), { ...(c.overrides || {}) });
  HP.selected = p;
  renderCatalog($("filter").value);
  const det = document.querySelector(`details[data-key="${presetKey(p)}"]`);
  if (det) { det.open = true; det.scrollIntoView({ block: "center" }); }
  $("run-status").textContent = c.preset_drifted
    ? `已载入「${c.name}」——注意：该预设保存后被改过，实际参数与保存时不同`
    : `已载入「${c.name}」`;
}

async function saveCurrentConfig() {
  if (!HP.selected) { $("run-status").textContent = "请先在目录里展开一个预设"; return; }
  const name = prompt("配置名", `${HP.selected.preset} 变体`);
  if (!name) return;
  const r = await fetch("/api/configs", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, engine: HP.selected.engine, preset: HP.selected.preset,
                           overrides: changedOverrides(HP.selected) }),
  });
  $("run-status").textContent = r.ok ? `已保存配置「${name}」` : `保存失败：${(await r.json()).detail}`;
  if (r.ok) await loadConfigs();
}

async function loadHistory() {
  const r = await fetch("/api/runs?limit=50");
  HP.history = (await r.json()).runs;
  renderHistory();
}

function renderHistory() {
  const box = $("history-list");
  box.innerHTML = "";
  for (const h of HP.history) {
    const row = document.createElement("label");
    row.className = "run";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.value = h.run_id;
    cb.disabled = !h.has_result;              // 没有落盘结果的（如被取消）不能对比
    cb.addEventListener("change", updateCompareButton);
    row.appendChild(cb);
    const eff = Object.keys(h.param_diff || {}).length;
    row.appendChild(document.createTextNode(
      ` ${h.preset} · ${h.mode} · ${h.start}~${h.end}`
      + (eff ? ` · 改 ${eff} 项` : " · 原件")
      + (h.has_result ? "" : "（无结果）")));
    // 「载入」补上迭代闭环：把那次运行的改动载回表单，改完再跑。
    // 没有它，"拿昨天的配置调一下"这条开发期最常见的动作就断了——
    // 历史只能看、不能续。
    const load = document.createElement("button");
    load.type = "button";
    load.textContent = "载入参数";
    load.title = "把该次运行的参数改动载入上面的表单，便于在此基础上继续调";
    load.addEventListener("click", (e) => {
      e.preventDefault(); e.stopPropagation(); loadRunIntoForm(h);
    });
    row.appendChild(load);
    if (h.has_result) {
      const a = document.createElement("a");
      a.href = `/api/runs/${h.run_id}/export/trades.csv`;
      a.textContent = "CSV";
      a.title = "导出成交明细（14 列规范顺序）";
      row.appendChild(a);
    }
    box.appendChild(row);
  }
  updateCompareButton();
}

function loadRunIntoForm(h) {
  const p = HP.catalog.find((x) => x.engine === h.engine && x.preset === h.preset);
  if (!p) { $("run-status").textContent = `载入失败：目录里找不到 ${h.engine}/${h.preset}`; return; }
  // 只载入**当时改过的**键；其余仍取预设默认——与 changedOverrides 的口径一致
  HP.edits.set(presetKey(p), { ...(h.param_diff || {}) });
  HP.selected = p;
  renderCatalog($("filter").value);
  const det = document.querySelector(`details[data-key="${presetKey(p)}"]`);
  if (det) { det.open = true; det.scrollIntoView({ block: "center" }); }
  $("run-status").textContent =
    `已载入 ${h.preset} 的参数（基于运行 ${h.run_id}）——改完点“开始回测”即可`;
}

function updateCompareButton() {
  $("compare").disabled =
    document.querySelectorAll("#history-list input:checked").length < 2;
}

async function compareSelected() {
  const ids = [...document.querySelectorAll("#history-list input:checked")].map((c) => c.value);
  const r = await fetch(`/api/compare?ids=${ids.join(",")}`);
  const out = $("compare-out");
  out.hidden = false;
  if (!r.ok) { out.textContent = (await r.json()).detail; return; }
  const d = await r.json();
  // 缺的指标渲染成 "—"（**不是 0**）：0 是"真的零"，— 是"这个引擎不产出该指标"
  out.innerHTML = `<table><thead><tr><th>指标</th>${d.rows.map((x) =>
      `<th>${x.preset}<br><span class="hint">${x.run_id} · ${x.mode ?? ""}</span></th>`).join("")}</tr></thead>`
    + `<tbody>${d.keys.map((k) => `<tr><td>${k}</td>${d.rows.map((x) =>
      `<td>${x.metrics[k] === null || x.metrics[k] === undefined ? "—" : x.metrics[k]}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}

$("filter").addEventListener("input", (e) => renderCatalog(e.target.value));
$("compare").addEventListener("click", () => compareSelected().catch(() => {}));
$("save-config").addEventListener("click", () => saveCurrentConfig().catch(() => {}));
$("prev-trade").addEventListener("click", () => setTrade(HP.tradeIdx - 1));
$("next-trade").addEventListener("click", () => setTrade(HP.tradeIdx + 1));
for (const b of document.querySelectorAll(".quick button")) {
  b.addEventListener("click", () => {
    const end = new Date();
    const start = new Date(end.getTime() - Number(b.dataset.days) * 86400000);
    $("end").value = end.toISOString().slice(0, 10);
    $("start").value = start.toISOString().slice(0, 10);
  });
}
$("run").addEventListener("click", () => startRun().catch(() => {}));
$("cancel").addEventListener("click", () => cancelRun().catch(() => {}));
$("start").value = "2025-01-01";
$("end").value = "2026-10-16";
loadCatalog();
loadHistory();
loadConfigs();

window.HP = HP;
