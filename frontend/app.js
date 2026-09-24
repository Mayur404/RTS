"use strict";

const $ = (id) => document.getElementById(id);
const svgNS = "http://www.w3.org/2000/svg";
const state = {
  live: null, playing: false, busy: false, speed: 1, timer: null,
  selectedNode: "Device_1", history: [], eventCount: 0, experiment: null,
  graphMode: "fleet", nodePositions: { fleet: {}, interaction: {} }, draggingNode: null,
  clockDisplayed: 0, clockFrameTime: null, lastStepWall: 0, generation: 0,
  graphSnapshotWall: 0,
};

function element(tag, className, textValue) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (textValue !== undefined) node.textContent = textValue;
  return node;
}

function svg(tag, attrs = {}, textValue) {
  const node = document.createElementNS(svgNS, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
  if (textValue !== undefined) node.textContent = textValue;
  return node;
}

const deviceTypeNames = {
  drone: "Aerial drone", server: "GPU edge server", rover: "Ground rover",
  arm: "Robotic arm", chip: "Edge TPU", station: "Ground station",
};

function deviceKind(node) {
  if (node?.hardware === "Ground-Station") return "station";
  return Object.hasOwn(deviceTypeNames, node?.node_type) ? node.node_type : "server";
}

function deviceIcon(node) {
  return `/static/icons/${deviceKind(node)}.svg`;
}

function renderDeviceKey(nodes) {
  const root = $("device-key"); root.replaceChildren();
  const seen = new Set();
  for (const node of Object.values(nodes || {})) {
    const kind = deviceKind(node);
    if (seen.has(kind)) continue;
    seen.add(kind);
    const item = element("span", "device-key-item");
    const icon = element("img"); icon.src = deviceIcon(node); icon.alt = ""; icon.setAttribute("aria-hidden", "true");
    item.append(icon, element("span", "", deviceTypeNames[kind]));
    root.append(item);
  }
}

function displayNumber(value, decimals = 0, suffix = "") {
  return typeof value === "number" && Number.isFinite(value)
    ? `${value.toFixed(decimals)}${suffix}` : "—";
}

function showToast(message, isError = false) {
  const toast = $("toast");
  toast.textContent = message;
  toast.classList.toggle("is-error", isError);
  toast.classList.add("is-visible");
  clearTimeout(showToast.timeout);
  showToast.timeout = setTimeout(() => toast.classList.remove("is-visible"), 4300);
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  let body;
  try { body = await response.json(); } catch { body = {}; }
  if (!response.ok) {
    const detail = typeof body.detail === "string" ? body.detail : `Request failed (${response.status})`;
    throw new Error(detail);
  }
  return body;
}

function setApiStatus(online) {
  $("api-dot").className = `status-dot ${online ? "online" : "error"}`;
  $("api-status").textContent = online ? "API connected" : "API unavailable";
}

function switchView(viewName) {
  document.querySelectorAll(".view").forEach((view) => {
    view.classList.toggle("is-visible", view.id === `view-${viewName}`);
  });
  document.querySelectorAll(".nav-item").forEach((button) => {
    const active = button.dataset.view === viewName;
    button.classList.toggle("is-active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  $("view-title").textContent = {
    live: "Live simulation", experiments: "Experiments", models: "Models", evidence: "Evidence guide", verification: "Verification",
  }[viewName];
  if (viewName === "models") loadModels();
  window.location.hash = viewName;
}

function liveConfig() {
  const seed = Number($("live-seed").value);
  if (!Number.isInteger(seed) || seed < 0) throw new Error("Seed must be a non-negative integer");
  return {
    fleet_size: Number($("fleet-size").value), seed,
    horizon_ms: Number($("live-horizon").value), enable_contention: true,
    fault_time_ms: 25, contention_magnitude: 0.9, target_node: "Device_1",
  };
}

function applyResearchLabels() {
  const policy = $("exp-policy");
  if (policy) {
    const full = [...policy.options].find((option) => option.value === "rts_predictive");
    const gnnOnly = [...policy.options].find((option) => option.value === "rts_predictive_gnn");
    if (full) full.textContent = "PredictiveRuntime · full bundled policy";
    if (gnnOnly) gnnOnly.textContent = "PredictiveRuntime · GNN with static remote estimate";
  }
  const explainer = document.querySelector(".model-explainer p");
  if (explainer) {
    explainer.textContent = "The seeded experiment and exploratory live comparison load the simulation-calibrated GNN and evaluated federated bundle. Neither bundle is a hardware timing certificate.";
  }
  const livePolicyTag = document.querySelector(".metric-primary .tag");
  if (livePolicyTag) livePolicyTag.textContent = "BUNDLED GNN + FL";
}

function stopPlayback(completed = false) {
  state.playing = false;
  if (state.timer) clearInterval(state.timer);
  state.timer = null;
  $("play-icon").textContent = "▶";
  $("play-label").textContent = completed ? "Run complete" : state.live?.current_time_ms ? "Resume" : "Start simulation";
  $("run-status").textContent = completed ? "RUN COMPLETE" : "PAUSED";
  $("play-button").disabled = completed;
  if (state.live) {
    state.clockDisplayed = state.live.current_time_ms;
    renderClock();
  }
}

function renderClock() {
  const t = state.clockDisplayed;
  const horizon = state.live?.horizon_ms || 1;
  $("clock-value").replaceChildren(document.createTextNode(displayNumber(t, 3, " ")), element("small", "", "ms"));
  $("topbar-clock").textContent = `t = ${displayNumber(t, 3)} ms`;
  const percentage = 100 * ((t % horizon) / horizon);
  $("run-progress").setAttribute("aria-valuenow", String(Math.round(percentage)));
  $("progress-fill").style.width = `${percentage}%`;
}

function animateClock(frameTime) {
  if (state.clockFrameTime != null && state.playing && state.live) {
    const elapsed = Math.min(100, frameTime - state.clockFrameTime);
    state.clockDisplayed = Math.min(state.live.current_time_ms, state.clockDisplayed + elapsed * state.speed);
    renderClock();
  }
  animateGraphActivity(frameTime);
  state.clockFrameTime = frameTime;
  requestAnimationFrame(animateClock);
}

function animateGraphActivity(frameTime) {
  document.querySelectorAll(".live-packet").forEach((packet) => {
    const x1 = Number(packet.dataset.x1), y1 = Number(packet.dataset.y1);
    const x2 = Number(packet.dataset.x2), y2 = Number(packet.dataset.y2);
    const base = Number(packet.dataset.progress || 0) / 100;
    const elapsed = Math.max(0, frameTime - state.graphSnapshotWall);
    const progress = Math.min(.985, base + elapsed / 1500);
    packet.setAttribute("cx", String(x1 + (x2 - x1) * progress));
    packet.setAttribute("cy", String(y1 + (y2 - y1) * progress));
  });
}

async function startLive() {
  const generation = ++state.generation;
  stopPlayback();
  state.busy = true;
  $("run-status").textContent = "PREPARING RUN";
  try {
    const snapshot = await request("/api/live/start", { method: "POST", body: JSON.stringify(liveConfig()) });
    if (generation !== state.generation) return;
    state.history = [];
    state.eventCount = 0;
    state.nodePositions = { fleet: {}, interaction: {} };
    state.clockDisplayed = 0;
    $("event-list").replaceChildren(element("div", "empty-state", "Events will appear as the simulation advances."));
    state.live = snapshot;
    state.selectedNode = "Device_1";
    updateLive(snapshot);
    $("play-label").textContent = "Start simulation";
    $("run-status").textContent = "READY TO RUN";
    $("play-button").disabled = false;
    setApiStatus(true);
  } catch (error) {
    if (generation !== state.generation) return;
    setApiStatus(false);
    $("run-status").textContent = "CONNECTION ERROR";
    showToast(error.message, true);
  } finally { if (generation === state.generation) state.busy = false; }
}

async function stepLive(delta = 25) {
  if (state.busy || !state.live) return;
  const generation = state.generation;
  state.busy = true;
  try {
    const snapshot = await request("/api/live/step", { method: "POST", body: JSON.stringify({ delta_ms: delta, session_id: state.live.session_id }) });
    if (generation !== state.generation) return;
    state.live = snapshot;
    updateLive(snapshot);
  } catch (error) {
    if (generation !== state.generation) return;
    stopPlayback();
    showToast(error.message, true);
  } finally { if (generation === state.generation) state.busy = false; }
}

function togglePlayback() {
  if (!state.live) return;
  if (state.playing) { stopPlayback(); return; }
  state.playing = true;
  $("play-icon").textContent = "Ⅱ";
  $("play-label").textContent = "Pause simulation";
  $("run-status").textContent = "SIMULATION RUNNING";
  state.lastStepWall = performance.now();
  state.timer = setInterval(() => {
    if (state.busy) return;
    const now = performance.now();
    const delta = Math.min(200, Math.max(1, (now - state.lastStepWall) * state.speed));
    state.lastStepWall = now;
    stepLive(delta);
  }, 40);
}

async function injectFault(kind) {
  if (!state.live) return showToast("Start a simulation first", true);
  const configs = {
    gpu: { target_node: "Device_1", cpu_load: 0.65, gpu_load: 0.95, duration_ms: 180, network_delay_ms: 12 },
    peer: { target_node: "Device_2", cpu_load: 0.98, gpu_load: 0.98, duration_ms: 180, network_delay_ms: 15 },
    network: { target_node: "Device_1", cpu_load: 0, gpu_load: 0, duration_ms: 180, network_delay_ms: 15 },
    thermal: { target_node: "Device_1", cpu_load: 0.98, gpu_load: 0.98, duration_ms: 250, network_delay_ms: 12 },
  };
  const config = configs[kind];
  try {
    const result = await request("/api/live/inject_fault", { method: "POST", body: JSON.stringify({ ...config, session_id: state.live.session_id }) });
    showToast(`Fault added at ${displayNumber(result.current_time_ms, 3, " ms")} on ${result.target_node}`);
  } catch (error) { showToast(error.message, true); }
}

function updateLive(snapshot) {
  const t = snapshot.current_time_ms;
  const horizon = snapshot.horizon_ms || 1;
  state.graphSnapshotWall = performance.now();
  if (!state.playing || t < state.clockDisplayed) state.clockDisplayed = t;
  renderClock();
  $("clock-sub").textContent = `Live state ${displayNumber(t, 3)} ms · Seed ${$("live-seed").value} · ${snapshot.fleet_size} nodes · rolling non-evidence view`;
  $("run-signal").className = "signal online";
  const a = snapshot.metrics_gg || {}, b = snapshot.metrics_edf || {};
  const hasTime = t > 0;
  $("primary-dmr").textContent = hasTime ? displayNumber(a.dmr_pct, 2, "%") : "—";
  $("baseline-dmr").textContent = hasTime ? displayNumber(b.dmr_pct, 2, "%") : "—";
  $("primary-misses").textContent = `${displayNumber(a.missed)} misses`;
  $("primary-critical").textContent = `${displayNumber(a.critical_misses)} critical`;
  $("baseline-misses").textContent = `${displayNumber(b.missed)} misses`;
  $("baseline-critical").textContent = `${displayNumber(b.critical_misses)} critical`;
  $("action-count").textContent = displayNumber(a.offloads);
  $("fallback-count").textContent = `${displayNumber(a.fallbacks)} fallbacks`;
  $("completed-count").textContent = `${displayNumber(a.completed)} on-time`;
  $("response-max").textContent = a.completed > 0 ? displayNumber(a.wcrt_ms, 1, " ms") : "—";
  $("active-packets").textContent = `${(snapshot.active_offloads || []).length} active offloads`;
  if (hasTime) {
    state.history.push({ t, primary: a.dmr_pct ?? 0, baseline: b.dmr_pct ?? 0 });
    if (state.history.length > 160) state.history.shift();
  }
  renderTrend();
  renderTopology(snapshot);
  renderDeviceKey(snapshot.nodes);
  renderDag(snapshot);
  renderInteraction(snapshot);
  renderNode(snapshot.nodes?.[state.selectedNode]);
  for (const event of snapshot.step_events || []) renderLiveEvent(event);
}

function topologyPositions(count) {
  if (count <= 4) return [[220, 145], [680, 145], [220, 395], [680, 395]];
  if (count <= 6) return [[195, 145], [705, 145], [155, 375], [745, 375], [450, 90], [450, 445]];
  return Array.from({ length: count }, (_, index) => {
    const angle = -Math.PI / 2 + index * 2 * Math.PI / count;
    return [450 + 330 * Math.cos(angle), 270 + 205 * Math.sin(angle)];
  });
}

function graphPositions(keys, mode) {
  const saved = state.nodePositions[mode];
  const defaults = mode === "fleet" ? topologyPositions(keys.length) : keys.map((_, index) => {
    const angle = -Math.PI / 2 + index * 2 * Math.PI / keys.length;
    return [450 + 305 * Math.cos(angle), 270 + 186 * Math.sin(angle)];
  });
  keys.forEach((id, index) => { if (!saved[id]) saved[id] = defaults[index]; });
  return saved;
}

function beginNodeDrag(event, id, root, mode) {
  if (event.button !== 0) return;
  event.preventDefault();
  selectNode(id);
  state.draggingNode = { id, mode, pointerId: event.pointerId };
  root.setPointerCapture(event.pointerId);
}

function moveNodeFromPointer(event, root, mode) {
  const active = state.draggingNode;
  if (!active || active.mode !== mode || active.pointerId !== event.pointerId || !state.live) return;
  const point = root.createSVGPoint();
  point.x = event.clientX; point.y = event.clientY;
  const view = point.matrixTransform(root.getScreenCTM().inverse());
  const width = mode === "fleet" ? 116 : 73;
  const height = mode === "fleet" ? 58 : 55;
  state.nodePositions[mode][active.id] = [
    Math.max(width, Math.min(900 - width, view.x)),
    Math.max(height, Math.min(540 - height, view.y)),
  ];
  if (mode === "fleet") renderTopology(state.live);
  else renderInteraction(state.live);
}

function nudgeNode(id, mode, dx, dy) {
  const position = state.nodePositions[mode][id];
  if (!position) return;
  const margin = mode === "fleet" ? 116 : 55;
  state.nodePositions[mode][id] = [Math.max(margin, Math.min(900 - margin, position[0] + dx)), Math.max(58, Math.min(482, position[1] + dy))];
  selectNode(id);
}

function wireGraphNode(group, id, root, mode) {
  group.addEventListener("click", () => selectNode(id));
  group.addEventListener("pointerdown", (event) => beginNodeDrag(event, id, root, mode));
  group.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectNode(id); }
    const moves = { ArrowLeft: [-15, 0], ArrowRight: [15, 0], ArrowUp: [0, -15], ArrowDown: [0, 15] };
    if (moves[event.key]) { event.preventDefault(); nudgeNode(id, mode, ...moves[event.key]); }
  });
}

function renderTopology(snapshot) {
  const root = $("topology-svg");
  root.replaceChildren();
  $("topology-empty").hidden = true;
  const nodes = snapshot.nodes || {};
  const keys = Object.keys(nodes);
  const coordinates = graphPositions(keys, "fleet");
  for (const link of snapshot.links || []) {
    const from = coordinates[link.source], to = coordinates[link.target];
    if (!from || !to) continue;
    const color = link.quality === "red" ? "#dc6b72" : link.quality === "amber" ? "#d5a54d" : "#b8cad7";
    const active = (snapshot.active_offloads || []).some((packet) =>
      (packet.source === link.source && packet.target === link.target) ||
      (packet.source === link.target && packet.target === link.source));
    const line = svg("line", { x1: from[0], y1: from[1], x2: to[0], y2: to[1], stroke: active ? "#080707" : color, "stroke-width": active ? 4 : 2, "stroke-dasharray": "6 7" });
    if (active) line.classList.add("live-link");
    root.append(line);
  }
  for (const packet of snapshot.active_offloads || []) {
    const from = coordinates[packet.source], to = coordinates[packet.target];
    if (!from || !to) continue;
    const dot = svg("circle", { cx: from[0], cy: from[1], r: 9, fill: "#ebff00", stroke: "#000", "stroke-width": 3 });
    dot.classList.add("live-packet");
    Object.assign(dot.dataset, { x1: from[0], y1: from[1], x2: to[0], y2: to[1], progress: packet.progress_pct || 0 });
    root.append(dot);
  }
  for (const [id, node] of Object.entries(nodes)) {
    const [x, y] = coordinates[id];
    const group = svg("g", { role: "button", tabindex: 0, "aria-label": `${node.name}, ${node.status}. Drag or use arrow keys to move in this view.` });
    group.classList.add("draggable-node");
    if ((node.running_tasks || []).length) group.classList.add("node-running");
    const stressed = node.is_overloaded || node.status === "OVERLOADED";
    const color = stressed ? "#dc6b72" : node.fallback_active ? "#cf993c" : "#0f8a93";
    const selected = id === state.selectedNode;
    group.append(svg("rect", { x: x - 115, y: y - 52, width: 230, height: 104, rx: 16, fill: selected ? "#e9f8f7" : "#fff", stroke: selected ? color : "#cddbe5", "stroke-width": selected ? 3 : 1.5 }));
    group.append(svg("image", { href: deviceIcon(node), x: x - 103, y: y - 31, width: 62, height: 62, "pointer-events": "none" }));
    const statusLabel = stressed ? "STRESSED" : node.fallback_active ? "FALLBACK" : "NOMINAL";
    group.append(svg("rect", { x: x + 35, y: y - 43, width: 70, height: 17, rx: 8, fill: color, opacity: .14 }));
    group.append(svg("text", { x: x + 70, y: y - 31, fill: color, "text-anchor": "middle", "font-size": 8, "font-weight": 700 }, statusLabel));
    group.append(svg("text", { x: x - 29, y: y - 28, fill: "#183048", "font-size": 15, "font-weight": 700 }, id.replace("_", " ")));
    group.append(svg("text", { x: x - 29, y: y - 7, fill: color, "font-size": 11, "font-weight": 700 }, deviceTypeNames[deviceKind(node)]));
    const activity = (node.running_tasks || []).length
      ? `RUNNING: ${node.running_tasks[0]}`
      : node.queue_len ? `QUEUED: ${node.active_task}` : "IDLE";
    group.append(svg("text", { x: x - 29, y: y + 9, fill: (node.running_tasks || []).length ? "#080707" : "#63798d", "font-size": 10, "font-weight": (node.running_tasks || []).length ? 800 : 400 }, activity));
    const cpu = Math.max(0, Math.min(100, Number(node.cpu) || 0));
    const gpu = Math.max(0, Math.min(100, Number(node.gpu) || 0));
    group.append(svg("rect", { x: x - 29, y: y + 29, width: 92, height: 5, rx: 3, fill: "#e0e8ee" }));
    group.append(svg("rect", { x: x - 29, y: y + 29, width: 92 * cpu / 100, height: 5, rx: 3, fill: "#0f8a93" }));
    group.append(svg("rect", { x: x - 29, y: y + 41, width: 92, height: 5, rx: 3, fill: "#e0e8ee" }));
    group.append(svg("rect", { x: x - 29, y: y + 41, width: 92 * gpu / 100, height: 5, rx: 3, fill: "#537dc6" }));
    group.append(svg("text", { x: x + 69, y: y + 35, fill: "#526a7d", "font-size": 9 }, `C ${Math.round(cpu)}%`));
    group.append(svg("text", { x: x + 69, y: y + 47, fill: "#526a7d", "font-size": 9 }, `G ${Math.round(gpu)}%`));
    wireGraphNode(group, id, root, "fleet");
    root.append(group);
  }
}

function selectNode(id) {
  state.selectedNode = id;
  if (state.live) {
    renderTopology(state.live);
    renderInteraction(state.live);
    renderDag(state.live);
    renderNode(state.live.nodes?.[id]);
  }
}

function setGraphMode(mode) {
  state.graphMode = mode;
  for (const name of ["fleet", "dag", "interaction"]) {
    $(`${name === "fleet" ? "topology" : name}-svg`).hidden = name !== mode;
  }
  document.querySelectorAll(".graph-tab").forEach((button) => {
    const active = button.dataset.graph === mode;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
  });
  $("graph-description").textContent = {
    fleet: "Drag nodes to arrange this view. Their simulated positions and links stay unchanged. Scroll sideways on small screens.",
    dag: "Follows the oldest active pipeline job until it completes. Arrows are real precedence constraints and every state comes from simulator tasks.",
    interaction: "Configured peer links and in-flight offloads from the selected run. Drag nodes to rearrange this view; scroll sideways on small screens.",
  }[mode];
}

function renderDag(snapshot) {
  const root = $("dag-svg"); root.replaceChildren();
  const pipeline = snapshot.pipeline;
  if (!pipeline) return;
  const stages = pipeline.stages || [];
  const job = pipeline.focus_jobs?.[state.selectedNode] || pipeline.latest_jobs?.[state.selectedNode];
  const byId = Object.fromEntries(stages.map((stage, index) => [stage.id, index]));
  const xAt = (index) => 86 + index * (830 / Math.max(1, stages.length - 1));
  root.append(svg("text", { x: 32, y: 51, fill: "#63798d", "font-size": 16, "font-weight": 700 },
    `${state.selectedNode.replace("_", " ")}  /  ${job ? `${job.job_id} · released ${displayNumber(job.release_time_ms, 1)} ms` : "No released job"}`));
  for (const edge of pipeline.edges || []) {
    const from = byId[edge.source], to = byId[edge.target];
    if (from === undefined || to === undefined) continue;
    const x1 = xAt(from) + 64, x2 = xAt(to) - 64;
    const sourceState = job?.stages?.[edge.source]?.state;
    const targetState = job?.stages?.[edge.target]?.state;
    const flowing = sourceState === "COMPLETED" && targetState && targetState !== "WAITING" && targetState !== "COMPLETED";
    const edgeLine = svg("line", { x1, y1: 255, x2: x2 - 8, y2: 255, stroke: flowing ? "#080707" : "#8caabd", "stroke-width": flowing ? 5 : 3, "stroke-dasharray": flowing ? "8 7" : "none" });
    if (flowing) edgeLine.classList.add("live-link");
    root.append(edgeLine);
    root.append(svg("path", { d: `M ${x2 - 9} 247 L ${x2 + 2} 255 L ${x2 - 9} 263 Z`, fill: "#8caabd" }));
  }
  const colors = {
    WAITING: ["#f4f7fa", "#b7c9d5"], RELEASED: ["#eef4ff", "#537dc6"],
    READY: ["#eef4ff", "#537dc6"], RUNNING: ["#e5f6f4", "#0f8a93"],
    OFFLOADED: ["#e9f2ff", "#537dc6"], FALLBACK_ACTIVE: ["#fff4df", "#c9902b"],
    COMPLETED: ["#e8f7ed", "#2f9d63"], DEADLINE_MISSED: ["#fff0f0", "#dc6b72"],
    ABANDONED: ["#fff0f0", "#dc6b72"],
  };
  for (const [index, stage] of stages.entries()) {
    const x = xAt(index), record = job?.stages?.[stage.id] || { state: "WAITING" };
    const status = record.state || "WAITING", [fill, accent] = colors[status] || colors.WAITING;
    const group = svg("g", { role: "group", "aria-label": `${stage.id}: ${status}` });
    if (["RELEASED", "READY", "RUNNING", "OFFLOADED", "FALLBACK_ACTIVE"].includes(status)) group.classList.add("dag-active-stage");
    group.append(svg("rect", { x: x - 64, y: 203, width: 128, height: 106, rx: 15, fill, stroke: accent, "stroke-width": 2 }));
    group.append(svg("circle", { cx: x, cy: 215, r: 6, fill: accent }));
    const label = stage.id.replace(/([a-z])([A-Z])/g, "$1 $2");
    const words = label.split(" ");
    if (words.length > 1) {
      group.append(svg("text", { x, y: 246, fill: "#183048", "text-anchor": "middle", "font-size": 12, "font-weight": 700 }, words[0]));
      group.append(svg("text", { x, y: 263, fill: "#183048", "text-anchor": "middle", "font-size": 12, "font-weight": 700 }, words.slice(1).join(" ")));
    } else group.append(svg("text", { x, y: 254, fill: "#183048", "text-anchor": "middle", "font-size": 12, "font-weight": 700 }, label));
    group.append(svg("text", { x, y: 290, fill: accent, "text-anchor": "middle", "font-size": 10, "font-weight": 700 }, status.replaceAll("_", " ")));
    if (typeof record.remaining_work_ms === "number" && ["RUNNING", "OFFLOADED", "FALLBACK_ACTIVE"].includes(status)) {
      group.append(svg("text", { x, y: 303, fill: "#383838", "text-anchor": "middle", "font-size": 8 }, `${displayNumber(record.remaining_work_ms, 2)} ms left`));
    }
    root.append(group);
    root.append(svg("text", { x, y: 337, fill: "#63798d", "text-anchor": "middle", "font-size": 11 },
      `${displayNumber(stage.relative_deadline_ms, 0)} ms stage deadline`));
  }
  root.append(svg("text", { x: 32, y: 475, fill: "#63798d", "font-size": 14 },
    "WAITING means the predecessor has not committed this stage for the selected job."));
}

function renderInteraction(snapshot) {
  const root = $("interaction-svg"); root.replaceChildren();
  const nodes = snapshot.nodes || {}, keys = Object.keys(nodes);
  const coordinates = graphPositions(keys, "interaction");
  root.append(svg("text", { x: 28, y: 39, fill: "#63798d", "font-size": 15, "font-weight": 700 },
    `${(snapshot.links || []).length} configured peer links · ${(snapshot.active_offloads || []).length} in-flight offloads`));
  for (const link of snapshot.links || []) {
    const from = coordinates[link.source], to = coordinates[link.target];
    if (!from || !to) continue;
    const active = (snapshot.active_offloads || []).some((packet) =>
      (packet.source === link.source && packet.target === link.target) ||
      (packet.source === link.target && packet.target === link.source));
    const line = svg("line", { x1: from[0], y1: from[1], x2: to[0], y2: to[1],
      stroke: active ? "#0f8a93" : link.quality === "red" ? "#dc6b72" : "#c4d4df",
      "stroke-width": active ? 6 : 2, opacity: active ? .8 : .7, "stroke-dasharray": active ? "10 8" : "none" });
    if (active) line.classList.add("live-link");
    root.append(line);
  }
  for (const packet of snapshot.active_offloads || []) {
    const from = coordinates[packet.source], to = coordinates[packet.target];
    if (!from || !to) continue;
    const dot = svg("circle", { cx: from[0], cy: from[1], r: 11, fill: "#ebff00", stroke: "#000", "stroke-width": 3 });
    dot.classList.add("live-packet");
    Object.assign(dot.dataset, { x1: from[0], y1: from[1], x2: to[0], y2: to[1], progress: packet.progress_pct || 0 });
    root.append(dot);
  }
  for (const [id, node] of Object.entries(nodes)) {
    const [x, y] = coordinates[id], selected = id === state.selectedNode;
    const stressed = node.is_overloaded || node.status === "OVERLOADED";
    const accent = stressed ? "#dc6b72" : node.fallback_active ? "#c9902b" : "#0f8a93";
    const group = svg("g", { role: "button", tabindex: 0, "aria-label": `${node.name}. Drag or use arrow keys to move in this view.` });
    group.classList.add("draggable-node");
    if ((node.running_tasks || []).length) group.classList.add("node-running");
    group.append(svg("circle", { cx: x, cy: y, r: 55, fill: selected ? "#e9f8f7" : "#fff", stroke: accent, "stroke-width": selected ? 4 : 2 }));
    group.append(svg("image", { href: deviceIcon(node), x: x - 21, y: y - 40, width: 42, height: 42, "pointer-events": "none" }));
    group.append(svg("text", { x, y: y + 14, fill: "#183048", "text-anchor": "middle", "font-size": 13, "font-weight": 700 }, id.replace("Device_", "Node ")));
    group.append(svg("text", { x, y: y + 31, fill: "#63798d", "text-anchor": "middle", "font-size": 9 }, (node.running_tasks || []).length ? `RUNNING ${node.running_tasks[0]}` : `${node.queue_len} queued · ${node.total_offloads} offloads`));
    wireGraphNode(group, id, root, "interaction");
    root.append(group);
  }
}

function renderNode(node) {
  const root = $("node-detail");
  root.replaceChildren();
  if (!node) { root.append(element("p", "muted", "Select a node in the fleet map.")); return; }
  $("selected-node-id").textContent = node.id?.split("_")[1]?.padStart(2, "0") || "—";
  const identity = element("div", "node-identity");
  const heading = element("div", "node-identity-top");
  const icon = element("img", "device-hero-icon");
  icon.src = deviceIcon(node);
  icon.alt = "";
  icon.setAttribute("aria-hidden", "true");
  const copy = element("div", "node-identity-copy");
  copy.append(element("span", "device-type-name", deviceTypeNames[deviceKind(node)]));
  copy.append(element("strong", "", node.name || node.id));
  copy.append(element("span", "", node.role || "Edge compute node"));
  heading.append(icon, copy);
  identity.append(heading);
  const status = element("span", "node-state", node.status || "UNKNOWN");
  if (node.is_overloaded) status.classList.add("stressed");
  else if (node.fallback_active) status.classList.add("fallback");
  identity.append(status);
  root.append(identity);
  const list = element("dl");
  const rows = [
    ["Compute profile", node.hardware || "Unspecified"],
    ["CPU utilization", displayNumber(node.cpu, 1, "%")],
    ["GPU utilization", displayNumber(node.gpu, 1, "%")],
    ["Temperature", displayNumber(node.temp_c, 1, " °C")],
    ["Ready queue", displayNumber(node.queue_len)],
    ["Active task", node.active_task || "Idle"],
    ["Offload dispatches", displayNumber(node.total_offloads)],
    ["Fallbacks", displayNumber(node.total_fallbacks)],
  ];
  for (const [key, value] of rows) {
    const row = element("div"); row.append(element("dt", "", key), element("dd", "", value)); list.append(row);
  }
  root.append(list);
}

function renderTrend() {
  const root = $("trend-chart"); root.replaceChildren();
  const left = 43, right = 619, top = 16, bottom = 181;
  const values = state.history.flatMap((point) => [point.primary, point.baseline]);
  const ceiling = Math.max(5, Math.ceil(Math.max(0, ...values) * 1.2));
  for (let tick = 0; tick <= 4; tick++) {
    const y = bottom - (bottom - top) * tick / 4;
    root.append(svg("line", { x1: left, y1: y, x2: right, y2: y, stroke: "#2b4155", "stroke-width": 1 }));
    root.append(svg("text", { x: 36, y: y + 4, fill: "#72889b", "text-anchor": "end", "font-size": 10 }, `${displayNumber(ceiling * tick / 4, 0)}%`));
  }
  const history = state.history;
  if (history.length < 2) {
    root.append(svg("text", { x: 335, y: 102, fill: "#72889b", "text-anchor": "middle", "font-size": 12 }, "Trend appears as the simulation advances"));
    return;
  }
  const t0 = history[0].t, range = Math.max(1, history[history.length - 1].t - t0);
  for (const [field, color] of [["primary", "#0f8a93"], ["baseline", "#ce5f69"]]) {
    const points = history.map((point) => [left + (point.t - t0) / range * (right - left), bottom - point[field] / ceiling * (bottom - top)]);
    root.append(svg("polyline", { points: points.map((p) => p.join(",")).join(" "), fill: "none", stroke: color, "stroke-width": 2.4, "stroke-linejoin": "round" }));
  }
  root.append(svg("text", { x: left, y: 205, fill: "#72889b", "font-size": 10 }, `${displayNumber(t0, 0)} ms`));
  root.append(svg("text", { x: right, y: 205, fill: "#72889b", "text-anchor": "end", "font-size": 10 }, `${displayNumber(history[history.length - 1].t, 0)} ms`));
}

function eventRow(event, canonical = false) {
  const row = element("div", "event-item");
  const timestamp = canonical ? event.timestamp_us / 1000 : event.timestamp_ms;
  const kind = event.event_type || event.event || "EVENT";
  const time = element("span", "event-time", `${displayNumber(timestamp, 2)} ms`);
  const title = element("span", "event-title", kind.replaceAll("_", " "));
  if (/DEADLINE|DROP|FAULT|ABORT/.test(kind)) title.classList.add("warn");
  if (/COMMIT|COMPLETED|FALLBACK/.test(kind)) title.classList.add("good");
  const task = event.task_id || event.payload?.task_id;
  const context = [event.device_id, task].filter(Boolean).join(" · ") || "System event";
  row.append(time, title, element("span", "event-context", context));
  return row;
}

function renderLiveEvent(event) {
  const root = $("event-list");
  if (state.eventCount === 0) root.replaceChildren();
  root.prepend(eventRow(event));
  state.eventCount++;
  $("event-count").textContent = `${state.eventCount} events`;
  while (root.children.length > 80) root.lastElementChild.remove();
}

async function fetchAllEvents(runId) {
  const events = [];
  for (let offset = 0; ; offset += 1000) {
    const page = await request(`/api/v1/runs/${encodeURIComponent(runId)}/events?offset=${offset}&limit=1000`);
    events.push(...page.events);
    if (events.length >= page.total) break;
  }
  return events;
}

async function runExperiment(event) {
  event.preventDefault();
  const button = $("run-experiment-button"); button.disabled = true;
  button.textContent = "Running simulation…";
  try {
    const body = {
      scenario_type: $("exp-scenario").value, policy: $("exp-policy").value,
      seed: Number($("exp-seed").value), duration_ms: Number($("exp-duration").value),
      fleet_size: Number($("exp-fleet").value),
    };
    const created = await request("/api/v1/runs", { method: "POST", body: JSON.stringify(body) });
    const [run, metrics, events] = await Promise.all([
      request(`/api/v1/runs/${encodeURIComponent(created.run_id)}`),
      request(`/api/v1/runs/${encodeURIComponent(created.run_id)}/metrics`),
      fetchAllEvents(created.run_id),
    ]);
    state.experiment = { run, metrics, events };
    renderExperiment();
    showToast(`Run ${created.run_id} completed with ${events.length} canonical events`);
  } catch (error) { showToast(error.message, true); }
  finally { button.disabled = false; button.innerHTML = "Run seeded experiment <span>↗</span>"; }
}

function renderExperiment() {
  const { run, metrics, events } = state.experiment;
  $("result-empty").hidden = true;
  $("result-content").hidden = false;
  $("result-title").textContent = `${run.scenario} / ${run.policy}`;
  $("result-released").textContent = displayNumber(metrics.total_released_tasks);
  $("result-missed").textContent = displayNumber(metrics.deadline_missed_count);
  $("result-critical").textContent = displayNumber(metrics.critical_misses);
  $("result-response").textContent = displayNumber(metrics.worst_case_response_time_ms, 1, " ms");
  $("result-run-id").textContent = run.run_id;
  $("result-manifest").textContent = JSON.stringify(run.manifest, null, 2);
  $("result-event-count").textContent = `${events.length} events`;
  const root = $("result-events"); root.replaceChildren();
  for (const item of events.slice(0, 120)) root.append(eventRow(item, true));
  if (events.length > 120) root.append(element("p", "small-note", `Showing the first 120 of ${events.length} events. Export JSON for the complete record.`));
}

function exportExperiment() {
  if (!state.experiment) return;
  const { run, metrics, events } = state.experiment;
  const content = { manifest: run.manifest, metrics, events };
  const blob = new Blob([JSON.stringify(content, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = element("a"); link.href = url; link.download = `${run.run_id}.json`;
  document.body.append(link); link.click(); link.remove(); URL.revokeObjectURL(url);
}

async function comparePolicies() {
  const button = $("compare-button"); button.disabled = true; button.textContent = "Comparing…";
  try {
    const data = await request("/api/v1/compare", { method: "POST", body: JSON.stringify({
      scenario_type: $("exp-scenario").value, seed: Number($("exp-seed").value),
      duration_ms: Number($("exp-duration").value),
      policies: ["rts_predictive", "edf"],
    }) });
    const root = $("compare-output"); root.replaceChildren();
    const table = element("table", "compare-table");
    const head = element("thead"), headRow = element("tr");
    for (const title of ["Policy", "Deadline miss ratio", "Critical misses", "Observed max response"]) headRow.append(element("th", "", title));
    head.append(headRow); table.append(head);
    const body = element("tbody");
    for (const [name, metrics] of Object.entries(data.comparisons)) {
      const row = element("tr");
      row.append(element("td", "", name === "rts_predictive" ? "PredictiveRuntime · bundled" : "EDF"));
      row.append(element("td", "", displayNumber(metrics.deadline_miss_ratio * 100, 2, "%")));
      row.append(element("td", "", displayNumber(metrics.critical_misses)));
      row.append(element("td", "", displayNumber(metrics.worst_case_response_time_ms, 1, " ms")));
      body.append(row);
    }
    table.append(body); root.append(table);
  } catch (error) { showToast(error.message, true); }
  finally { button.disabled = false; button.textContent = "Compare selected scenario"; }
}

function renderModelDetails(rootId, fields) {
  const root = $(rootId); root.replaceChildren();
  const list = element("dl");
  for (const [label, value] of fields) {
    const row = element("div");
    row.append(element("dt", "", label), element("dd", "", value));
    list.append(row);
  }
  root.append(list);
}

async function loadModels() {
  try {
    const data = await request("/api/v1/models");
    const gnn = data.predictor, fl = data.federated;
    $("gnn-evidence").textContent = gnn.evidence || "UNVALIDATED";
    $("fl-evidence").textContent = fl.evidence || "UNVALIDATED";
    renderModelDetails("gnn-model-detail", [
      ["Version", gnn.model_version || "Unavailable"], ["Architecture", gnn.architecture || "Unavailable"],
      ["Saved weights", gnn.weights_available ? "Available" : "Missing"],
      ["Parameters", displayNumber(gnn.parameters)], ["Calibrated", gnn.calibrated ? "Yes" : "No"],
      ["Held-out AUROC", displayNumber(gnn.test_metrics?.roc_auc, 4)],
      ["Held-out ECE", displayNumber(gnn.test_metrics?.ece, 4)],
      ["Measured inference latency", displayNumber(gnn.measured_inference_latency_ms, 3, " ms")],
    ]);
    renderModelDetails("fl-model-detail", [
      ["Version", fl.model_version || "Unavailable"], ["Architecture", fl.architecture || "Unavailable"],
      ["Evaluated rounds", displayNumber(fl.rounds_evaluated)],
      ["Federated clients", displayNumber(fl.non_iid_partitions)],
      ["Held-out execution MAE", displayNumber(fl.test_metrics?.execution_mae_ms, 3, " ms")],
      ["Held-out q95 coverage", displayNumber(fl.test_metrics?.q95_empirical_coverage, 3)],
      ["Seeded experiment", fl.evidence === "SIMULATION_EVALUATED" ? "Active" : "Unavailable"],
    ]);
  } catch (error) { showToast(error.message, true); }
}

async function runVerification() {
  const button = $("run-verification");
  button.disabled = true;
  button.textContent = "Analyzing…";
  try {
    const task = (task_id, period_us, deadline_us, wcet_us, priority) => ({
      task_id, period_us, deadline_us, wcet_us, priority,
      jitter_us: 0, blocking_us: 0, overhead_us: 100, resource_id: "safety-cpu",
    });
    const certificate = await request("/api/v1/verification/analyze", {
      method: "POST",
      body: JSON.stringify({
        tasks: [
          task("Actuation", 10000, 10000, 1000, 11),
          task("Sense", 20000, 20000, 1500, 10),
          task("ObstacleDetection", 20000, 20000, 2500, 9),
          task("Perception", 33000, 33000, 5000, 8),
          task("PathPlanning", 50000, 50000, 4500, 7),
        ],
        scenario_hash: "degraded-autonomous-pipeline-v1",
        scheduler_config_hash: "fp-preemptive-v1",
        hardware_profile_hash: "modeled-safety-cpu-v1",
        resource_partition_id: "safety-cpu",
        fallback_mode_id: "configured-early-exit-v1",
      }),
    });
    $("verification-status").textContent = certificate.status;
    $("verification-tag").textContent = certificate.status === "VERIFIED" ? "ANALYTICALLY VERIFIED" : "ANALYTICAL RESULT";
    const root = $("verification-output"); root.className = "model-detail"; root.replaceChildren();
    renderModelDetails("verification-output", [
      ["Certificate", certificate.certificate_id],
      ["Input hash", certificate.input_sha256],
      ["Analyzer", `${certificate.provenance.analyzer_name} ${certificate.provenance.analyzer_version}`],
      ["Assumption", "Single processor · fully preemptive · constrained deadlines"],
      ...certificate.results.map((result) => [
        result.task_id,
        `R=${displayNumber(result.response_time_us / 1000, 3, " ms")} · margin=${displayNumber(result.margin_us / 1000, 3, " ms")}`,
      ]),
    ]);
  } catch (error) { showToast(error.message, true); }
  finally { button.disabled = false; button.textContent = "Analyze degraded partition"; }
}

function wireControls() {
  document.querySelectorAll(".nav-item").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.view)));
  document.querySelectorAll(".graph-tab").forEach((button) => button.addEventListener("click", () => setGraphMode(button.dataset.graph)));
  for (const [id, mode] of [["topology-svg", "fleet"], ["interaction-svg", "interaction"]]) {
    const root = $(id);
    root.addEventListener("pointermove", (event) => moveNodeFromPointer(event, root, mode));
    root.addEventListener("pointerup", (event) => {
      if (state.draggingNode?.pointerId === event.pointerId) state.draggingNode = null;
    });
    root.addEventListener("pointercancel", () => { state.draggingNode = null; });
  }
  $("play-button").addEventListener("click", togglePlayback);
  $("step-button").addEventListener("click", () => stepLive(25));
  $("reset-button").addEventListener("click", startLive);
  for (const id of ["fleet-size", "live-seed", "live-horizon"]) $(id).addEventListener("change", startLive);
  document.querySelectorAll("[data-speed]").forEach((button) => button.addEventListener("click", () => {
    state.speed = Number(button.dataset.speed);
    document.querySelectorAll("[data-speed]").forEach((candidate) => candidate.classList.toggle("is-active", candidate === button));
  }));
  document.querySelectorAll("[data-fault]").forEach((button) => button.addEventListener("click", () => injectFault(button.dataset.fault)));
  $("experiment-form").addEventListener("submit", runExperiment);
  $("compare-button").addEventListener("click", comparePolicies);
  $("export-run-button").addEventListener("click", exportExperiment);
  $("refresh-models").addEventListener("click", loadModels);
  $("run-verification").addEventListener("click", runVerification);
}

document.addEventListener("DOMContentLoaded", () => {
  applyResearchLabels();
  wireControls();
  setGraphMode("fleet");
  renderTrend();
  requestAnimationFrame(animateClock);
  const initialView = ["live", "experiments", "models", "evidence", "verification"].includes(location.hash.slice(1))
    ? location.hash.slice(1) : "live";
  switchView(initialView);
  startLive();
});
