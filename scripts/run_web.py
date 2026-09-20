"""
Launcher script that boots the GhostGuard FastAPI server and opens the dashboard in the browser.
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

import time
import webbrowser
import threading
import uvicorn

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from ghostguard.api.server import app

def open_browser():
    time.sleep(1.2)
    url = "http://localhost:8000"
    print(f"[GhostGuard] Opening web dashboard at {url}...")
    try:
        webbrowser.open(url)
    except Exception as e:
        print(f"[GhostGuard] Could not launch browser automatically: {e}")

def main():
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    print("=" * 60)
    print(f"[GhostGuard] Web Dashboard & API Server on http://localhost:{port}")
    print("=" * 60)
    
    threading.Thread(target=open_browser, daemon=True).start()
    uvicorn.run(app, host=host, port=port, log_level="info")

if __name__ == "__main__":
    main()
