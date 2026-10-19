const COLORS = { green: "#34D399", teal: "#2DD4C8", amber: "#F5A623", red: "#EF5350", solar: "#FFD166", mutedDim: "#54695F", border: "#243430", muted: "#7E9A90", text: "#E7F0EC", grid: "#7E9A90" };
let selectedId = 1;
let charts = {};
if (window.Chart) { Chart.defaults.color = COLORS.muted; Chart.defaults.font.family = "'IBM Plex Mono', monospace"; }

/* ---------------------------------------------------------------- helpers */
function statusColor(s) {
  if (!s.active) return COLORS.mutedDim;
  if (s.status === "em fila" || s.status === "protegido") return COLORS.red;
  if (s.status === "limitado" || s.status === "reservado") return COLORS.amber;
  return s.plan === "pre" ? COLORS.green : COLORS.teal;
}
function fmt(n, d = 2) { return Number(n).toFixed(d); }
function fmtHour(h) {
  let hh = Math.floor(h), mm = Math.round((h % 1) * 60);
  if (mm === 60) { hh = (hh + 1) % 24; mm = 0; }
  return `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
}
async function fetchState() { const res = await fetch("/api/state"); return res.json(); }
async function post(path) { await fetch(path, { method: "POST" }); render(); }

/* ----------------------------------------------------------- barramento */
function renderLoadCard(data) {
  const loadPct = Math.min((data.total_load / data.max_capacity) * 100, 100);
  const loadColor = loadPct > 92 ? COLORS.red : loadPct > 72 ? COLORS.amber : COLORS.green;
  const lv = document.getElementById("load-value");
  lv.innerHTML = `${fmt(data.total_load, 1)} <span>/ ${fmt(data.max_capacity, 0)} A</span>`;
  lv.style.color = loadColor;
  const alertEl = document.getElementById("load-alert");
  if (loadPct > 72) {
    alertEl.style.color = loadColor;
    alertEl.textContent = loadPct > 92 ? "⚠ limite próximo — limitando pós-pago" : "⚠ carga elevada";
  } else { alertEl.textContent = ""; }
  const fill = document.getElementById("bar-fill");
  fill.style.width = loadPct + "%";
  fill.style.background = `linear-gradient(90deg, ${COLORS.border}, ${loadColor})`;
  const gridPct = Math.min((data.grid_capacity / data.max_capacity) * 100, 100);
  document.getElementById("grid-marker").style.left = gridPct + "%";
  const bonusA = data.max_capacity - data.grid_capacity;
  document.getElementById("bar-sublabel").innerHTML = bonusA > 0.1
    ? `rede: ${fmt(data.grid_capacity, 0)} A &nbsp;+&nbsp; <span class="solar-amt">☀️🔋 geração local: ${fmt(bonusA, 1)} A</span> &nbsp;=&nbsp; ${fmt(data.max_capacity, 1)} A disponíveis (limite físico ${data.bus_limit} A)`
    : `rede: ${fmt(data.grid_capacity, 0)} A · sem geração local disponível neste instante`;
  const taps = document.getElementById("taps");
  taps.innerHTML = "";
  data.stations.forEach((s) => {
    const tap = document.createElement("div");
    tap.className = "tap" + (s.id === selectedId ? " selected" : "");
    tap.style.opacity = s.active ? 1 : 0.35;
    tap.innerHTML = `<div class="line"></div><div class="dot" style="background:${statusColor(s)}"></div><div class="id mono">#${s.id}</div>`;
    tap.onclick = () => { selectedId = s.id; render(); };
    taps.appendChild(tap);
  });
}

/* ----------------------------------------------------------------- vagas */
function renderStationGrid(data) {
  const grid = document.getElementById("station-grid");
  grid.innerHTML = "";
  data.stations.forEach((s) => {
    const card = document.createElement("div");
    card.className = `station-card plan-${s.plan}` + (s.id === selectedId ? " selected" : "") + (s.status === "protegido" ? " anomaly" : "");
    const kw = (s.current_a * data.voltage) / 1000;
    card.innerHTML = `
      <div class="top-row">
        <div><div class="name">${s.name}</div><div class="slot mono">vaga #${s.id}</div></div>
        <button class="plug-btn" data-action="plug" data-id="${s.id}">${s.active ? "✕" : "+"}</button>
      </div>
      <div class="status-row"><span class="status-dot" style="background:${statusColor(s)}"></span><span class="status-label">${s.status}</span></div>
      <div class="kw mono">${fmt(kw)} <span>kW</span></div>
      <div class="sub">${fmt(s.energy_kwh)} kWh · R$ ${fmt(s.cost)}</div>
      <button class="plan-btn mono" data-action="plan" data-id="${s.id}">${s.plan === "pre" ? "pré-pago" : "pós-pago"} →</button>
      ${s.active && s.status !== "protegido" ? `<button class="fault-btn mono" data-action="fault" data-id="${s.id}">⚡ simular falha no sensor</button>` : ""}
    `;
    card.onclick = (e) => { if (e.target.dataset.action) return; selectedId = s.id; render(); };
    grid.appendChild(card);
  });
  const bind = (action, path) => grid.querySelectorAll(`[data-action="${action}"]`).forEach((btn) => {
    btn.onclick = (e) => { e.stopPropagation(); post(`/api/${path}/${btn.dataset.id}`); };
  });
  bind("plug", "toggle_plug"); bind("plan", "toggle_plan"); bind("fault", "fault");
}

/* -------------------------------------------------- fluxo de energia (SVG) */
function renderFlow(data) {
  const last = data.history[data.history.length - 1] || {};
  const gen = last.solar_gen_kw || 0, charge = last.charge_kw || 0, dis = last.batt_kw || 0;
  const grid = last.grid_kw || 0, exp = last.export_kw || 0, load = last.load_kw || 0;
  const on = (v) => v > 0.05;
  const wire = (x1, y1, x2, y2, v, color, label, lx, ly, reverse) => {
    const [a, b, c, d] = reverse ? [x2, y2, x1, y1] : [x1, y1, x2, y2];
    return `<path class="wire ${on(v) ? "on" : ""}" d="M${a},${b} L${c},${d}" ${on(v) ? `style="stroke:${color}"` : ""} marker-end="${on(v) ? `url(#ah-${color.slice(1)})` : ""}"/>
      <text class="wlabel" x="${lx}" y="${ly}" text-anchor="middle" fill="${on(v) ? color : COLORS.mutedDim}">${label}</text>`;
  };
  const node = (x, y, icon, t1, t2) => `<g class="node"><rect x="${x - 62}" y="${y - 27}" width="124" height="54" rx="10"/>
      <text class="t1" x="${x}" y="${y - 8}" text-anchor="middle">${icon} ${t1}</text><text class="t2" x="${x}" y="${y + 14}" text-anchor="middle">${t2}</text></g>`;
  const markers = [COLORS.solar, COLORS.teal, COLORS.grid, COLORS.green].map((c) =>
    `<marker id="ah-${c.slice(1)}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="${c}"/></marker>`).join("");
  const battLabel = charge > 0.05 ? `carga ${fmt(charge, 1)} kW` : dis > 0.05 ? `descarga ${fmt(dis, 1)} kW` : "em espera";
  document.getElementById("flow").innerHTML = `
  <svg viewBox="0 0 640 215" role="img" aria-label="Diagrama de fluxo de energia">
    <defs>${markers}</defs>
    ${wire(142, 45, 258, 96, gen, COLORS.solar, `${fmt(gen, 1)} kW`, 190, 62, false)}
    ${wire(142, 170, 258, 122, Math.max(charge, dis), COLORS.teal, battLabel, 200, 172, charge > dis)}
    ${wire(498, 45, 382, 96, grid, COLORS.grid, `${fmt(grid, 1)} kW`, 450, 62, false)}
    ${wire(498, 170, 382, 122, exp, COLORS.grid, `${fmt(exp, 1)} kW`, 465, 164, true)}
    ${node(80, 45, "☀️", "Solar", fmt(gen, 1) + " kW")}
    ${node(80, 170, "🔋", "Bateria", fmt(data.battery.soc_pct, 0) + " %")}
    ${node(560, 45, "🔌", "Rede", fmt(grid, 1) + " kW")}
    ${node(560, 170, "🌐", "Exportação", fmt(exp, 1) + " kW")}
    <g class="node"><rect x="258" y="82" width="124" height="52" rx="10" style="stroke:${COLORS.green}"/>
      <text class="t1" x="320" y="101" text-anchor="middle">🚗 Carregadores</text><text class="t2" x="320" y="122" text-anchor="middle" style="fill:${COLORS.green}">${fmt(load, 1)} kW</text></g>
  </svg>`;
  document.getElementById("flow-note").textContent = `${fmtHour(data.hour)} · ${data.tariff.peak ? "PONTA" : "fora de ponta"}`;
}

/* ------------------------------------------------------------- fórmulas */
function renderFormulaCard(data) {
  const s = data.stations.find((x) => x.id === selectedId) || data.stations[0];
  const power = (s.current_a * data.voltage) / 1000;
  const price = s.plan === "pre" ? data.price_pre : data.price_pos;
  document.getElementById("formula-card").innerHTML = `
    <div class="label">Leitura em tempo real — ${s.name} <span class="mono" style="color:${COLORS.mutedDim}">#${s.id}</span></div>
    <div class="formula-row"><span class="fl">Tensão (V)</span><span class="fv mono">${data.voltage} V</span></div>
    <div class="formula-row"><span class="fl">Corrente medida (Hall)</span><span class="fv mono">${fmt(s.current_a)} A</span></div>
    <div class="formula-row"><span class="fl">Corrente comandada</span><span class="fv mono">${fmt(s.commanded_a)} A</span></div>
    <div class="hr"></div>
    <div class="formula-row big"><span class="fl">P = V · I</span><span class="fv mono">${fmt(power)} kW</span></div>
    <div class="formula-row big"><span class="fl">E = P · Δt <span class="muted-note">(Δt = 0,1 h)</span></span><span class="fv mono">${fmt(s.energy_kwh, 3)} kWh</span></div>
    <div class="hr"></div>
    <div class="formula-row big"><span class="fl">Custo (R$ ${fmt(price)}/kWh)</span><span class="fv mono" style="color:${COLORS.green}">R$ ${fmt(s.cost)}</span></div>
  `;
}
function renderPlansCard(data) {
  document.getElementById("plans-card").innerHTML = `
    <div class="label">Planos de recarga</div>
    <div class="plan-row"><div class="plan-dot" style="background:${COLORS.green}"></div><div>
      <div class="plan-title-row"><span class="plan-title">Pré-pago</span><span class="plan-price mono">R$ ${fmt(data.price_pre)}/kWh</span></div>
      <div class="plan-desc">Corrente-alvo de 16 A. Capacidade priorizada: só é reduzido se a demanda pré-paga sozinha excede toda a capacidade disponível.</div></div></div>
    <div class="plan-row"><div class="plan-dot" style="background:${COLORS.teal}"></div><div>
      <div class="plan-title-row"><span class="plan-title">Pós-pago</span><span class="plan-price mono">R$ ${fmt(data.price_pos)}/kWh</span></div>
      <div class="plan-desc">Corrente-alvo de 10 A. Mais barato, mas cede capacidade ao pré-pago e é o plano "flexível" que o otimizador adia na ponta.</div></div></div>
  `;
}

/* -------------------------------------------------- solar + bateria card */
function renderSolarCard(data) {
  const s = data.solar, b = data.battery;
  const pct = Math.min(s.coverage_pct, 100);
  const bcolor = b.soc_pct < 25 ? COLORS.red : b.soc_pct < 50 ? COLORS.amber : COLORS.teal;
  const stColor = b.state === "carregando" ? COLORS.green : b.state === "descarregando" ? COLORS.solar : COLORS.muted;
  document.getElementById("solar-card").innerHTML = `
    <div class="solar-header"><div class="label">☀️ Geração renovável e armazenamento</div><div class="solar-clock mono">${fmtHour(data.hour)}</div></div>
    <div class="solar-gauge-row">
      <div class="solar-gauge" style="--pct:${pct}"><span>${fmt(pct, 0)}%</span></div>
      <div class="solar-gauge-caption">do consumo está sendo coberto por <b>energia renovável</b> agora (solar direta + bateria).</div>
    </div>
    <div class="formula-row"><span class="fl">Potência instalada</span><span class="fv mono">${fmt(s.installed_kwp, 0)} kWp</span></div>
    <div class="formula-row"><span class="fl">Geração solar agora</span><span class="fv mono" style="color:${COLORS.solar}">${fmt(s.power_kw)} kW</span></div>
    <div class="formula-row"><span class="fl">Nebulosidade estimada</span><span class="fv mono">${fmt((1 - s.cloud_est) * 100, 0)} %</span></div>
    <div class="formula-row"><span class="fl">Capacidade extra liberada</span><span class="fv mono" style="color:${COLORS.solar}">+${fmt(s.bonus_a, 1)} A</span></div>
    <div class="section-sep">Bateria (${fmt(b.capacity_kwh, 0)} kWh)</div>
    <div class="batt-row">
      <div class="batt-shell">
        <div class="batt-fill" style="width:${b.soc_pct}%;background:${bcolor}"></div>
        <div class="batt-min" style="left:${b.min_soc_pct}%"></div>
        <div class="batt-txt mono">${fmt(b.soc_pct, 0)}% · ${fmt(b.kwh, 1)} kWh</div>
      </div>
      <div class="batt-state mono" style="color:${stColor}">${b.state}${Math.abs(b.power_kw) > 0.05 ? `<br>${fmt(Math.abs(b.power_kw), 1)} kW` : ""}</div>
    </div>
    <div class="hr"></div>
    <div class="formula-row"><span class="fl">Energia solar usada (acum.)</span><span class="fv mono">${fmt(s.solar_energy_kwh, 1)} kWh</span></div>
    <div class="formula-row"><span class="fl">Energia da bateria (acum.)</span><span class="fv mono">${fmt(b.to_load_kwh, 1)} kWh</span></div>
    <div class="formula-row"><span class="fl">Energia de rede (acum.)</span><span class="fv mono">${fmt(s.grid_energy_kwh, 1)} kWh</span></div>
    <div class="formula-row"><span class="fl">Excedente injetado (acum.)</span><span class="fv mono">${fmt(s.export_kwh, 1)} kWh</span></div>
  `;
}

/* ------------------------------------------------- decisões / recomendação */
function renderDecisionsCard(data) {
  document.getElementById("decisions-card").innerHTML = `
    <div class="label">🧠 Decisões do otimizador <span class="muted-note">· ${data.modes[data.mode]}</span></div>
    <ul class="dec-list">${data.decisions.map((d) => `<li>${d}</li>`).join("")}</ul>
    <div class="reco">💡 <b>Recomendação:</b> ${data.recommendation || "—"}</div>
  `;
}
function renderEventsCard(data) {
  document.getElementById("events-card").innerHTML = `
    <div class="label">🛡️ Proteção e alertas <span class="muted-note">· desarmes: ${data.trips}</span></div>
    <ul class="ev-list">${data.events.slice(0, 8).map((e) =>
      `<li class="${e.level}"><span class="eh">${fmtHour(e.hour)}</span>${e.msg}</li>`).join("")}</ul>
  `;
}

/* ------------------------------------------------------- impacto (KPIs) */
function renderImpactCard(data) {
  const f = data.finance, e = data.env;
  document.getElementById("impact-card").innerHTML = `
    <div class="label">🌱 Impacto da sessão</div>
    <div class="kpi-grid">
      <div class="kpi"><div class="kv" style="color:${COLORS.solar}">${fmt(e.renewable_share_pct, 0)}%</div><div class="kl">do consumo é renovável</div></div>
      <div class="kpi"><div class="kv" style="color:${COLORS.green}">${fmt(e.co2_avoided_kg, 1)} kg</div><div class="kl">CO₂ evitado (≈ ${fmt(e.trees_eq, 2)} árvore/ano)</div></div>
      <div class="kpi"><div class="kv" style="color:${COLORS.green}">R$ ${fmt(f.savings, 0)}</div><div class="kl">economia vs. só rede</div></div>
      <div class="kpi"><div class="kv">${fmt(e.service_level_pct, 0)}%</div><div class="kl">da demanda atendida</div></div>
    </div>
    <div class="hr"></div>
    <div class="formula-row"><span class="fl">Custo da rede (real)</span><span class="fv mono">R$ ${fmt(f.grid_cost)}</span></div>
    <div class="formula-row"><span class="fl">Custo se fosse só rede</span><span class="fv mono">R$ ${fmt(f.baseline_cost)}</span></div>
    <div class="formula-row"><span class="fl">Crédito por injeção</span><span class="fv mono">R$ ${fmt(f.export_credit)}</span></div>
    <div class="formula-row big"><span class="fl">Margem operacional</span><span class="fv mono" style="color:${COLORS.green}">R$ ${fmt(f.margin)}</span></div>
  `;
}
function renderStatsCard(data) {
  const activeCount = data.stations.filter((s) => s.active).length;
  document.getElementById("stats-card").innerHTML = `
    <div class="label">Painel de operação</div>
    <div class="stat-row"><span class="sl">Vagas ativas</span><span class="sv mono">${activeCount} / ${data.stations.length}</span></div>
    <div class="stat-row"><span class="sl">Energia entregue</span><span class="sv mono">${fmt(data.total_energy)} kWh</span></div>
    <div class="stat-row"><span class="sl">Limitações de carga (pós-pago)</span><span class="sv mono" style="color:${data.overload_events > 0 ? COLORS.amber : COLORS.text}">${data.overload_events}</span></div>
    <div class="stat-row"><span class="sl">Sobrecargas evitadas pela geração local</span><span class="sv mono" style="color:${COLORS.solar}">${data.overload_avoided_local}</span></div>
  `;
}

/* --------------------------------------------------------------- gráficos */
const axisOpts = { ticks: { color: COLORS.mutedDim, font: { size: 10 }, maxTicksLimit: 8 }, grid: { color: COLORS.border } };
function renderMixChart(data) {
  document.getElementById("solar-coverage-mini").textContent = `${fmt(data.solar.coverage_pct, 0)}% renovável agora`;
  const h = data.history;
  const labels = h.map((r) => fmtHour(r.hour));
  const sets = [h.map((r) => r.solar_kw), h.map((r) => r.batt_kw), h.map((r) => r.grid_kw), h.map((r) => r.soc)];
  if (!charts.mix) {
    charts.mix = new Chart(document.getElementById("mix-chart").getContext("2d"), {
      type: "line",
      data: { labels, datasets: [
        { label: "solar (kW)", data: sets[0], borderColor: COLORS.solar, backgroundColor: "rgba(255,209,102,0.35)", fill: true, stack: "mix", tension: 0.25, pointRadius: 0, yAxisID: "y" },
        { label: "bateria (kW)", data: sets[1], borderColor: COLORS.teal, backgroundColor: "rgba(45,212,200,0.35)", fill: true, stack: "mix", tension: 0.25, pointRadius: 0, yAxisID: "y" },
        { label: "rede (kW)", data: sets[2], borderColor: COLORS.mutedDim, backgroundColor: "rgba(126,154,144,0.3)", fill: true, stack: "mix", tension: 0.25, pointRadius: 0, yAxisID: "y" },
        { label: "SOC (%)", data: sets[3], borderColor: COLORS.text, borderDash: [5, 4], borderWidth: 1.5, fill: false, tension: 0.25, pointRadius: 0, yAxisID: "y2" },
      ]},
      options: { responsive: true, animation: false, interaction: { mode: "index", intersect: false },
        scales: { x: axisOpts, y: { stacked: true, ...axisOpts, title: { display: true, text: "kW", color: COLORS.mutedDim } },
                  y2: { position: "right", min: 0, max: 100, ticks: { color: COLORS.mutedDim, font: { size: 10 } }, grid: { display: false }, title: { display: true, text: "SOC %", color: COLORS.mutedDim } } },
        plugins: { legend: { labels: { color: COLORS.muted, font: { size: 11 } } } } },
    });
  } else {
    const c = charts.mix; c.data.labels = labels; sets.forEach((d, i) => (c.data.datasets[i].data = d)); c.update("none");
  }
}
function renderForecastChart(data) {
  const f = data.forecast;
  const labels = f.map((x) => String(x.hour).padStart(2, "0") + "h");
  const total = f.reduce((a, x) => a + x.kw, 0);
  const demand = f.map(() => data.expected_load_kw);
  document.getElementById("forecast-note").textContent = `≈ ${fmt(total, 0)} kWh previstos · demanda média ${fmt(data.expected_load_kw, 1)} kW · nebulosidade ${fmt((1 - data.solar.cloud_est) * 100, 0)}%`;
  const vals = f.map((x) => x.kw);
  if (!charts.fc) {
    charts.fc = new Chart(document.getElementById("forecast-chart").getContext("2d"), {
      data: { labels, datasets: [
        { type: "bar", label: "geração prevista (kW)", data: vals, backgroundColor: "rgba(255,209,102,0.75)", borderRadius: 3 },
        { type: "line", label: "demanda média esperada (kW)", data: demand, borderColor: COLORS.red, borderDash: [6, 4], borderWidth: 1.5, pointRadius: 0, fill: false },
      ]},
      options: { responsive: true, animation: false, scales: { x: axisOpts, y: { ...axisOpts, beginAtZero: true } },
        plugins: { legend: { labels: { color: COLORS.muted, font: { size: 11 } } } } },
    });
  } else {
    const c = charts.fc; c.data.labels = labels; c.data.datasets[0].data = vals; c.data.datasets[1].data = demand; c.update("none");
  }
}
function renderChart(data) {
  document.getElementById("total-revenue").textContent = `R$ ${fmt(data.total_revenue)}`;
  const labels = data.history.map((h) => fmtHour(h.hour));
  const pre = data.history.map((h) => h.pre), pos = data.history.map((h) => h.pos);
  if (!charts.rev) {
    charts.rev = new Chart(document.getElementById("revenue-chart").getContext("2d"), {
      type: "line",
      data: { labels, datasets: [
        { label: "pré-pago (R$)", data: pre, borderColor: COLORS.green, backgroundColor: "rgba(52,211,153,0.2)", fill: true, tension: 0.3, pointRadius: 0 },
        { label: "pós-pago (R$)", data: pos, borderColor: COLORS.teal, backgroundColor: "rgba(45,212,200,0.2)", fill: true, tension: 0.3, pointRadius: 0 },
      ]},
      options: { responsive: true, animation: false, interaction: { mode: "index", intersect: false },
        scales: { x: axisOpts, y: { stacked: true, ...axisOpts } }, plugins: { legend: { labels: { color: COLORS.muted, font: { size: 11 } } } } },
    });
  } else {
    const c = charts.rev; c.data.labels = labels; c.data.datasets[0].data = pre; c.data.datasets[1].data = pos; c.update("none");
  }
}

/* ------------------------------------------------------------- controles */
function renderControls(data) {
  document.querySelectorAll("#mode-seg button").forEach((b) => b.classList.toggle("active", b.dataset.mode === data.mode));
  document.querySelectorAll("#speed-seg button").forEach((b) => b.classList.toggle("active", Number(b.dataset.speed) === data.speed));
  document.getElementById("clock").textContent = fmtHour(data.hour);
  const tp = document.getElementById("tariff-pill");
  tp.textContent = `${data.tariff.peak ? "⚡ PONTA" : "fora de ponta"} · R$ ${fmt(data.tariff.current)}/kWh`;
  tp.classList.toggle("peak", data.tariff.peak);
  document.getElementById("source-chip").textContent = data.source.connected ? "🟢 Dados: inversor GoodWe (real)" : "🔌 Dados: simulados";
}
document.querySelectorAll("#mode-seg button").forEach((b) => (b.onclick = () => post(`/api/mode/${b.dataset.mode}`)));
document.querySelectorAll("#hour-seg button").forEach((b) => (b.onclick = () => post(`/api/set_hour/${b.dataset.hour}`)));
document.querySelectorAll("#speed-seg button").forEach((b) => (b.onclick = () => post(`/api/speed/${b.dataset.speed}`)));
document.getElementById("reset-btn").onclick = () => post("/api/reset");

/* ------------------------------------------------------------ assistente */
const chat = document.getElementById("chat");
const chatText = document.getElementById("chat-text");
function addMsg(text, who, cls = "") {
  const d = document.createElement("div");
  d.className = `msg ${who} ${cls}`; d.textContent = text;
  chat.appendChild(d); chat.scrollTop = chat.scrollHeight;
  return d;
}
function speak(text) {
  if (!document.getElementById("tts").checked || !("speechSynthesis" in window)) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text); u.lang = "pt-BR";
  window.speechSynthesis.speak(u);
}
async function ask(text) {
  text = (text || "").trim();
  if (!text) return;
  addMsg(text, "user");
  const pending = addMsg("…", "bot", "pending");
  try {
    const res = await fetch("/api/assistant", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
    const out = await res.json();
    pending.remove(); addMsg(out.reply, "bot"); speak(out.reply);
  } catch (e) { pending.remove(); addMsg("Não consegui falar com o servidor.", "bot"); }
  render();
}
document.getElementById("send").onclick = () => { ask(chatText.value); chatText.value = ""; };
chatText.addEventListener("keydown", (e) => { if (e.key === "Enter") { ask(chatText.value); chatText.value = ""; } });
document.querySelectorAll("#suggest button").forEach((b) => (b.onclick = () => ask(b.textContent)));

const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
const mic = document.getElementById("mic");
if (!SR) { mic.style.display = "none"; }
else {
  const rec = new SR(); rec.lang = "pt-BR"; rec.interimResults = false;
  rec.onstart = () => mic.classList.add("listening");
  rec.onend = () => mic.classList.remove("listening");
  rec.onerror = () => mic.classList.remove("listening");
  rec.onresult = (ev) => ask(ev.results[0][0].transcript);
  mic.onclick = () => { try { rec.start(); } catch (e) { /* já iniciado */ } };
}

/* ------------------------------------------------------------------ loop */
async function render() {
  let data;
  try { data = await fetchState(); } catch (e) { return; }
  renderControls(data); renderLoadCard(data); renderStationGrid(data); renderFlow(data);
  renderFormulaCard(data); renderSolarCard(data); renderDecisionsCard(data); renderImpactCard(data);
  renderEventsCard(data); renderPlansCard(data); renderStatsCard(data);
  renderMixChart(data); renderForecastChart(data); renderChart(data);
}
render();
setInterval(render, 1500);
