"""
FastAPI Server Launcher for PredictiveRuntime Dashboard.
Runs Uvicorn server on port 8000.
"""

import os
import sys

# Ensure UTF-8 stdout on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import uvicorn

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from rts_predictive.api.server import app

def main():
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    print("=" * 60)
    print(f"[PredictiveRuntime] REST Server Launching on http://localhost:{port}")
    print("=" * 60)
    uvicorn.run(app, host=host, port=port, log_level="info")

if __name__ == "__main__":
    main()
