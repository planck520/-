const SENSOR_META = {
  temperature: { label: "温度", unit: "°C", accent: "#40d383", warn: (v) => v > 30 || v < 16 },
  humidity: { label: "湿度", unit: "%RH", accent: "#22d3ee", warn: (v) => v > 80 || v < 30 },
  light: { label: "光照", unit: "Lux", accent: "#f5c84b", warn: (v) => v < 120 },
  co2: { label: "CO2", unit: "ppm", accent: "#8b7cf6", warn: (v) => v >= 1200 },
  noise: { label: "噪声", unit: "dB", accent: "#ff9f43", warn: (v) => v >= 65 },
  smoke: { label: "烟雾", unit: "ppm", accent: "#ff5b6e", warn: (v) => v > 150 },
  pm25: { label: "PM2.5", unit: "µg/m³", accent: "#9be15d", warn: (v) => v > 75 },
  fan_current: { label: "风扇电流", unit: "A", accent: "#4f9cff", warn: () => false },
  fan_power: { label: "风扇功率", unit: "W", accent: "#22d3ee", warn: () => false },
};

const DEVICE_META = {
  fan: { label: "风扇", kind: "switch" },
  lighting_led: { label: "照明 LED", kind: "brightness" },
  warning_led: { label: "警示灯", kind: "switch" },
  buzzer: { label: "蜂鸣器", kind: "switch" },
};

const FSM_LABELS = {
  VACANT: "无人",
  ARRIVING: "进入",
  OCCUPIED: "占用",
  LEAVING: "离开",
};

const PROFILE_LABELS = {
  energy_saving: "节能",
  balanced: "均衡",
  comfort: "舒适",
};

const HISTORY_DEFAULT = ["temperature", "humidity", "co2", "noise"];

const state = {
  latest: null,
  system: null,
  devices: {},
  alerts: [],
  weather: null,
  profiles: {},
  energySummary: null,
  energySeries: [],
  historyRangeHours: 24,
  selectedSensors: new Set(HISTORY_DEFAULT),
  historyData: {},
  energyRange: "day",
  chatAbort: null,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

document.addEventListener("DOMContentLoaded", () => {
  bindNavigation();
  bindControls();
  buildStaticControls();
  tickClock();
  setInterval(tickClock, 1000);
  refreshAll();
  setInterval(refreshAll, 2000);
  setInterval(() => {
    if ((location.hash || "#dashboard") === "#history") loadHistory();
    if ((location.hash || "#dashboard") === "#energy") loadEnergy();
  }, 10000);
  refreshProfiles();
  refreshEvents();
  loadAssistant();
  loadHistory();
  loadEnergy();
});

function bindNavigation() {
  const openPage = () => {
    const page = (location.hash || "#dashboard").slice(1);
    $$(".sidebar-nav a").forEach((link) => link.classList.toggle("active", link.dataset.page === page));
    $$(".page-section").forEach((section) => section.classList.remove("active"));
    $(`#page-${page}`)?.classList.add("active");
    if (page === "history") resizeCharts();
    if (page === "energy") loadEnergy();
  };
  window.addEventListener("hashchange", openPage);
  openPage();
}

function bindControls() {
  document.body.addEventListener("click", async (event) => {
    const shortcutButton = event.target.closest("[data-shortcut]");
    if (shortcutButton) {
      await runShortcutFromElement(shortcutButton);
      return;
    }

    const deviceButton = event.target.closest("[data-device-action]");
    if (deviceButton) {
      await controlDevice(deviceButton.dataset.device, deviceButton.dataset.deviceAction, deviceButton.dataset.value);
      return;
    }
  });

  $("#demo-toggle").addEventListener("click", () => shortcut("toggle_demo_mode", {}, "已切换 Demo / 真实模式"));
  $("#clear-alerts").addEventListener("click", () => shortcut("clear_alert", {}, "已请求清除全部告警"));
  $("#refresh-events").addEventListener("click", refreshEvents);
  $("#ack-smoke").addEventListener("click", () => $("#smoke-modal").classList.add("hidden"));

  $("#load-history").addEventListener("click", loadHistory);
  $("#export-history").addEventListener("click", exportHistoryCsv);
  $("#export-chart").addEventListener("click", exportHistoryPng);

  $("#history-ranges").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-range]");
    if (!button) return;
    state.historyRangeHours = Number(button.dataset.range);
    setActiveButton("#history-ranges", button);
    loadHistory();
  });

  $("#energy-ranges").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-range]");
    if (!button) return;
    state.energyRange = button.dataset.range;
    setActiveButton("#energy-ranges", button);
    loadEnergy();
  });

  $("#chat-form").addEventListener("submit", sendChat);
  $("#stop-chat").addEventListener("click", stopChat);
  $("#voice-button").addEventListener("click", startVoiceInput);

  window.addEventListener("resize", debounce(resizeCharts, 150));
  document.addEventListener("keydown", handleKeyboardShortcut);
}

function buildStaticControls() {
  $("#sensor-grid").innerHTML = Object.entries(SENSOR_META)
    .map(([key, meta]) => `
      <article class="sensor-card" id="sensor-${key}" style="--card-accent:${meta.accent}">
        <div class="sensor-label">${meta.label}</div>
        <div class="sensor-value"><strong>--</strong><span class="sensor-unit">${meta.unit}</span></div>
        <div class="sensor-time">等待数据</div>
      </article>
    `)
    .join("");

  $("#fsm-track").innerHTML = Object.entries(FSM_LABELS)
    .map(([key, label]) => `
      <div class="fsm-step" data-fsm="${key}">
        <strong>${key}</strong>
        <div class="muted">${label}</div>
      </div>
    `)
    .join("");

  $("#sensor-selector").innerHTML = Object.entries(SENSOR_META)
    .filter(([key]) => key !== "fan_power")
    .map(([key, meta]) => `
      <label>
        <input type="checkbox" value="${key}" ${state.selectedSensors.has(key) ? "checked" : ""}>
        ${meta.label}
      </label>
    `)
    .join("");

  $("#sensor-selector").addEventListener("change", (event) => {
    const input = event.target.closest("input[type=checkbox]");
    if (!input) return;
    if (input.checked) state.selectedSensors.add(input.value);
    else state.selectedSensors.delete(input.value);
    loadHistory();
  });

  addChatMessage("assistant", "你好，我会结合当前传感器、FSM、告警和能耗上下文回答问题。");
}

async function refreshAll() {
  const [latest, system, devices, alerts, energy, weather] = await Promise.allSettled([
    IotApi.get("/api/v1/sensors/latest"),
    IotApi.get("/api/v1/system/status"),
    IotApi.get("/api/v1/devices/status"),
    IotApi.get("/api/v1/alerts"),
    IotApi.get("/api/v1/energy/summary?range=day"),
    IotApi.get("/api/v1/weather"),
  ]);

  const ok = [latest, system, devices, alerts].some((result) => result.status === "fulfilled");
  setConnection(ok);

  if (latest.status === "fulfilled") state.latest = latest.value;
  if (system.status === "fulfilled") state.system = system.value;
  if (devices.status === "fulfilled") state.devices = devices.value || {};
  if (alerts.status === "fulfilled") state.alerts = alerts.value.active_alerts || [];
  if (energy.status === "fulfilled") state.energySummary = energy.value;
  if (weather.status === "fulfilled") state.weather = weather.value;

  renderDashboard();
}

async function refreshProfiles() {
  try {
    state.profiles = await IotApi.get("/api/v1/system/profiles");
    renderProfiles();
  } catch (error) {
    toast(`偏好模式加载失败：${error.message}`, "error");
  }
}

async function refreshEvents() {
  try {
    const payload = await IotApi.get("/api/v1/devices/events?limit=8");
    const events = payload.events || [];
    $("#device-events").innerHTML = events.length
      ? events.map((event) => `
        <div class="event-row">
          <strong>${deviceLabel(event.device_name)}</strong>
          <span class="muted">${event.action} ${formatEventValue(event.value)} · ${formatTime(event.timestamp)}</span>
        </div>
      `).join("")
      : "暂无设备事件";
  } catch (error) {
    $("#device-events").textContent = `设备事件加载失败：${error.message}`;
  }
}

function renderDashboard() {
  renderSensors();
  renderSystem();
  renderDevices();
  renderAlerts();
  renderAssistantContext();
}

function renderSensors() {
  const data = state.latest?.data || {};
  const timestamp = state.latest?.timestamp;
  Object.entries(SENSOR_META).forEach(([key, meta]) => {
    const card = $(`#sensor-${key}`);
    if (!card) return;
    const raw = data[key]?.value;
    const value = numberOrNull(raw);
    const unit = data[key]?.unit || meta.unit;
    card.querySelector("strong").textContent = value === null ? "--" : formatNumber(value);
    card.querySelector(".sensor-unit").textContent = normalizeUnit(unit);
    card.querySelector(".sensor-time").textContent = timestamp ? `更新 ${formatTime(timestamp)}` : "等待数据";
    card.style.borderColor = value !== null && meta.warn(value) ? "rgba(255,91,110,.48)" : "";
  });
}

function renderSystem() {
  const system = state.system || {};
  $("#ai-mode").textContent = aiModeLabel(system.ai_mode);
  $("#uptime").textContent = formatDuration(system.uptime_seconds || 0);
  $("#weather").textContent = formatWeather(state.weather);
  $("#last-decision").textContent = system.last_llm_decision || "暂无 AI 建议记录";
  $("#fsm-score").textContent = `score ${formatNumber(system.fsm_score ?? 0)}`;
  $("#profile-active").textContent = profileLabel(system.active_profile);
  $("#active-profile-side").textContent = profileLabel(system.active_profile);

  $$(".fsm-step").forEach((step) => step.classList.toggle("active", step.dataset.fsm === system.fsm_state));

  const pill = $("#connection-pill");
  if (system.degraded) {
    pill.textContent = system.demo_mode ? "Demo 模式" : "降级运行";
    pill.className = "pill warn";
  }
}

function renderProfiles() {
  const active = state.profiles.active_profile || state.system?.active_profile || "balanced";
  const profiles = state.profiles.profiles || {};
  $("#profile-switcher").innerHTML = Object.keys(profiles).map((key) => `
    <button data-profile="${key}" class="${key === active ? "active" : ""}">${profileLabel(key)}</button>
  `).join("");
  $("#profile-switcher").onclick = async (event) => {
    const button = event.target.closest("button[data-profile]");
    if (!button) return;
    try {
      await IotApi.post("/api/v1/system/profile", { profile: button.dataset.profile });
      toast(`已切换到${profileLabel(button.dataset.profile)}模式`, "ok");
      await refreshProfiles();
      await refreshAll();
    } catch (error) {
      toast(`模式切换失败：${error.message}`, "error");
    }
  };

  const config = profiles[active] || {};
  $("#profile-detail").textContent = `风扇温度 >= ${config.fan_on_above_c ?? "--"}°C 或 CO2 >= 1200 ppm，开灯照度 < ${config.light_on_below_lux ?? "--"} Lux，建议亮度 ${config.lighting_brightness ?? "--"}%`;
}

function renderDevices() {
  $("#device-grid").innerHTML = Object.entries(DEVICE_META).map(([key, meta]) => {
    const item = state.devices[key] || {};
    const isOn = Boolean(item.state);
    const mode = item.mode || "auto";
    const brightness = Number(item.brightness || (isOn ? 100 : 0));
    const controls = meta.kind === "brightness"
      ? `
        <div class="brightness-row">
          <input type="range" min="0" max="100" value="${brightness}" data-brightness-slider="${key}">
          <span>${brightness}%</span>
        </div>
        <div class="device-actions">
          <button data-device-action="set_brightness" data-device="${key}" data-value="100">开灯</button>
          <button data-device-action="set_brightness" data-device="${key}" data-value="0">关灯</button>
          <button data-device-action="auto" data-device="${key}">自动</button>
        </div>
      `
      : `
        <div class="device-actions">
          <button data-device-action="on" data-device="${key}">开启</button>
          <button data-device-action="off" data-device="${key}">关闭</button>
          <button data-device-action="auto" data-device="${key}">自动</button>
        </div>
      `;
    return `
      <article class="device-card">
        <div class="device-title">
          <strong>${meta.label}</strong>
          <span class="state-dot ${isOn ? "on" : ""}"></span>
        </div>
        <div class="device-meta">${isOn ? "已开启" : "已关闭"} · ${mode === "manual" ? "手动" : "自动"}${item.trigger ? ` · ${item.trigger}` : ""}</div>
        ${controls}
      </article>
    `;
  }).join("");

  $$("[data-brightness-slider]").forEach((slider) => {
    slider.addEventListener("change", () => controlDevice(slider.dataset.brightnessSlider, "set_brightness", slider.value));
  });
}

function renderAlerts() {
  const alerts = state.alerts || [];
  const banner = $("#alert-banner");
  const modal = $("#smoke-modal");
  if (!alerts.length) {
    banner.classList.add("hidden");
    $("#alerts-list").className = "list-empty";
    $("#alerts-list").textContent = "暂无活动告警";
    modal.classList.add("hidden");
    return;
  }

  banner.classList.remove("hidden");
  banner.textContent = `当前 ${alerts.length} 条活动告警：${alerts.map((item) => alertLabel(item.type)).join("、")}`;
  $("#alerts-list").className = "";
  $("#alerts-list").innerHTML = alerts.map((alert) => `
    <div class="alert-row">
      <strong>${alertLabel(alert.type)}</strong>
      <div class="muted">${alert.message || "传感器超过阈值"} · 当前 ${formatNumber(alert.value)} / 阈值 ${formatNumber(alert.threshold)}</div>
      <div class="device-actions">
        <button data-shortcut="clear_alert" data-alert-type="${alert.type}">解除此告警</button>
      </div>
    </div>
  `).join("");

  const smoke = alerts.find((item) => String(item.type).includes("smoke"));
  if (smoke) {
    $("#smoke-modal-body").textContent = `烟雾值 ${formatNumber(smoke.value)} ppm，阈值 ${formatNumber(smoke.threshold)} ppm。请检查烟雾来源，确认是否存在火情，并按现场预案处理。`;
    modal.classList.remove("hidden");
  }
}

async function controlDevice(device, action, rawValue) {
  const payload = { device, action };
  if (rawValue !== undefined && rawValue !== "") payload.value = Number(rawValue);
  try {
    await IotApi.post("/api/v1/devices/control", payload);
    toast(`${deviceLabel(device)}：${actionLabel(action, rawValue)}`, "ok");
    await refreshAll();
    await refreshEvents();
  } catch (error) {
    toast(`${deviceLabel(device)}控制失败：${error.message}`, "error");
  }
}

async function runShortcutFromElement(element) {
  const action = element.dataset.shortcut;
  if (action === "set_fsm") {
    await shortcut("set_fsm", { state: element.dataset.state }, `FSM 已切到 ${element.dataset.state}`);
  } else if (action === "clear_fsm") {
    await shortcut("clear_fsm", {}, "已清除 FSM 覆盖");
  } else if (action === "clear_alert") {
    await shortcut("clear_alert", { type: element.dataset.alertType || "all" }, "已请求解除告警");
  }
}

async function shortcut(action, params, successMessage) {
  try {
    await IotApi.post("/api/v1/shortcuts/action", { action, params });
    toast(successMessage || "快捷动作已执行", "ok");
    await refreshAll();
    await refreshEvents();
  } catch (error) {
    toast(`快捷动作失败：${error.message}`, "error");
  }
}

async function loadAssistant() {
  try {
    const [prompts, history] = await Promise.all([
      IotApi.get("/api/v1/assistant/quick-prompts"),
      IotApi.get("/api/v1/assistant/history?limit=12"),
    ]);
    $("#quick-prompts").innerHTML = (prompts.prompts || []).map((prompt) => `
      <button data-prompt="${escapeHtml(prompt.text)}">${prompt.text}</button>
    `).join("");
    $("#quick-prompts").onclick = (event) => {
      const button = event.target.closest("button[data-prompt]");
      if (!button) return;
      $("#chat-input").value = button.dataset.prompt;
      $("#chat-form").requestSubmit();
    };
    if (history.messages?.length) {
      $("#chat-log").innerHTML = "";
      history.messages.forEach((message) => addChatMessage(message.role, message.message));
    }
  } catch (error) {
    $("#quick-prompts").innerHTML = `<div class="muted">快捷提问加载失败：${error.message}</div>`;
  }
}

async function sendChat(event) {
  event.preventDefault();
  const input = $("#chat-input");
  const message = input.value.trim();
  if (!message || state.chatAbort) return;

  input.value = "";
  addChatMessage("user", message);
  const assistantNode = addChatMessage("assistant", "");
  state.chatAbort = new AbortController();
  $("#stop-chat").classList.remove("hidden");

  try {
    await IotApi.streamChat(message, (token) => {
      assistantNode.querySelector(".chat-content").textContent += token;
      $("#chat-log").scrollTop = $("#chat-log").scrollHeight;
    }, state.chatAbort.signal);
  } catch (error) {
    if (error.name !== "AbortError") {
      assistantNode.querySelector(".chat-content").textContent += `\n[请求失败] ${error.message}`;
    }
  } finally {
    state.chatAbort = null;
    $("#stop-chat").classList.add("hidden");
  }
}

function stopChat() {
  if (state.chatAbort) state.chatAbort.abort();
}

function addChatMessage(role, message) {
  const node = document.createElement("div");
  node.className = `chat-message ${role}`;
  node.innerHTML = `<div class="chat-role">${role === "user" ? "你" : "AI 助手"}</div><div class="chat-content"></div>`;
  node.querySelector(".chat-content").textContent = message || "";
  $("#chat-log").appendChild(node);
  $("#chat-log").scrollTop = $("#chat-log").scrollHeight;
  return node;
}

function startVoiceInput() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    toast("当前浏览器不支持语音识别", "error");
    return;
  }
  const recognition = new SpeechRecognition();
  recognition.lang = "zh-CN";
  recognition.interimResults = false;
  recognition.onstart = () => $("#voice-state").textContent = "正在聆听";
  recognition.onerror = () => {
    $("#voice-state").textContent = "语音失败";
    toast("语音识别失败，请重试", "error");
  };
  recognition.onend = () => $("#voice-state").textContent = "语音待命";
  recognition.onresult = (event) => {
    $("#chat-input").value = event.results[0][0].transcript;
  };
  recognition.start();
}

async function loadHistory() {
  const selected = Array.from(state.selectedSensors);
  if (!selected.length) {
    state.historyData = {};
    drawHistoryChart();
    return;
  }

  const end = new Date();
  const start = new Date(end.getTime() - state.historyRangeHours * 3600 * 1000);
  const pairs = await Promise.allSettled(selected.map(async (sensor) => {
    const url = `/api/v1/sensors/history?sensor=${encodeURIComponent(sensor)}&start=${encodeURIComponent(toLocalIso(start))}&end=${encodeURIComponent(toLocalIso(end))}`;
    const payload = await IotApi.get(url);
    return [sensor, payload.data || []];
  }));
  state.historyData = {};
  pairs.forEach((result) => {
    if (result.status === "fulfilled") state.historyData[result.value[0]] = result.value[1];
  });
  drawHistoryChart();
}

async function loadEnergy() {
  try {
    const [summary, series] = await Promise.all([
      IotApi.get(`/api/v1/energy/summary?range=${state.energyRange}`),
      IotApi.get(`/api/v1/energy/timeseries?range=${state.energyRange}`),
    ]);
    state.energySummary = summary;
    state.energySeries = series.data || [];
    renderEnergy();
  } catch (error) {
    toast(`能耗数据加载失败：${error.message}`, "error");
  }
}

function renderEnergy() {
  const summary = state.energySummary || {};
  const comparison = summary.comparison || {};
  $("#energy-kpis").innerHTML = [
    ["累计耗电", `${summary.total_energy_kwh ?? "--"} kWh`],
    ["风扇运行", formatRuntimeMinutes(summary.fan_runtime_minutes)],
    ["平均功率", `${summary.avg_power_w ?? "--"} W`],
    ["碳减排", `${summary.co2_reduction_kg ?? "--"} kg`],
  ].map(([label, value]) => `<div class="kpi-card"><span class="metric-label">${label}</span><strong>${value}</strong></div>`).join("");

  drawBarChart($("#energy-compare"), [
    { label: "自动模式", value: Number(comparison.ai_mode_kwh || 0), color: "#22d3ee" },
    { label: "常开模式", value: Number(comparison.always_on_kwh || 0), color: "#ff9f43" },
  ], "kWh");
  drawLineChart($("#power-chart"), [{ label: "风扇功率", color: "#40d383", data: state.energySeries.map((row) => ({ ts: row.ts, value: row.fan_power_w })) }], "W");

  const saving = Number(comparison.saving_percent || 0);
  $("#energy-donut").style.background = `conic-gradient(var(--cyan) 0 ${Math.max(5, saving)}%, var(--green) ${Math.max(5, saving)}% 100%)`;
  $("#energy-donut-label").innerHTML = `节能率 <strong>${formatNumber(saving)}%</strong><br>曲线点数 ${state.energySeries.length}<br>最后更新 ${formatTime(new Date().toISOString())}`;
}

function drawHistoryChart() {
  const series = Object.entries(state.historyData).map(([sensor, rows]) => ({
    label: SENSOR_META[sensor]?.label || sensor,
    color: SENSOR_META[sensor]?.accent || "#fff",
    data: rows.map((row) => ({ ts: row.ts, value: row.value })),
  }));
  drawLineChart($("#history-chart"), series, "");
}

function drawLineChart(canvas, series, unit) {
  const ctx = canvas.getContext("2d");
  fitCanvas(canvas);
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "rgba(255,255,255,.62)";
  ctx.font = "13px Microsoft YaHei";

  const points = series.flatMap((item) => item.data.map((row) => ({ ...row, tsValue: new Date(row.ts).getTime(), value: Number(row.value) }))).filter((row) => Number.isFinite(row.value) && Number.isFinite(row.tsValue));
  if (!points.length) {
    ctx.fillText("暂无可绘制数据", 24, 34);
    return;
  }

  const pad = { left: 52, right: 24, top: 28, bottom: 42 };
  const minX = Math.min(...points.map((point) => point.tsValue));
  const maxX = Math.max(...points.map((point) => point.tsValue));
  const minY = Math.min(...points.map((point) => point.value));
  const maxY = Math.max(...points.map((point) => point.value));
  const ySpan = maxY - minY || 1;
  const xSpan = maxX - minX || 1;
  const x = (ts) => pad.left + ((ts - minX) / xSpan) * (width - pad.left - pad.right);
  const y = (value) => height - pad.bottom - ((value - minY) / ySpan) * (height - pad.top - pad.bottom);

  drawGrid(ctx, width, height, pad, minY, maxY, unit);
  series.forEach((item, index) => {
    const rows = item.data.map((row) => ({ ts: new Date(row.ts).getTime(), value: Number(row.value) })).filter((row) => Number.isFinite(row.ts) && Number.isFinite(row.value));
    if (!rows.length) return;
    ctx.strokeStyle = item.color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    rows.forEach((row, rowIndex) => {
      const px = x(row.ts);
      const py = y(row.value);
      if (rowIndex === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    });
    ctx.stroke();
    ctx.fillStyle = item.color;
    ctx.fillRect(pad.left + index * 135, 8, 10, 10);
    ctx.fillStyle = "rgba(255,255,255,.72)";
    ctx.fillText(item.label, pad.left + 16 + index * 135, 18);
  });
}

function drawBarChart(canvas, bars, unit) {
  const ctx = canvas.getContext("2d");
  fitCanvas(canvas);
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  const max = Math.max(0.01, ...bars.map((bar) => bar.value));
  const pad = { left: 52, right: 30, top: 26, bottom: 48 };
  drawGrid(ctx, width, height, pad, 0, max, unit);
  const barWidth = Math.min(120, (width - pad.left - pad.right) / bars.length * 0.42);
  bars.forEach((bar, index) => {
    const slot = (width - pad.left - pad.right) / bars.length;
    const x = pad.left + slot * index + slot / 2 - barWidth / 2;
    const h = (bar.value / max) * (height - pad.top - pad.bottom);
    const y = height - pad.bottom - h;
    ctx.fillStyle = bar.color;
    ctx.fillRect(x, y, barWidth, h);
    ctx.fillStyle = "rgba(255,255,255,.75)";
    ctx.font = "13px Microsoft YaHei";
    ctx.fillText(bar.label, x - 8, height - 20);
    ctx.fillText(`${formatNumber(bar.value)} ${unit}`, x - 8, y - 8);
  });
}

function drawGrid(ctx, width, height, pad, minY, maxY, unit) {
  ctx.strokeStyle = "rgba(255,255,255,.08)";
  ctx.fillStyle = "rgba(255,255,255,.42)";
  ctx.lineWidth = 1;
  ctx.font = "12px Microsoft YaHei";
  for (let i = 0; i <= 4; i += 1) {
    const y = pad.top + ((height - pad.top - pad.bottom) / 4) * i;
    const value = maxY - ((maxY - minY) / 4) * i;
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(width - pad.right, y);
    ctx.stroke();
    ctx.fillText(`${formatNumber(value)}${unit ? ` ${unit}` : ""}`, 8, y + 4);
  }
}

function fitCanvas(canvas) {
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(320, Math.floor(rect.width * ratio));
  canvas.height = Math.max(240, Math.floor(rect.height * ratio));
  canvas.getContext("2d").setTransform(ratio, 0, 0, ratio, 0, 0);
  canvas.width = Math.max(320, Math.floor(rect.width));
  canvas.height = Math.max(240, Math.floor(rect.height));
}

function resizeCharts() {
  drawHistoryChart();
  renderEnergy();
}

function exportHistoryCsv() {
  const rows = [["sensor", "timestamp", "value"]];
  Object.entries(state.historyData).forEach(([sensor, data]) => {
    data.forEach((row) => rows.push([sensor, row.ts, row.value]));
  });
  const csv = rows.map((row) => row.map((cell) => `"${String(cell ?? "").replace(/"/g, '""')}"`).join(",")).join("\n");
  downloadBlob(csv, "sensor-history.csv", "text/csv;charset=utf-8");
}

function exportHistoryPng() {
  const link = document.createElement("a");
  link.download = "sensor-history.png";
  link.href = $("#history-chart").toDataURL("image/png");
  link.click();
}

function downloadBlob(content, filename, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function handleKeyboardShortcut(event) {
  const tag = event.target.tagName;
  if (["INPUT", "TEXTAREA", "SELECT"].includes(tag)) return;
  const map = {
    "1": ["set_fsm", { state: "VACANT" }, "FSM -> VACANT"],
    "2": ["set_fsm", { state: "ARRIVING" }, "FSM -> ARRIVING"],
    "3": ["set_fsm", { state: "OCCUPIED" }, "FSM -> OCCUPIED"],
    "4": ["set_fsm", { state: "LEAVING" }, "FSM -> LEAVING"],
    "0": ["clear_fsm", {}, "已清除 FSM 覆盖"],
    n: ["trigger_alert", { type: "noise_warning" }, "已触发噪声告警"],
    N: ["clear_alert", { type: "noise_warning" }, "已解除噪声告警"],
    s: ["trigger_alert", { type: "smoke_warning" }, "已触发烟雾告警"],
    S: ["clear_alert", { type: "smoke_warning" }, "已解除烟雾告警"],
    a: ["clear_alert", {}, "已清除全部告警"],
    d: ["toggle_demo_mode", {}, "已切换 Demo / 真实模式"],
    f: ["control_device", { device: "fan", device_action: "on" }, "风扇已开启"],
    F: ["control_device", { device: "fan", device_action: "off" }, "风扇已关闭"],
    r: ["control_device", { device: "fan", device_action: "auto" }, "风扇恢复自动"],
    b: ["control_device", { device: "buzzer", device_action: "on" }, "蜂鸣器已开启"],
    B: ["control_device", { device: "buzzer", device_action: "off" }, "蜂鸣器已关闭"],
    w: ["control_device", { device: "warning_led", device_action: "on" }, "警示灯已开启"],
    W: ["control_device", { device: "warning_led", device_action: "off" }, "警示灯已关闭"],
    l: ["control_device", { device: "lighting_led", device_action: "set_brightness", value: 100 }, "照明 LED 已开启"],
    L: ["control_device", { device: "lighting_led", device_action: "set_brightness", value: 0 }, "照明 LED 已关闭"],
    R: ["control_device", { device: "lighting_led", device_action: "auto" }, "照明 LED 恢复自动"],
  };
  const item = map[event.key];
  if (!item) return;
  event.preventDefault();
  shortcut(item[0], item[1], item[2]);
}

function renderAssistantContext() {
  const sensors = state.latest?.data || {};
  const system = state.system || {};
  $("#assistant-context").innerHTML = `
    FSM：${system.fsm_state || "--"} / ${aiModeLabel(system.ai_mode)}<br>
    温度：${formatNumber(sensors.temperature?.value)}°C，CO2：${formatNumber(sensors.co2?.value)} ppm<br>
    告警：${state.alerts.length || 0} 条，模式：${profileLabel(system.active_profile)}
  `;
}

function setConnection(ok) {
  const pill = $("#connection-pill");
  pill.textContent = ok ? `已连接 ${IotApi.base}` : "后端未连接";
  pill.className = ok ? "pill ok" : "pill danger";
}

function setActiveButton(containerSelector, activeButton) {
  $$(`${containerSelector} button`).forEach((button) => button.classList.toggle("active", button === activeButton));
}

function toast(message, type = "") {
  const node = document.createElement("div");
  node.className = `toast ${type}`;
  node.textContent = message;
  $("#toast-root").appendChild(node);
  setTimeout(() => node.remove(), 3200);
}

function tickClock() {
  $("#clock").textContent = new Date().toLocaleString("zh-CN", { hour12: false });
}

function numberOrNull(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatNumber(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "--";
  if (Math.abs(parsed) >= 100) return parsed.toFixed(0);
  if (Math.abs(parsed) >= 10) return parsed.toFixed(1);
  return parsed.toFixed(2);
}

function formatDuration(seconds) {
  const total = Number(seconds) || 0;
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = Math.floor(total % 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function formatRuntimeMinutes(minutes) {
  const total = Number(minutes);
  if (!Number.isFinite(total)) return "--";
  const rounded = Math.max(0, Math.round(total));
  const h = Math.floor(rounded / 60);
  const m = rounded % 60;
  if (h > 0 && m > 0) return `${h}小时${m}分钟`;
  if (h > 0) return `${h}小时`;
  return `${m}分钟`;
}

function formatTime(raw) {
  if (!raw) return "--";
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return raw;
  return date.toLocaleTimeString("zh-CN", { hour12: false });
}

function normalizeUnit(unit) {
  return String(unit || "").replace("掳C", "°C").replace("碌g/m鲁", "µg/m³");
}

function toLocalIso(date) {
  const offsetMs = date.getTimezoneOffset() * 60000;
  const local = new Date(date.getTime() - offsetMs);
  const offsetMinutes = -date.getTimezoneOffset();
  const sign = offsetMinutes >= 0 ? "+" : "-";
  const abs = Math.abs(offsetMinutes);
  const hh = String(Math.floor(abs / 60)).padStart(2, "0");
  const mm = String(abs % 60).padStart(2, "0");
  return `${local.toISOString().slice(0, 19)}${sign}${hh}:${mm}`;
}

function formatWeather(weather) {
  if (!weather) return "天气加载中";
  if (!weather.enabled) {
    if (weather.source === "disabled") return "天气未配置";
    if (weather.status) return `天气获取失败 ${weather.status}`;
    return weather.message ? `天气获取失败：${weather.message}` : "天气获取失败";
  }
  const temp = weather.temperature === null || weather.temperature === undefined ? "--" : `${formatNumber(weather.temperature)}°C`;
  const humidity = weather.humidity === null || weather.humidity === undefined ? "--" : `${weather.humidity}%RH`;
  return `${weather.city || "室外"} ${weather.condition || ""} ${temp} / ${humidity}`;
}

function deviceLabel(device) {
  return DEVICE_META[device]?.label || device || "--";
}

function profileLabel(profile) {
  return PROFILE_LABELS[profile] || profile || "--";
}

function aiModeLabel(mode) {
  const map = {
    fsm_fallback: "FSM 规则",
    llm_decision: "大模型建议",
    llm_advice: "大模型建议",
    emergency_override: "安全优先",
    manual_override: "手动覆盖",
  };
  return map[mode] || mode || "--";
}

function alertLabel(type) {
  const raw = String(type || "");
  if (raw.includes("smoke")) return "烟雾告警";
  if (raw.includes("noise")) return "噪声告警";
  return raw || "告警";
}

function actionLabel(action, value) {
  if (action === "on") return "开启";
  if (action === "off") return "关闭";
  if (action === "auto") return "恢复自动";
  if (action === "set_brightness") return `亮度 ${value}%`;
  return action;
}

function formatEventValue(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[char]));
}

function debounce(fn, wait) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
}
