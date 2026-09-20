"""
Test suite for GhostGuard FastAPI REST API endpoints.
Verifies simulation execution, benchmark caching, and response schemas.
"""

from ghostguard.api.server import (
    health,
    get_section12_trace,
    run_simulation,
    SimulationRequest,
    serve_index
)


def test_api_health():
    res = health()
    assert res["status"] == "ok"
    assert res["service"] == "ghostguard-api"


def test_api_section12():
    data = get_section12_trace()
    assert "frames" in data
    assert "topology" in data
    assert "metrics_gg" in data
    assert "metrics_edf" in data
    assert len(data["frames"]) == 101
    assert data["metrics_gg"]["critical_misses"] == 0
    assert len(data["tasks_gg"]) > 0
    assert "nodes" in data["frames"][0]
    assert "links" in data["frames"][0]
    assert len(data["topology"]["nodes"]) >= 4


def test_api_simulate():
    req = SimulationRequest(
        contention=0.95,
        fault_time=30.0,
        jitter=6.0,
        fleet_size=6,
        target_node="Node 1"
    )
    data = run_simulation(req)
    assert "frames" in data
    assert "topology" in data
    assert "metrics_gg" in data
    assert "tasks_gg" in data
    assert data["metrics_gg"]["critical_misses"] == 0
    assert len(data["topology"]["nodes"]) == 6
    assert "Device_6" in data["frames"][0]["nodes"]


def test_api_frontend_served():
    resp = serve_index()
    assert hasattr(resp, "path")
    assert resp.path.endswith("index.html")
