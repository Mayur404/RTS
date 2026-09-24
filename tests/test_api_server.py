"""
Test suite for PredictiveRuntime FastAPI REST API endpoints.
Verifies simulation execution, benchmark caching, and response schemas.
"""

from pathlib import Path
from xml.etree import ElementTree

from rts_predictive.api.server import (
    health,
    get_section12_trace,
    run_simulation,
    SimulationRequest,
    serve_index
)


def test_api_health():
    res = health()
    assert res["status"] == "ok"
    assert res["service"] == "rts_predictive-api"


def test_api_section12():
    data = get_section12_trace()
    assert data["evidence"] == "SIMULATED"
    assert all(frame["evidence"] == "SIMULATED" for frame in data["frames"])
    assert "frames" in data
    assert "topology" in data
    assert "metrics_gg" in data
    assert "metrics_edf" in data
    assert len(data["frames"]) == 101
    assert 0 <= data["metrics_gg"]["critical_misses"] <= data["metrics_gg"]["deadline_missed_count"]
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
    assert data["evidence"] == "SIMULATED"
    assert "frames" in data
    assert "topology" in data
    assert "metrics_gg" in data
    assert "tasks_gg" in data
    assert 0 <= data["metrics_gg"]["critical_misses"] <= data["metrics_gg"]["deadline_missed_count"]
    assert len(data["topology"]["nodes"]) == 6
    assert "Device_6" in data["frames"][0]["nodes"]


def test_api_frontend_served():
    resp = serve_index()
    assert hasattr(resp, "path")
    assert resp.path.endswith("index.html")


def test_main_ui_serves_self_contained_assets():
    page_path = Path(serve_index().path)
    page = page_path.read_text(encoding="utf-8")
    styles = (page_path.parent / "style.css").read_text(encoding="utf-8")
    light_styles = (page_path.parent / "light.css").read_text(encoding="utf-8")
    script = (page_path.parent / "app.js").read_text(encoding="utf-8")

    assert 'href="/static/style.css"' in page
    assert 'src="/static/app.js"' in page
    assert 'href="/static/light.css"' in page
    assert "cdn." not in page.lower()
    assert "streamlit" not in page.lower()
    assert "live-grid" in styles
    assert "color-scheme: light" in light_styles
    assert 'data-graph="dag"' in page
    assert 'data-graph="interaction"' in page
    assert 'request("/api/live/start"' in script


def test_device_illustrations_are_valid_local_svgs():
    icons = Path(serve_index().path).parent / "icons"
    for kind in ("drone", "server", "rover", "arm", "chip", "station"):
        root = ElementTree.parse(icons / f"{kind}.svg").getroot()
        assert root.tag == "{http://www.w3.org/2000/svg}svg"
        assert root.attrib["viewBox"] == "0 0 96 96"
