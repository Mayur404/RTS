"""
FastAPI REST API and Web Application Server for GhostGuard.
Serves simulation endpoints and the decoupled single-page dashboard on port 8000.
"""

import os
import sys
from typing import Dict, Any, Optional
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# Ensure root directory is in sys.path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from ghostguard.dashboard.timeline_tracer import run_traced_simulation, run_dynamic_scenario

app = FastAPI(
    title="GhostGuard Real-Time Systems API",
    description="Predictive Runtime Protection for Distributed Real-Time AI Systems",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory cache for the deterministic Section 12 benchmark
_SECTION_12_CACHE: Optional[Dict[str, Any]] = None


def get_cached_section12() -> Dict[str, Any]:
    global _SECTION_12_CACHE
    if _SECTION_12_CACHE is None:
        _SECTION_12_CACHE = run_traced_simulation(duration_ms=100.0, step_ms=1.0)
    return _SECTION_12_CACHE


class SimulationRequest(BaseModel):
    contention: float = 0.90      # 0.50 to 0.98
    fault_time: float = 25.0      # 10.0 to 80.0 ms
    jitter: float = 5.0           # 1.0 to 20.0 ms
    fleet_size: int = 4           # 4, 6, 8
    target_node: str = "Node 1"   # "Node 1", "Node 2", "Correlated Both"


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "ghostguard-api", "version": "2.0.0"}


@app.get("/api/section12")
def get_section12_trace():
    """Returns the pre-computed deterministic failure scenario benchmark trace instantly."""
    return get_cached_section12()


@app.post("/api/simulate")
def run_simulation(req: SimulationRequest):
    """Executes a parameterized discrete-event simulation under GhostGuard and EDF."""
    try:
        trace = run_dynamic_scenario(
            fault_time_ms=req.fault_time,
            contention_magnitude=req.contention,
            channel_jitter_ms=req.jitter,
            target_node=req.target_node,
            duration_ms=100.0,
            step_ms=1.0,
            fleet_size=req.fleet_size
        )
        return trace
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Mount frontend static directory
frontend_dir = os.path.join(root_dir, "frontend")
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

    @app.get("/")
    def serve_index():
        index_file = os.path.join(frontend_dir, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)
        return {"message": "Frontend index.html not found"}
