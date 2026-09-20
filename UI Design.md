# GhostGuard Research Dashboard — UI Design Specification and Template

**Product type:** Interactive research simulator, run inspector, and evidence browser  
**Audience:** Research team, course evaluator, paper reviewer, and technical demo audience  
**Implementation target:** The existing FastAPI backend and web frontend, upgraded to consume canonical run/event APIs  
**Related document:** `Implementation Plan.md`

## 1. Product Direction

The interface should feel like a precise scientific instrument: calm, legible, inspectable, and honest about evidence. Its purpose is not merely to show that GhostGuard “wins.” It must help a reviewer understand what happened, why the policy chose an action, which assumptions apply, and where uncertainty remains.

### UX goals

- Configure and run a reproducible scenario without editing code.
- Explain one critical task’s journey from release to local/offload/fallback decision.
- Compare policies using identical scenario seeds and aligned timelines.
- Inspect model quality, inference overhead, and federated estimator freshness.
- Inspect the exact schedulability certificate and assumptions.
- Export a run or figure with its provenance intact.

### Non-goals

- A production fleet-control console.
- A visual claim of physical-system safety.
- Decorative animation that obscures timestamps or changes data meaning.
- Showing only the best run or hiding misses and failed interventions.

## 2. Evidence Language

Every major value must carry one of four evidence types. This is a core UI rule.

| Badge | Meaning | Example |
|---|---|---|
| `SIMULATED` | Produced by the discrete-event model | CPU load, task completion time, deadline miss |
| `PREDICTED` | Output of a learned or heuristic model | miss probability, q95 remote latency |
| `MEASURED` | Timed on the named host during this run/build | GNN inference latency |
| `ANALYTICAL` | Computed from a formal analysis under assumptions | RTA WCRT and margin |

Never label a scripted showcase value “measured.” Never use “guaranteed safe” alone. Preferred copy:

- “Schedulable under certificate assumptions”
- “No critical misses observed in 30 simulated seeds”
- “Offload predicted feasible with 4.2 ms conservative margin”
- “Not verified: configured overhead exceeds analyzed bound”

## 3. Information Architecture

Use a persistent application shell with four primary workspaces:

1. **Live Run** — build a scenario, start a run, replay events, and inspect decisions.
2. **Compare** — compare policies or experiment aggregates with uncertainty.
3. **Models** — view GNN validation/calibration/latency and federated model rounds.
4. **Verification** — view timing certificates, assumptions, per-task RTA iterations, and export artifacts.

Secondary destinations:

- Runs archive
- Scenario presets
- Artifact/provenance browser
- Methods/help

### Global shell

```text
+------------------------------------------------------------------------------------------------+
| GhostGuard / Research Console          Run: GG-20260920-0042  [SIMULATED]  API ●  Theme  Help   |
+----------------------+-------------------------------------------------------------------------+
| Live Run             |                                                                         |
| Compare              |                         active workspace                                |
| Models               |                                                                         |
| Verification         |                                                                         |
| -------------------- |                                                                         |
| Runs                 |                                                                         |
| Scenarios            |                                                                         |
| Artifacts            |                                                                         |
| Methods              |                                                                         |
+----------------------+-------------------------------------------------------------------------+
| Code rev 8ac… | Scenario 91f… | Model gnn-1.2.0 | Seed 301 | Units: ms | Reproducible ✓       |
+------------------------------------------------------------------------------------------------+
```

Desktop uses a 224 px collapsible sidebar. Tablet collapses it to icons. Mobile uses a bottom navigation bar for the four primary workspaces and a “More” sheet for secondary destinations.

## 4. Live Run Workspace

### 4.1 Layout

```text
+------------------------------------------------------------------------------------------------+
| Scenario: Correlated Peer Shock     Policy pair: GhostGuard vs EDF      [Run experiment]       |
| Seed 301 • 100 ms • 6 nodes • config 91f…                    [Save preset] [More actions ▾]     |
+----------------------------+-------------------------------------------------------------------+
| SCENARIO BUILDER           | KPI STRIP                                                         |
|                            | Critical DMR | p99 RT | On-time utility | GNN p95 | Offload success |
| Workload                   +-------------------------------------------------------------------+
| Fleet & topology           | MESH / PIPELINE toggle                            Legend / Layers  |
| Faults                     |                                                                   |
| Network                    |                    interactive topology                             |
| Policy                     |                                                                   |
| Advanced                   +-------------------------------------------------------------------+
|                            | EVENT TIMELINE + GANTT                                             |
| Validation ✓               | [|<] [<] [Play] [>]  1x   t=49.500 ms    [============o=========]  |
|                            +------------------------------------------------+------------------+
| [Reset] [Run]             | DECISION INSPECTOR                             | NODE/TASK DETAIL |
+----------------------------+------------------------------------------------+------------------+
```

At widths below 1100 px, the scenario builder becomes a left drawer and the inspector/detail panels stack below the timeline.

### 4.2 Scenario builder

Use grouped sections with a compact summary when collapsed.

**Workload**

- Pipeline preset
- Release model: periodic/sporadic
- Duration, warm-up, drain
- Stage table: period, deadline, WCET, criticality, resource, exit profile
- DAG preview with validation for cycles and unreachable sinks

**Fleet & topology**

- Fleet size
- Device profile per node
- Link editor or topology preset
- CPU/GPU concurrency and scheduler

**Faults**

- Add one or more faults as rows/cards
- Target, resource/link, onset, duration, severity, shape, correlation group
- Timeline preview displaying overlaps

**Network**

- Bandwidth/base latency
- Jitter distribution and parameters
- Loss and retry policy

**Policy**

- Primary and comparison policies
- Predictor/model version
- Risk threshold
- reliability threshold
- safety margin
- watchdog policy

**Advanced**

- Seed or seed set
- instrumentation resolution
- named RNG stream recording
- experiment note

Validation is live and specific. Example: “Fault ends at 130 ms, beyond the 100 ms run; it will be truncated.” Hard errors disable Run; warnings do not.

### 4.3 Run states

- **Draft:** controls enabled; no output panels show stale values without a “previous run” label.
- **Validating:** inline progress, usually under 300 ms.
- **Queued:** run ID assigned; cancellation available.
- **Running:** progress by simulated time and completed policy/seed count; controls locked except safe cancel.
- **Completed:** all panels bound to immutable run ID.
- **Partial:** some policies/seeds failed; successful data remain visible and failures are prominent.
- **Failed:** error summary, expandable technical details, retry with same config, download log.
- **Cancelled:** clearly distinguished from failed.

Do not use a spinner as the only status. Always show text and, for long experiment matrices, completed/total units.

### 4.4 KPI strip

Show five compact metrics. Each card includes label, value, unit, evidence badge, comparison delta, and sample size.

Recommended default KPIs:

- Critical DMR
- p99 response time
- On-time normalized utility
- Predictor p95 overhead
- Timely offload success rate

Example:

```text
CRITICAL DMR          1.7%       ↓ 4.2 pp vs EDF
SIMULATED             95% CI [0.9, 2.8] • n=30 seeds
```

Avoid green-only “wins.” Pair color with arrows, labels, and confidence intervals. If only one deterministic run is selected, replace CI text with “single seed; no uncertainty estimate.”

### 4.5 Mesh visualization

The mesh is for topology and current state, not precise trend reading.

Node anatomy:

- outer ring: state (`nominal`, `contended`, `throttled`, `fallback`, `unreachable`)
- center glyph: device type
- two small bars: CPU and GPU utilization
- badge: queue length
- label: stable short node name
- selection halo: high-contrast outline independent of state color

Link anatomy:

- thickness: configured bandwidth bucket
- dash pattern: degraded or unavailable
- moving packet marker only while a real transmission event is active
- arrow: direction
- label on selection: q50/q95 latency and loss

Optional layers:

- Resource load
- Task placement
- Offload traffic
- Prediction risk
- Fault overlay

Only one dense overlay should be active by default. Provide a textual topology table for accessibility and precise values.

### 4.6 Pipeline view

Toggle from Mesh to Pipeline. Display the DAG left-to-right with stage status and current attempt location. A stage card shows:

- task name and criticality
- absolute deadline
- remaining work estimate
- slack/bound margin
- local/remote attempt state
- selected exit point and utility, if any

Blocked stages are visually quiet. Ready/running/late states use icon plus label, not color alone.

### 4.7 Timeline and Gantt

Use a single synchronized time domain for topology, task Gantt, resource trends, and event cursor.

Tracks:

- Faults and link state
- GhostGuard task attempts by node/resource
- Comparison-policy attempts
- Network request/result/cancel transmissions
- Predictor/decision overhead
- Deadlines and commits

Visual encodings:

- solid bar: running
- hatched bar: queued/waiting
- dotted bar: transmission
- purple outline: degraded/early-exit attempt
- diagonal strike: cancelled attempt
- red deadline marker: missed
- black/white diamond: committed result

Interactions:

- Play/pause; step to previous/next event; speed 0.25x–8x.
- Arrow keys step events; Shift+Arrow steps fixed time; Space toggles playback.
- Drag or click scrubber.
- Click a task attempt to lock selection across all panels.
- Zoom and pan; double-click restores full range.
- “Follow selected task” keeps its next event centered.
- Milestone chips are generated from event types, not fixed timestamps.

The cursor tooltip shows exact simulation time and the ordered events at that timestamp.

### 4.8 Decision inspector

This is the most important explanatory panel. For the selected decision, show:

```text
Decision D-00418 • t=33.125 ms • Perception job P-17

Prediction [PREDICTED]
Miss probability       0.82   threshold 0.61
Time to violation      14.6 ms
Top cause              GPU contention (0.71)
Model                   gnn-1.2.0 calibrated
Inference               0.24 ms [MEASURED on Ryzen …]

Candidate bounds
Action       Finish bound   Margin   Reliability   Result
Local full     41.2 ms      -8.1      —            Rejected
Node 2 q95     27.4 ms      +5.7      0.94         Selected
Node 3 q95     31.9 ms      +1.2      0.81         Feasible
Exit E2        29.3 ms      +3.8      —            Feasible

Reason
Selected Node 2: highest utility among actions satisfying the conservative bound.
```

All values link to a glossary/formula popover. Rejected options remain visible; this prevents the interface from presenting a decision without alternatives.

### 4.9 Node/task detail

Tabbed details:

- **State:** CPU/GPU, temperature, queues, active tasks.
- **Task:** release/deadline, predecessors, attempts, service received, utility.
- **Network:** current links and transmissions.
- **Events:** filtered canonical event list with JSON drawer.

Use small line charts only for time series; never show a gauge when a number plus threshold is clearer.

## 5. Compare Workspace

### 5.1 Purpose

Support honest policy comparison across repeated seeds and scenario families, not just a side-by-side hero card.

### 5.2 Controls

- Select experiment or compatible run set.
- Choose policies, scenario facets, seed subset, metric, and aggregation.
- Toggle absolute value / paired delta.
- Toggle mean + CI / median + IQR / empirical CDF.
- Filter criticality and task/pipeline type.

### 5.3 Default visual set

1. **Critical DMR dot-and-whisker plot** — point estimate and 95% CI by policy.
2. **Paired seed slope plot** — GhostGuard versus strongest baseline; exposes run-to-run variance.
3. **Response-time ECDF** — empirical data only, with deadline markers.
4. **Utility vs DMR Pareto plot** — reveals aggressive fallback trade-offs.
5. **Mechanism table** — offloads, cancellations, fallbacks, overhead, bytes.

Charts include `n`, units, scenario filters, aggregation method, and an “Export with provenance” action.

### 5.4 Comparison table

Columns:

- Policy
- Critical DMR with CI
- Total DMR with CI
- p99 response time
- On-time utility
- Offload timely success
- Fallback rate
- Decision p99
- Paired delta vs reference

Allow sorting but retain the selected reference. Use em dash for not applicable and “missing” for absent data; never coerce missing to zero.

## 6. Models Workspace

### 6.1 Predictor tab

- Model card: version, architecture, parameters, feature schema, data manifest, training date.
- Test metrics: AUROC, AUPRC, recall/precision at chosen threshold, Brier score, ECE, TTV MAE.
- Reliability diagram with sample counts per bin.
- Precision-recall curve with selected operating point.
- Lead-time distribution, split into actionable/non-actionable predictions.
- Inference latency distribution by graph size and host.
- Confusion matrix and error browser linked to replayable runs.

Clearly show whether the active policy used the GNN or heuristic fallback.

### 6.2 Federated tab

- Global model version, age, participating clients, sample counts.
- Round-by-round q95 latency error and reliability calibration.
- Client participation matrix.
- Non-IID distribution summary by device profile.
- Bytes and background compute per round.
- Comparison: static, local-only, federated, pooled-data reference.

Do not include a privacy shield icon unless the page also explains that raw traces are not centralized but FedAvg alone is not formal privacy.

## 7. Verification Workspace

### 7.1 Certificate summary

```text
Certificate FP-RTA-91f3…                         ANALYTICAL
Status: SCHEDULABLE UNDER LISTED ASSUMPTIONS
Configuration: 91f3…   Analyzer: rta-2.0   Generated: 2026-09-20 UTC
Minimum margin: 3.4 ms on ObstacleDetection
```

Statuses:

- `VERIFIED` — teal check, with conditional wording.
- `NOT SCHEDULABLE` — red cross.
- `INCONCLUSIVE` — amber question mark.
- `STALE/MISMATCH` — gray broken-link icon; current configuration hash differs.

### 7.2 Per-task analysis table

Columns:

- Task
- Priority
- `C`, `B`, `J`, `O`, `T`, `D`
- Iterations to convergence
- `R`
- Margin `D-R`
- Status

Selecting a row opens its iteration trace and formula substitution. Provide a copy-ready LaTeX expression generated from the same certificate JSON.

### 7.3 Assumptions panel

Assumptions must be visible without opening a modal:

- scheduler type and priority ordering
- preemption points
- WCET source
- blocking model
- context switch/predictor overhead bound
- background task suspension
- shared-resource assumptions
- unsupported effects

Changing scenario fields that affect the certificate marks it stale immediately.

## 8. Runs and Artifact Browser

### Runs table

- Run ID
- scenario and policy
- seed
- state
- start/duration
- config/model/code hashes
- critical DMR
- provenance health

Filters are encoded in the URL. Selecting a run opens Live Run in immutable replay mode.

### Artifact browser

Group by experiment:

- raw run manifests
- aggregate dataset
- statistics report
- figures PNG/PDF
- LaTeX tables
- verification certificates
- data/model cards

Each artifact shows checksum, creation command, source run count, and download action. A red provenance warning appears if checksums or source references fail validation.

## 9. Visual Design System

### 9.1 Theme

Use a restrained dark technical theme for interactive analysis and a light export theme for paper figures. Avoid glowing neon, animated pulse indicators for steady healthy states, and large marketing gradients.

### 9.2 Color tokens

Dark theme:

| Token | Hex | Use |
|---|---:|---|
| `bg-canvas` | `#0B1020` | Application background |
| `bg-surface` | `#121A2B` | Primary panels |
| `bg-raised` | `#182338` | Raised controls/tooltips |
| `border-subtle` | `#2B3953` | Dividers and panel borders |
| `text-primary` | `#F4F7FB` | Main text |
| `text-secondary` | `#AEBBD0` | Labels and secondary copy |
| `accent` | `#5B8CFF` | Selection and primary action |
| `positive` | `#31C48D` | Met/feasible; always with icon/text |
| `warning` | `#F7B84B` | Risk/uncertainty |
| `danger` | `#F26D6D` | Miss/failure |
| `predicted` | `#A78BFA` | Predicted values |
| `analytical` | `#2DD4BF` | Analytical certificates |
| `measured` | `#38BDF8` | Host-measured values |
| `simulated` | `#94A3B8` | Simulated values |

Check text/background combinations against WCAG 2.2 AA. Color is never the only carrier of state.

### 9.3 Typography

- UI sans: Inter or Plus Jakarta Sans, system fallback.
- Numeric/technical: JetBrains Mono or IBM Plex Mono.
- Base size: 14 px desktop, 16 px form controls on mobile.
- Numeric columns use tabular figures.
- Limit uppercase to short tags and evidence badges.

Type scale:

- Page title: 24/32, 700
- Section title: 18/26, 650
- Card title: 14/20, 650
- Body: 14/21, 400
- Caption: 12/18, 450
- KPI: 28/34, 700 mono/tabular

### 9.4 Spacing and shape

- 4 px base spacing grid: 4, 8, 12, 16, 24, 32.
- Panel padding: 16 px compact, 20–24 px standard.
- Radius: 6 px controls, 8 px panels, fully rounded only for small badges.
- One-pixel borders; shadows reserved for overlays and selected floating panels.
- Minimum pointer target: 44 x 44 px where space permits.

### 9.5 Icons

Use one consistent outline icon set. Required icons must have accessible labels. Do not use Unicode mojibake-prone symbols as control labels; use inline SVG plus text.

## 10. Component Specifications

### Evidence badge

Props: `type`, `compact`, `tooltip`.  
Displays icon, text, and type-specific border. Tooltip explains provenance and links to Methods.

### Metric card

Props: `label`, `value`, `unit`, `evidence`, `interval`, `delta`, `sampleSize`, `status`.  
Empty state says “Not computed.” Loading preserves card size. Long units never wrap away from values.

### Status pill

Use for finite states only. Text examples: “Running 14/63,” “Partial: 2 failed,” “Certificate stale.” A colored dot alone is insufficient.

### Data table

- sticky header, keyboard sortable, visible sort direction
- aligned numeric columns and explicit units in headers
- column picker on dense research tables
- virtualization above 200 rows
- export respects active filters and includes provenance sidecar

### Tooltip/popover

Hover and keyboard focus both work. Tooltips contain brief definitions; interactive content belongs in a popover. Nothing essential is hover-only.

### Toast and error banner

Toasts confirm transient actions. Run failures and provenance problems use persistent banners with a next action.

### Chart frame

Every chart includes title, evidence/source, filters, `n`, legend, accessible summary, and export menu. Chart palettes remain distinguishable under common color-vision deficiencies and grayscale.

## 11. Responsive Behavior

### Desktop, 1280 px and above

- Full sidebar.
- Scenario builder plus visualization/inspector split.
- Up to five KPI cards in one row.

### Tablet, 768–1279 px

- Collapsed sidebar.
- Scenario builder in drawer.
- Two-column KPI grid.
- Inspector below visualization.

### Mobile, below 768 px

- Bottom navigation.
- Scenario controls in full-screen sheet.
- One KPI per horizontal snap card or two compact cards per row.
- Mesh defaults to simplified mode; accessible node list appears first.
- Timeline is horizontally scrollable with event-step controls pinned.
- Large research tables use row cards plus “open full table” landscape view.

No feature required to reproduce or inspect a run may be desktop-only.

## 12. Accessibility Requirements

- Meet WCAG 2.2 AA for contrast and interaction.
- Logical heading structure and landmark regions.
- Visible focus ring on every interactive element.
- Complete keyboard operation for run controls, timeline stepping, tabs, dialogs, and tables.
- Canvas/SVG mesh has an equivalent live-updated table and textual event summary.
- `aria-live="polite"` for run progress; do not announce every playback frame.
- Respect `prefers-reduced-motion`; disable packet animation and smooth auto-pan.
- Do not rely on color, shape, or spatial position alone.
- Chart exports include alt-text captions; the page includes a data table or downloadable CSV.
- Form errors are linked to fields and summarized at the start of the form.

## 13. Performance Budget

- Initial shell JavaScript: target under 250 KB gzip excluding the chosen chart library.
- First usable render: under 2 seconds on a typical laptop for cached/local API.
- Playback: stable 60 fps for normal traces; degrade to 30 fps with sampling for very large traces.
- Do not ship all events for long runs. Request time windows and aggregate server-side.
- Virtualize event lists and tables.
- Perform frame reduction in a Web Worker or on the server.
- Pause animation when the tab is hidden.
- Cache immutable run data by run ID and checksum.

Plotly may be retained initially, but load it only on workspaces that need it. Use SVG/canvas deliberately: SVG for smaller semantic diagrams; canvas/WebGL for dense timelines.

## 14. Frontend Data Model

Use generated types from the OpenAPI schema where practical.

```ts
type EvidenceType = "simulated" | "predicted" | "measured" | "analytical";

interface ValueWithEvidence<T> {
  value: T;
  unit?: "ms" | "us" | "percent" | "bytes" | "ratio";
  evidence: EvidenceType;
  sourceId: string;
  method?: string;
}

interface RunSummary {
  runId: string;
  status: "queued" | "running" | "completed" | "partial" | "failed" | "cancelled";
  progress: { completed: number; total: number; simulatedTimeUs?: number };
  scenarioHash: string;
  codeRevision: string;
  modelVersions: Record<string, string>;
  seeds: number[];
  warnings: string[];
}

interface CanonicalEvent {
  eventId: string;
  timestampUs: number;
  sequence: number;
  type: string;
  deviceId?: string;
  jobId?: string;
  taskId?: string;
  attemptId?: string;
  payload: Record<string, unknown>;
}

interface DecisionRecord {
  decisionId: string;
  timestampUs: number;
  taskId: string;
  prediction: {
    missProbability: number;
    ttvUs?: number;
    causes: Record<string, number>;
    modelVersion: string;
    inferenceUs: number;
  };
  candidates: Array<{
    action: "local" | "offload" | "exit";
    targetId?: string;
    exitPointId?: string;
    finishBoundUs: number;
    marginUs: number;
    expectedUtility: number;
    accepted: boolean;
    rejectionReasons: string[];
  }>;
  selectedIndex: number;
}
```

All time values use integer microseconds over the API. Format in milliseconds at the presentation boundary.

## 15. API-to-UI Behavior

- Create run returns immediately with `run_id`; poll status or use server-sent events/WebSocket for progress.
- Replay requests accept time windows and event filters.
- If WebSocket disconnects, show “Live updates paused” and continue retrying with backoff; immutable completed data remain usable.
- URL contains workspace, run/experiment ID, selection, and time cursor so an exact view can be shared.
- A run’s scenario and result cannot mutate after completion.
- Changing scenario controls creates a draft derived from the run; it never rewrites the original.

## 16. Content and Microcopy

Preferred labels:

- “Run simulation,” not “Prove safety.”
- “Critical deadline-miss ratio,” not “Failures” without definition.
- “Fallback/early exit,” not “Recovery guaranteed.”
- “Comparison policy,” not “losing baseline.”
- “No misses observed,” not “zero misses guaranteed.”
- “Predicted miss probability,” not “GNN confidence” unless confidence is formally defined.

Empty states should teach the next action:

- “No run selected. Choose a completed run or configure a new scenario.”
- “No verification certificate matches this configuration. Run analysis to generate one.”
- “This run used the heuristic predictor; GNN calibration charts do not apply.”

## 17. Reusable Screen Specification Template

Use this template when adding a new screen:

```markdown
### Screen: <name>

**User question:** What exact question does this screen answer?

**Entry points:** Navigation routes or links that open it.

**Required data:** Endpoint, schema, evidence type, units, loading size.

**Primary action:** One action, with authorization and side effect.

**Layout:** Desktop, tablet, and mobile arrangement.

**Components:** Named design-system components and their props.

**States:** Empty, loading, success, partial, error, stale, permission denied.

**Interactions:** Mouse, touch, keyboard, URL/deep-link behavior.

**Accessibility:** Focus order, labels, alternate representation, announcements.

**Performance:** Expected row/event count, virtualization, caching, rendering budget.

**Telemetry:** UI events needed to diagnose usability; never include research results as analytics.

**Acceptance criteria:** Testable Given/When/Then statements.
```

## 18. Reusable Component Specification Template

```markdown
### Component: <name>

**Purpose:**
**Inputs/props:**
**Output/events:**
**Variants:**
**Visual tokens:**
**States:** default, hover, focus, active, disabled, loading, error, empty
**Keyboard behavior:**
**ARIA semantics:**
**Responsive behavior:**
**Data/evidence rules:**
**Unit tests:**
**Visual regression cases:**
```

## 19. Implementation Roadmap

### UI-0 — Correctness cleanup

- Fix character-encoding/mojibake in current HTML and README.
- Replace unconditional safety claims.
- Remove hard-coded metric fallbacks from `frontend/app.js`.
- Label current walkthrough as a deterministic demo.

### UI-1 — Shell and design tokens

- Add semantic tokens as CSS custom properties.
- Build responsive navigation, evidence badges, metric cards, status components, and error states.
- Establish focus styles and reduced-motion behavior.

### UI-2 — API client and immutable runs

- Generate/define typed API client.
- Implement scenario draft, validation, create-run, progress, archive, and replay loading.
- Encode view state in URLs.

### UI-3 — Canonical replay

- Replace authored milestones with an event reducer.
- Synchronize mesh, DAG, timeline, inspector, and cursor.
- Add accessible node/event tables.

### UI-4 — Research comparison

- Build experiment filters, CI plots, paired plots, ECDF, Pareto view, and mechanism table.
- Add provenance-preserving CSV/PDF/PNG export.

### UI-5 — Models and verification

- Add calibration, model latency, FL rounds, certificate summary, per-task RTA, and assumptions.
- Implement stale certificate detection by configuration hash.

### UI-6 — Quality gate

- Playwright flows for run/replay/compare/export.
- axe scan, keyboard-only test, reduced-motion test, and responsive visual regression.
- Performance profile with a large trace.

## 20. UI Acceptance Checklist

- [ ] No experimental value is supplied by an HTML/JavaScript default when API data are missing.
- [ ] Every metric displays units and evidence type.
- [ ] Single-run views do not imply statistical confidence.
- [ ] All milestones come from canonical events.
- [ ] A reviewer can inspect why every candidate was accepted or rejected.
- [ ] Offload cancellation and late-result discard are visible on the timeline.
- [ ] Early-exit point and output utility are visible.
- [ ] Verification claims show assumptions and configuration hash.
- [ ] Model version, calibration state, and measured host are visible.
- [ ] Missing/partial/failed data are not displayed as zero.
- [ ] Mesh and charts have accessible text/table equivalents.
- [ ] Keyboard users can configure, run, replay, inspect, and export.
- [ ] Mobile layout supports the full inspection workflow.
- [ ] Exports include source run IDs and checksums.
- [ ] The interface never uses universal safety language for simulation-only evidence.

## 21. Recommended First Screen to Build

Build **Live Run in immutable replay mode** first, using one completed run and the canonical event API. It exercises the most important architecture: evidence badges, event-derived mesh and DAG state, synchronized timeline, decision explanation, task attempts, and provenance footer. Once replay is correct, add scenario editing and live progress; this prevents the UI from becoming another source of invented state.

