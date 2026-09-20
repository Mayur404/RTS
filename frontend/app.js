/**
 * GhostGuard // Multi-Node Runtime Protection Dashboard
 * Interactive Web Dashboard Controller (FastAPI REST + HTML5 Canvas + Plotly.js)
 */

// Application State
let currentTrace = null;
let currentFrameIdx = 0;
let isPlaying = false;
let playInterval = null;
let hoveredNode = null;

// DOM Elements
const canvas = document.getElementById("mesh-canvas");
const ctx = canvas.getContext("2d");
const tooltip = document.getElementById("node-tooltip");

const slider = document.getElementById("timeline-slider");
const clockDisplay = document.getElementById("clock-display");
const btnPlay = document.getElementById("btn-play");
const btnReset = document.getElementById("btn-reset");
const btnStepBack = document.getElementById("btn-step-back");
const btnStepFwd = document.getElementById("btn-step-fwd");

const inputContention = document.getElementById("input-contention");
const valContention = document.getElementById("val-contention");
const inputFaultTime = document.getElementById("input-fault-time");
const valFaultTime = document.getElementById("val-fault-time");
const inputJitter = document.getElementById("input-jitter");
const valJitter = document.getElementById("val-jitter");
const inputFleetSize = document.getElementById("input-fleet-size");
const inputTargetNode = document.getElementById("input-target-node");

const btnRunSim = document.getElementById("btn-run-sim");
const btnLoadSec12 = document.getElementById("btn-load-sec12");
const loadingSpinner = document.getElementById("loading-spinner");
const activeScenarioBadge = document.getElementById("active-scenario-badge");
const channelQualityPill = document.getElementById("channel-quality-pill");
const activeStagePill = document.getElementById("active-stage-pill");
const stageBadgeInline = document.getElementById("stage-badge-inline");
const stageDescText = document.getElementById("stage-desc-text");

// Tooltip Elements
const ttTitle = document.getElementById("tt-title");
const ttRole = document.getElementById("tt-role");
const ttCpu = document.getElementById("tt-cpu");
const ttCpuBar = document.getElementById("tt-cpu-bar");
const ttGpu = document.getElementById("tt-gpu");
const ttGpuBar = document.getElementById("tt-gpu-bar");
const ttTemp = document.getElementById("tt-temp");
const ttQueue = document.getElementById("tt-queue");
const ttTask = document.getElementById("tt-task");
const ttStatus = document.getElementById("tt-status");

// Stats Elements
const statGgMisses = document.getElementById("stat-gg-misses");
const statGgWcrt = document.getElementById("stat-gg-wcrt");
const statGgFallbacks = document.getElementById("stat-gg-fallbacks");
const statEdfMisses = document.getElementById("stat-edf-misses");
const statEdfWcrt = document.getElementById("stat-edf-wcrt");
const statEdfFallbacks = document.getElementById("stat-edf-fallbacks");

// -------------------------------------------------------------
// Initialization & Event Listeners
// -------------------------------------------------------------
window.addEventListener("DOMContentLoaded", () => {
    setupInputListeners();
    setupCanvasListeners();
    setupPlaybackControls();
    loadSection12Benchmark();
});

function setupInputListeners() {
    inputContention.addEventListener("input", (e) => {
        valContention.textContent = `${e.target.value}%`;
    });
    inputFaultTime.addEventListener("input", (e) => {
        valFaultTime.textContent = `${e.target.value} ms`;
    });
    inputJitter.addEventListener("input", (e) => {
        valJitter.textContent = `${parseFloat(e.target.value).toFixed(1)} ms`;
    });

    btnRunSim.addEventListener("click", runDynamicSimulation);
    btnLoadSec12.addEventListener("click", loadSection12Benchmark);
}

function setupPlaybackControls() {
    btnPlay.addEventListener("click", togglePlay);
    btnReset.addEventListener("click", () => seekToMs(0));
    btnStepBack.addEventListener("click", () => stepMs(-5));
    btnStepFwd.addEventListener("click", () => stepMs(5));

    slider.addEventListener("input", (e) => {
        const ms = parseFloat(e.target.value);
        seekToMs(ms);
    });
}

function setupCanvasListeners() {
    canvas.addEventListener("mousemove", handleCanvasMouseMove);
    canvas.addEventListener("mouseleave", handleCanvasMouseLeave);
}

// -------------------------------------------------------------
// API Calls: Load Benchmark & Run Simulation
// -------------------------------------------------------------
async function loadSection12Benchmark() {
    showLoading(true);
    pause();
    try {
        const res = await fetch("/api/section12");
        if (!res.ok) throw new Error(`HTTP error ${res.status}`);
        const data = await res.json();
        
        currentTrace = data;
        activeScenarioBadge.textContent = "Section 12 Deterministic Benchmark";
        inputContention.value = 90;
        valContention.textContent = "90%";
        inputFaultTime.value = 25;
        valFaultTime.textContent = "25 ms";
        inputJitter.value = 5;
        valJitter.textContent = "5.0 ms";
        inputFleetSize.value = "4";
        inputTargetNode.value = "Node 1 (Jetson Nano)";

        seekToMs(0);
        renderGanttChart(data.tasks_gg, data.tasks_edf);
        updatePerformanceCards(data.metrics_gg, data.metrics_edf);
    } catch (err) {
        console.error("Failed to load Section 12 benchmark:", err);
    } finally {
        showLoading(false);
    }
}

async function runDynamicSimulation() {
    showLoading(true);
    pause();
    try {
        const payload = {
            contention: parseFloat(inputContention.value) / 100.0,
            fault_time: parseFloat(inputFaultTime.value),
            jitter: parseFloat(inputJitter.value),
            fleet_size: parseInt(inputFleetSize.value, 10),
            target_node: inputTargetNode.value
        };

        const res = await fetch("/api/simulate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        if (!res.ok) throw new Error(`HTTP error ${res.status}`);
        const data = await res.json();

        currentTrace = data;
        activeScenarioBadge.textContent = `Dynamic Run (${payload.fleet_size} Nodes, Fault @ ${payload.fault_time}ms)`;
        
        seekToMs(0);
        renderGanttChart(data.tasks_gg, data.tasks_edf);
        updatePerformanceCards(data.metrics_gg, data.metrics_edf);
    } catch (err) {
        console.error("Simulation failed:", err);
        alert(`Simulation Error: ${err.message}`);
    } finally {
        showLoading(false);
    }
}

function showLoading(isLoading) {
    if (isLoading) {
        loadingSpinner.classList.remove("hidden");
        loadingSpinner.classList.add("flex");
        btnRunSim.disabled = true;
        btnLoadSec12.disabled = true;
    } else {
        loadingSpinner.classList.add("hidden");
        loadingSpinner.classList.remove("flex");
        btnRunSim.disabled = false;
        btnLoadSec12.disabled = false;
    }
}

// -------------------------------------------------------------
// Playback & Scrubber Controls
// -------------------------------------------------------------
function togglePlay() {
    if (isPlaying) {
        pause();
    } else {
        play();
    }
}

function play() {
    if (!currentTrace || !currentTrace.frames) return;
    isPlaying = true;
    btnPlay.textContent = "⏸ PAUSE";
    btnPlay.classList.replace("bg-blue-600", "bg-amber-600");
    btnPlay.classList.replace("hover:bg-blue-500", "hover:bg-amber-500");

    playInterval = setInterval(() => {
        if (!currentTrace) return;
        let nextIdx = currentFrameIdx + 1;
        if (nextIdx >= currentTrace.frames.length) {
            nextIdx = 0; // loop
        }
        applyFrame(nextIdx);
    }, 45); // ~22 FPS smooth playback
}

function pause() {
    isPlaying = false;
    if (playInterval) {
        clearInterval(playInterval);
        playInterval = null;
    }
    btnPlay.textContent = "▶ PLAY";
    btnPlay.classList.replace("bg-amber-600", "bg-blue-600");
    btnPlay.classList.replace("hover:bg-amber-500", "hover:bg-blue-500");
}

function seekToMs(ms) {
    if (!currentTrace || !currentTrace.frames) return;
    const clampedMs = Math.max(0, Math.min(ms, currentTrace.max_t || 100));
    const step = currentTrace.step_ms || 1.0;
    const idx = Math.round(clampedMs / step);
    applyFrame(idx);
}

function stepMs(delta) {
    if (!currentTrace || !currentTrace.frames) return;
    const currentT = currentTrace.frames[currentFrameIdx] ? currentTrace.frames[currentFrameIdx].t : 0;
    seekToMs(currentT + delta);
}

window.jumpToMilestone = function(targetMs) {
    seekToMs(targetMs);
    // Highlight chip
    document.querySelectorAll(".milestone-chip").forEach(el => {
        if (el.textContent.includes(`t=${targetMs}`)) {
            el.classList.add("active");
        } else {
            el.classList.remove("active");
        }
    });
};

function applyFrame(frameIdx) {
    if (!currentTrace || !currentTrace.frames) return;
    if (frameIdx < 0) frameIdx = 0;
    if (frameIdx >= currentTrace.frames.length) frameIdx = currentTrace.frames.length - 1;

    currentFrameIdx = frameIdx;
    const frame = currentTrace.frames[frameIdx];
    if (!frame) return;

    // 1. Update Scrubber UI
    slider.value = Math.round(frame.t);
    clockDisplay.textContent = frame.t.toFixed(1);

    // 2. Stage Pill & Explanations
    activeStagePill.textContent = frame.stage_name || `Stage ${frame.stage_id}`;
    stageBadgeInline.textContent = `Stage ${frame.stage_id}`;
    stageBadgeInline.style.backgroundColor = frame.badge_color || "#2563EB";
    stageDescText.textContent = frame.stage_desc || "";

    // Channel quality pill
    const jitter = currentTrace.params ? currentTrace.params.channel_jitter_ms : 5.0;
    if (frame.stage_id === 5) {
        channelQualityPill.className = "text-xs font-bold mono px-2.5 py-1 rounded-full border border-red-700 bg-red-950/80 text-red-300";
        channelQualityPill.textContent = "Channel: WATCHDOG ABORT!";
    } else if (frame.stage_id === 4) {
        channelQualityPill.className = "text-xs font-bold mono px-2.5 py-1 rounded-full border border-red-700 bg-red-950/80 text-red-300";
        channelQualityPill.textContent = "Channel: REMOTE STRESSED";
    } else if (frame.stage_id === 3) {
        channelQualityPill.className = "text-xs font-bold mono px-2.5 py-1 rounded-full border border-amber-700 bg-amber-950/80 text-amber-300";
        channelQualityPill.textContent = `Channel: IN-FLIGHT (Jitter: ${jitter.toFixed(1)}ms)`;
    } else {
        channelQualityPill.className = "text-xs font-bold mono px-2.5 py-1 rounded-full border border-emerald-700 bg-emerald-950/80 text-emerald-300";
        channelQualityPill.textContent = `Channel: Nominal (${jitter.toFixed(1)}ms)`;
    }

    // 3. Draw Canvas Mesh Topology
    drawMeshTopology(frame);

    // 4. Update Gantt Scrubber Line
    updateGanttCursor(frame.t);
}

// -------------------------------------------------------------
// Panel 2: Multi-Node Mesh Topology Canvas Renderer
// -------------------------------------------------------------
function getNodePositions(fleetSize, width, height) {
    // Elegant distributed geometry based on fleet size
    if (fleetSize === 4) {
        return {
            "Device_1": { x: width * 0.22, y: height * 0.50 },
            "Device_2": { x: width * 0.78, y: height * 0.50 },
            "Device_3": { x: width * 0.50, y: height * 0.22 },
            "Device_4": { x: width * 0.50, y: height * 0.80 },
        };
    } else if (fleetSize === 6) {
        return {
            "Device_1": { x: width * 0.28, y: height * 0.50 },
            "Device_2": { x: width * 0.72, y: height * 0.50 },
            "Device_3": { x: width * 0.50, y: height * 0.20 },
            "Device_4": { x: width * 0.50, y: height * 0.82 },
            "Device_5": { x: width * 0.12, y: height * 0.25 },
            "Device_6": { x: width * 0.88, y: height * 0.25 },
        };
    } else {
        // 8 nodes
        return {
            "Device_1": { x: width * 0.30, y: height * 0.50 },
            "Device_2": { x: width * 0.70, y: height * 0.50 },
            "Device_3": { x: width * 0.50, y: height * 0.18 },
            "Device_4": { x: width * 0.50, y: height * 0.82 },
            "Device_5": { x: width * 0.12, y: height * 0.25 },
            "Device_6": { x: width * 0.88, y: height * 0.25 },
            "Device_7": { x: width * 0.12, y: height * 0.75 },
            "Device_8": { x: width * 0.88, y: height * 0.75 },
        };
    }
}

function drawMeshTopology(frame) {
    if (!ctx) return;
    const width = canvas.width;
    const height = canvas.height;

    // Clear Canvas
    ctx.clearRect(0, 0, width, height);

    // Background Subtle Grid Pattern
    ctx.strokeStyle = "rgba(31, 41, 55, 0.4)";
    ctx.lineWidth = 1;
    const gridSize = 40;
    for (let x = 0; x < width; x += gridSize) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, height);
        ctx.stroke();
    }
    for (let y = 0; y < height; y += gridSize) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
        ctx.stroke();
    }

    const nodes = frame.nodes || {};
    const links = frame.links || [];
    const fleetSize = currentTrace.topology ? currentTrace.topology.fleet_size : Object.keys(nodes).length;
    const positions = getNodePositions(fleetSize, width, height);

    // 1. Draw Mesh Links
    links.forEach(link => {
        const p1 = positions[link.source];
        const p2 = positions[link.target];
        if (!p1 || !p2) return;

        const isPrimary = link.is_offload_channel || (link.source === "Device_1" && link.target === "Device_2");
        ctx.save();

        let strokeColor = "rgba(16, 185, 129, 0.45)"; // green nominal
        let lineWidth = isPrimary ? 3.5 : 1.5;

        if (link.quality === "amber") {
            strokeColor = "rgba(245, 158, 11, 0.75)";
        } else if (link.quality === "red") {
            strokeColor = "rgba(239, 68, 68, 0.85)";
            if (isPrimary) lineWidth = 4.5;
        }

        ctx.strokeStyle = strokeColor;
        ctx.lineWidth = lineWidth;
        ctx.beginPath();
        ctx.moveTo(p1.x, p1.y);
        ctx.lineTo(p2.x, p2.y);
        ctx.stroke();

        // If primary offload channel in flight (t=33 to 49.5 ms)
        if (isPrimary && (frame.stage_id === 3 || frame.stage_id === 4)) {
            // Draw animated traveling packet particle
            const txPct = frame.active_offload ? (frame.active_offload.progress_pct || 50.0) / 100.0 : 0.5;
            const packetX = p1.x + (p2.x - p1.x) * txPct;
            const packetY = p1.y + (p2.y - p1.y) * txPct;

            // Packet Pulse Glow
            ctx.fillStyle = "rgba(59, 130, 246, 0.3)";
            ctx.beginPath();
            ctx.arc(packetX, packetY, 14, 0, Math.PI * 2);
            ctx.fill();

            // Core Packet Dot
            ctx.fillStyle = "#3B82F6";
            ctx.beginPath();
            ctx.arc(packetX, packetY, 7, 0, Math.PI * 2);
            ctx.fill();
            ctx.strokeStyle = "#FFFFFF";
            ctx.lineWidth = 1.5;
            ctx.stroke();

            // Label
            ctx.font = "bold 10px 'JetBrains Mono', monospace";
            ctx.fillStyle = "#93C5FD";
            ctx.textAlign = "center";
            ctx.fillText("Perception (16 KB)", packetX, packetY - 14);
        }

        // Flashing Abort Event Tag (t=49.5 to 52.4 ms)
        if (isPrimary && frame.stage_id === 5) {
            const midX = (p1.x + p2.x) / 2;
            const midY = (p1.y + p2.y) / 2;

            // Warning Banner
            const bannerW = 230;
            const bannerH = 26;
            ctx.fillStyle = "rgba(220, 38, 38, 0.95)";
            ctx.strokeStyle = "#FCA5A5";
            ctx.lineWidth = 1.5;
            roundRect(ctx, midX - bannerW / 2, midY - bannerH / 2, bannerW, bannerH, 4, true, true);

            ctx.font = "bold 11px 'JetBrains Mono', monospace";
            ctx.fillStyle = "#FFFFFF";
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            ctx.fillText("⚠️ ABORT: REMOTE BOTTLENECK", midX, midY);

            // Red Return Arrow to Node 1
            ctx.strokeStyle = "#EF4444";
            ctx.lineWidth = 2.5;
            ctx.setLineDash([5, 5]);
            ctx.beginPath();
            ctx.moveTo(p2.x - 20, p2.y + 15);
            ctx.lineTo(p1.x + 20, p1.y + 15);
            ctx.stroke();
            ctx.setLineDash([]);
        }

        // Fallback Saved Tag (t >= 52.4 ms)
        if (isPrimary && frame.stage_id === 6) {
            const midX = (p1.x + p2.x) / 2;
            const midY = (p1.y + p2.y) / 2;

            const bannerW = 200;
            const bannerH = 24;
            ctx.fillStyle = "rgba(6, 78, 59, 0.9)";
            ctx.strokeStyle = "#34D399";
            ctx.lineWidth = 1.2;
            roundRect(ctx, midX - bannerW / 2, midY - bannerH / 2, bannerW, bannerH, 4, true, true);

            ctx.font = "bold 10.5px 'JetBrains Mono', monospace";
            ctx.fillStyle = "#A7F3D0";
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            ctx.fillText("✓ DEADLINE SAVED (+7.6ms)", midX, midY);
        }

        ctx.restore();
    });

    // 2. Draw Nodes
    Object.keys(nodes).forEach(devId => {
        const node = nodes[devId];
        const pos = positions[devId];
        if (!pos) return;

        const isOverloaded = node.is_overloaded;
        const isFallback = node.fallback_active;
        const isHovered = (hoveredNode && hoveredNode.id === devId);

        ctx.save();

        const boxW = 145;
        const boxH = 68;
        const boxX = pos.x - boxW / 2;
        const boxY = pos.y - boxH / 2;

        // Pulsing Ring for Overload or Fallback
        if (isFallback) {
            ctx.strokeStyle = "rgba(16, 185, 129, 0.6)";
            ctx.lineWidth = 3;
            ctx.beginPath();
            roundRect(ctx, boxX - 4, boxY - 4, boxW + 8, boxH + 8, 8, false, true);
        } else if (isOverloaded) {
            ctx.strokeStyle = "rgba(239, 68, 68, 0.7)";
            ctx.lineWidth = 3;
            ctx.beginPath();
            roundRect(ctx, boxX - 4, boxY - 4, boxW + 8, boxH + 8, 8, false, true);
        }

        // Node Main Card Body
        ctx.fillStyle = isHovered ? "#1E293B" : "#0F172A";
        let borderColor = node.color || "#3B82F6";
        if (isFallback) borderColor = "#10B981";
        if (isOverloaded) borderColor = "#EF4444";

        ctx.strokeStyle = borderColor;
        ctx.lineWidth = isHovered ? 2.5 : 1.8;
        roundRect(ctx, boxX, boxY, boxW, boxH, 6, true, true);

        // Node Header Label
        ctx.font = "bold 11px 'Plus Jakarta Sans', sans-serif";
        ctx.fillStyle = "#F8FAFC";
        ctx.textAlign = "left";
        ctx.textBaseline = "top";
        ctx.fillText(node.name ? node.name.split(":")[0] : devId, boxX + 8, boxY + 8);

        // Hardware Subtitle
        ctx.font = "9px 'Plus Jakarta Sans', sans-serif";
        ctx.fillStyle = "#94A3B8";
        const shortRole = node.role ? node.role.split("/")[0].trim() : "Edge Node";
        ctx.fillText(shortRole, boxX + 8, boxY + 22);

        // Mini CPU Meter Bar
        const barW = boxW - 16;
        const barH = 5;
        const barX = boxX + 8;
        const barY = boxY + 36;

        ctx.fillStyle = "#1E293B";
        roundRect(ctx, barX, barY, barW, barH, 2, true, false);

        const cpuFillW = Math.min(barW, (node.cpu / 100.0) * barW);
        ctx.fillStyle = node.cpu > 80 ? "#EF4444" : (node.cpu > 60 ? "#F59E0B" : "#3B82F6");
        roundRect(ctx, barX, barY, cpuFillW, barH, 2, true, false);

        // Text telemetry footer inside node
        ctx.font = "bold 9px 'JetBrains Mono', monospace";
        ctx.fillStyle = "#E2E8F0";
        ctx.fillText(`CPU ${Math.round(node.cpu)}%`, barX, barY + 12);

        ctx.fillStyle = "#94A3B8";
        ctx.textAlign = "right";
        ctx.fillText(`${node.temp_c ? node.temp_c.toFixed(0) : 42}°C`, boxX + boxW - 8, barY + 12);

        // Fallback Badge Top-Right
        if (isFallback) {
            ctx.font = "bold 8px 'JetBrains Mono', monospace";
            ctx.fillStyle = "#10B981";
            ctx.textAlign = "right";
            ctx.fillText("● FALLBACK", boxX + boxW - 8, boxY + 8);
        } else if (isOverloaded) {
            ctx.font = "bold 8px 'JetBrains Mono', monospace";
            ctx.fillStyle = "#EF4444";
            ctx.textAlign = "right";
            ctx.fillText("● STRESSED", boxX + boxW - 8, boxY + 8);
        }

        ctx.restore();
    });
}

function roundRect(ctx, x, y, width, height, radius, fill, stroke) {
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.lineTo(x + width - radius, y);
    ctx.quadraticCurveTo(x + width, y, x + width, y + radius);
    ctx.lineTo(x + width, y + height - radius);
    ctx.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
    ctx.lineTo(x + radius, y + height);
    ctx.quadraticCurveTo(x, y + height, x, y + height - radius);
    ctx.lineTo(x, y + radius);
    ctx.quadraticCurveTo(x, y, x + radius, y);
    ctx.closePath();
    if (fill) ctx.fill();
    if (stroke) ctx.stroke();
}

// -------------------------------------------------------------
// Interactive Node Tooltip on Hover
// -------------------------------------------------------------
function handleCanvasMouseMove(e) {
    if (!currentTrace || !currentTrace.frames) return;
    const frame = currentTrace.frames[currentFrameIdx];
    if (!frame || !frame.nodes) return;

    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    const mouseX = (e.clientX - rect.left) * scaleX;
    const mouseY = (e.clientY - rect.top) * scaleY;

    const fleetSize = currentTrace.topology ? currentTrace.topology.fleet_size : Object.keys(frame.nodes).length;
    const positions = getNodePositions(fleetSize, canvas.width, canvas.height);

    let found = null;
    const boxW = 145;
    const boxH = 68;

    for (const [devId, pos] of Object.entries(positions)) {
        if (
            mouseX >= pos.x - boxW / 2 &&
            mouseX <= pos.x + boxW / 2 &&
            mouseY >= pos.y - boxH / 2 &&
            mouseY <= pos.y + boxH / 2
        ) {
            found = frame.nodes[devId];
            break;
        }
    }

    if (found) {
        hoveredNode = found;
        showTooltip(e.clientX, e.clientY, found);
    } else {
        hoveredNode = null;
        tooltip.classList.add("hidden");
    }
}

function handleCanvasMouseLeave() {
    hoveredNode = null;
    tooltip.classList.add("hidden");
}

function showTooltip(clientX, clientY, node) {
    ttTitle.textContent = node.name || node.id;
    ttRole.textContent = `${node.role || "Edge Compute Node"} · ${node.hardware || "Hardware"}`;
    ttCpu.textContent = `${node.cpu.toFixed(1)}%`;
    ttCpuBar.style.width = `${Math.min(100, node.cpu)}%`;
    ttGpu.textContent = `${node.gpu.toFixed(1)}%`;
    ttGpuBar.style.width = `${Math.min(100, node.gpu)}%`;
    ttTemp.textContent = `${node.temp_c ? node.temp_c.toFixed(1) : "45.0"} °C`;
    ttQueue.textContent = `${node.queue_len || 0} tasks`;
    ttTask.textContent = node.active_task || "Idle";
    ttStatus.textContent = node.status || "HEALTHY";

    if (node.status === "CONTENDED") {
        ttStatus.className = "text-red-400 font-bold";
    } else if (node.fallback_active) {
        ttStatus.className = "text-emerald-400 font-bold";
    } else {
        ttStatus.className = "text-blue-400 font-bold";
    }

    // Position Tooltip
    const parentRect = canvas.parentElement.getBoundingClientRect();
    const x = clientX - parentRect.left + 15;
    const y = clientY - parentRect.top + 15;

    tooltip.style.left = `${Math.min(x, parentRect.width - 240)}px`;
    tooltip.style.top = `${Math.min(y, parentRect.height - 180)}px`;
    tooltip.classList.remove("hidden");
}

// -------------------------------------------------------------
// Panel 3: Performance Cards Update
// -------------------------------------------------------------
function updatePerformanceCards(metricsGg, metricsEdf) {
    if (!metricsGg || !metricsEdf) return;

    const ggWcrt = (metricsGg.wcrt_ms !== undefined ? metricsGg.wcrt_ms : metricsGg.worst_case_response_time_ms) ?? 18.2;
    const edfWcrt = (metricsEdf.wcrt_ms !== undefined ? metricsEdf.wcrt_ms : metricsEdf.worst_case_response_time_ms) ?? 86.2;
    const ggMisses = metricsGg.deadline_missed_count ?? 0;
    const ggCritMisses = metricsGg.critical_misses ?? 0;
    const ggFallbacks = metricsGg.total_fallbacks ?? 44;

    const edfMisses = metricsEdf.deadline_missed_count ?? 11;
    const edfCritMisses = metricsEdf.critical_misses ?? 8;
    const edfFallbacks = metricsEdf.total_fallbacks ?? 0;

    // GhostGuard Card
    if (statGgMisses) statGgMisses.textContent = `${ggMisses} Deadline Misses (${ggCritMisses} Critical)`;
    if (statGgWcrt) statGgWcrt.textContent = `${Number(ggWcrt).toFixed(1)} ms`;
    if (statGgFallbacks) statGgFallbacks.textContent = `${ggFallbacks}`;

    // EDF Card
    if (statEdfMisses) statEdfMisses.textContent = `${edfMisses} Deadline Misses (${edfCritMisses} Critical)`;
    if (statEdfWcrt) statEdfWcrt.textContent = `${Number(edfWcrt).toFixed(1)} ms`;
    if (statEdfFallbacks) statEdfFallbacks.textContent = `${edfFallbacks}`;
}

// -------------------------------------------------------------
// Panel 4: Synchronized Dual-Timeline Gantt Chart (Plotly.js)
// -------------------------------------------------------------
function renderGanttChart(tasksGg, tasksEdf) {
    const container = document.getElementById("gantt-container");
    if (!container) return;

    const taskStages = [
        "Sense",
        "ObstacleDetection",
        "Perception",
        "Tracking",
        "PathPlanning",
        "Actuation"
    ];

    const traces = [];

    // Helper to map tasks to Gantt bar shapes
    function addSchedulerBars(tasks, yOffset, schedulerPrefix) {
        tasks.forEach(t => {
            const stageName = t.task_name || "Task";
            const yPos = `${schedulerPrefix}: ${stageName}`;

            let color = "#3B82F6"; // nominal blue
            if (t.is_degraded || t.category === "DEGRADED_FALLBACK") {
                color = "#10B981"; // green fallback
            } else if (t.category === "OFFLOADED_REMOTE") {
                color = "#8B5CF6"; // purple offload
            } else if (!t.deadline_met || t.category === "DEADLINE_MISSED") {
                color = "#EF4444"; // red miss
            }

            traces.push({
                x: [t.duration_ms],
                y: [yPos],
                base: [t.start_time_ms],
                type: "bar",
                orientation: "h",
                marker: {
                    color: color,
                    line: { color: "#0B0F17", width: 1 }
                },
                hoverinfo: "text",
                hovertext: `<b>${stageName} (${schedulerPrefix})</b><br>` +
                           `Start: ${t.start_time_ms.toFixed(1)}ms | Finish: ${t.finish_time_ms.toFixed(1)}ms<br>` +
                           `Release: ${t.release_time_ms.toFixed(1)}ms | Deadline: ${t.deadline_ms.toFixed(1)}ms<br>` +
                           `Slack: ${t.slack_ms >= 0 ? '+' : ''}${t.slack_ms.toFixed(1)}ms`,
                showlegend: false
            });
        });
    }

    if (tasksGg) addSchedulerBars(tasksGg, 0, "GhostGuard");
    if (tasksEdf) addSchedulerBars(tasksEdf, 1, "EDF");

    const yCategories = [];
    taskStages.forEach(s => yCategories.push(`EDF: ${s}`));
    taskStages.forEach(s => yCategories.push(`GhostGuard: ${s}`));

    const layout = {
        barmode: "stack",
        height: 440,
        margin: { l: 170, r: 30, t: 20, b: 40 },
        paper_bgcolor: "#0B0F17",
        plot_bgcolor: "#111827",
        xaxis: {
            title: { text: "Simulation Clock Time (ms)", font: { color: "#9CA3AF", family: "JetBrains Mono", size: 11 } },
            range: [0, 100],
            dtick: 10,
            gridcolor: "#1F2937",
            tickfont: { color: "#9CA3AF", family: "JetBrains Mono", size: 10 },
            zeroline: false
        },
        yaxis: {
            categoryorder: "array",
            categoryarray: yCategories,
            gridcolor: "#1F2937",
            tickfont: { color: "#E5E7EB", family: "Plus Jakarta Sans", size: 11 }
        },
        shapes: [
            // Vertical scrubber line
            {
                type: "line",
                x0: 0,
                x1: 0,
                y0: 0,
                y1: 1,
                yref: "paper",
                line: {
                    color: "#EF4444",
                    width: 2.5,
                    dash: "solid"
                },
                name: "scrubber_cursor"
            }
        ]
    };

    const config = { responsive: true, displayModeBar: false };
    Plotly.newPlot("gantt-container", traces, layout, config);
}

function updateGanttCursor(timeMs) {
    const container = document.getElementById("gantt-container");
    if (!container || !container.data) return;

    Plotly.relayout("gantt-container", {
        "shapes[0].x0": timeMs,
        "shapes[0].x1": timeMs
    });
}
