# Using the facility simulation

```powershell
cd D:\Course\RTS2
.venv\Scripts\python.exe scripts\run_web.py
```

Open the printed address, normally http://localhost:8000. Stop the server with
Ctrl+C. The interface has only Simulation and Results.

## Facility and moving devices

The scene contains a service road, operations and logistics buildings, an edge
compute hub, assembly cells, loading bays, trees and a drone pad. Drones patrol
the courtyard and rovers follow the road, with colored vehicle bodies turning
along their route. Travel is illustrative and follows accepted simulation time;
it does not alter RF, link delays, task scheduling or experiment results.

**Animate travel** switches this presentation movement on/off. Pausing the engine
freezes it. Dragging or keyboard-moving a device holds that device off its route
until **Reset devices** clears the manual placement. Fixed servers and assembly
robots remain stationary. Reduced motion suppresses interpolation and propellers.

Live CPU/GPU task labels resolve the exact recorded resource owner, including
remote tasks and controller operations. Background occupancy and GPU CPU
reservations are distinguished from an idle lane. The selected device's main
workflow and its other workflow graphs are shown together. Click a node in any
graph to inspect the exact task; dependency arrows use committed predecessor
records. Selecting a different task can switch the primary workflow.

## Arrange and inspect devices

The facility starts with six devices. Each icon has recorded simulated CPU/GPU
capacity percentages and bars, including configured interference and reservations.
They are occupied capacity, not task progress or measured hardware utilization.

- Drag a device to reposition it; subsequent snapshots retain that position.
- Drag empty ground to pan. Scroll the wheel or use a two-finger pinch to zoom.
- Use **+ / −** to zoom, **Fit** to restore the overview, **Focus device** to
  enlarge the selected device, and **Reset devices** to restore their positions.
- Click a device or use the device dropdown to display its task graph.
- Focus the ground and use arrow keys to pan, **+ / −** to zoom, or **Home / 0**
  to fit. Focus a device and press arrows to move it (Shift moves farther).
- Enter/Space selects a focused device or task. Tab navigation preserves focus
  across simulation snapshots.

Facility coordinates and travel routes are presentation only. Dragging changes layout;
network timing still uses the scenario's configured model. This is a distributed
real-time task simulator, not a physical 5G/RF or robot-motion model.

Task arrows require committed predecessor results. The selected device's latest
released job is shown, unless an exact inspected task pins its older job. All
workflows continue running and sharing resources. Offloaded nodes show their
execution host; an early-exit GPU node says **early-exit path**, without implying
all four full-execution layers were completed.

Live arrows represent actual in-flight requests, results, cancellations and
learning updates. Queued and completed packets are excluded. Moving dots use
accepted simulated observations and pause during sender serialization. A dashed
orange watchdog/fallback arrow represents the recorded mechanism, not an extra
network packet.

## Control workload and playback

The controls select 2–8 devices, mixed/vision-and-planning/control/telemetry tasks,
and task release rates from 50–150%. A settings change starts a fresh paired run
after any in-flight step finishes. Device count and task mix use the existing
validated scenario API. Custom fleet/workload/model calibration is unvalidated;
the recorded outcomes remain actual results of the configured simulation.

Conditions include normal, busy, thermal, unreliable and **Recovery stress**.
The default stress configuration preserves Device_1's origin fault and injects
peer faults from 98–300 ms: 70% CPU interference, 95% GPU interference, 20 ms extra
link delay and 20% loss. These are explicit inputs saved in the run configuration.
They exercise recovery; they do not fix or guarantee the outcome.

The speed slider ranges from 0.05× to 3× relative to normal presentation pacing.
Simulation work budgets do not change with playback speed. **Pause / Resume** holds
or continues the engine; an outstanding request finishes before pause settles.
**Step 1 ms** advances exactly 1000 microseconds while paused. **New run** starts a
fresh run with seed 1000. Hidden browser tabs stop requesting new steps.

## See watchdog, fallback and early exit

1. Select **Recovery stress** and the vision or mixed workload.
2. Click **Slow motion**. It selects 0.05× and enables pause after a watchdog abort.
3. Resume. The engine pauses after an accepted snapshot containing that event.
4. Read the protection strip's recorded timestamps: remote request → watchdog
   abort → fallback admitted → early exit → task result committed. Future or absent
   milestones remain labeled **Not recorded**. Step 1 ms to follow local execution.
5. Select **Any early exit** to stop on a local exit instead. Uncheck the pause
   option to continue freely. Click a task to inspect that exact task's records.

An event can occur between two accepted snapshots; automatic pause stops after
the snapshot, not before its canonical timestamp. Slow pacing reduces that gap.
Cancellation can still be in transit while local fallback executes. A recovered
task does not establish that its enclosing job met its deadline. A scenario with
no watchdog/exit displays no invented intervention. Reduced motion suppresses
packet interpolation; brief smoothing never extrapolates future simulator events.

## Read the final deadline results

Start with the large Results explanation. It says whether protection reduced
misses, increased them, or finished with the same total. While work remains active,
it explicitly says the result is not final.

- **Finished on time:** the workflow's final output committed by its deadline.
- **Prevented workflow misses:** EDF missed these exact workflows, while
  protection completed them. The comparison does not assign credit to one
  particular mechanism.
- **Extra workflow misses:** EDF completed these workflows but protection missed
  them. Net fewer misses = prevented minus extra, once every pair is resolved.
- **Fallback tasks:** unique tasks with a recorded admission to a shorter path.
  Their finished/missed/skipped/active outcomes are listed separately. A finished
  fallback task does not imply all later stages in its workflow met the deadline.
- **Watchdog interventions:** remote attempts aborted so local recovery could
  start. **Early-exit activations** include local shorter paths and watchdog
  recovery paths; the two counters overlap and must not be added as saved jobs.
- **Simulated time:** elapsed model time, the work-release interval and the
  following drain. It is separate from how long the browser/server took to run.
- **Completion time:** release to final output for on-time workflows only, shown
  for each policy. Different completion sets can make these averages incomparable
  as a paired latency effect. The closest finish shows remaining deadline slack.

The device table shows protected on-time, missed and active workflows, paired
prevented/extra misses and fallback-task counts. Expand **Which workflows changed?**
for exact identities and deadline budgets. Counts remain visible even when they
are zero; the UI does not assume protection improves every configured scenario.
A consistency alert appears if record identities, counts or deadline timings do
not reconcile. Full raw traces and manifests remain the evidence source.

## Results and evidence

Results compare baseline EDF with predictive protection on identical seeded
releases, demands and injected conditions. Miss rate is missed end-to-end jobs
divided by all released jobs. Active jobs stay in the provisional denominator;
the result is final after the release window and drain finish.

Paired categories retain both met, met only with protection, missed only with
protection, both missed and still active. The time series uses accepted simulation
observations. Expand **More results & evidence** for extra counters, configured
utility, model scope, configuration/model identities and downloadable canonical
events, metrics and checksummed manifests. Utility excludes missed tasks.

Custom scenarios and other comparators remain available through `/docs`.
Use `scripts/check_facility_scene.py`, `scripts/check_ground_map.py`, `scripts/check_simple_simulation.py`, and
`scripts/check_simple_playback.py` for the current UI. Retired dashboard versions and their browser checks are excluded from the clean repository.
