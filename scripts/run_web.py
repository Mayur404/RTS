"""
Launcher script that boots the PredictiveRuntime FastAPI server and opens the dashboard in the browser.
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

import socket
import urllib.request

def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0

def open_browser(port: int = 8000):
    time.sleep(1.2)
    url = f"http://localhost:{port}"
    print(f"[PredictiveRuntime] Opening web dashboard at {url}...")
    try:
        webbrowser.open(url)
    except Exception as e:
        print(f"[PredictiveRuntime] Could not launch browser automatically: {e}")

def main():
    default_port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")

    # If the default port is already occupied, check if PredictiveRuntime is already serving on it
    if is_port_in_use(default_port):
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{default_port}/health")
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                if resp.status == 200:
                    print("=" * 60)
                    print(f"[PredictiveRuntime] Server is already running on http://localhost:{default_port}!")
                    print(f"[PredictiveRuntime] Opening browser dashboard...")
                    print("=" * 60)
                    webbrowser.open(f"http://localhost:{default_port}")
                    return
        except Exception:
            pass

        # If occupied by another process, find next free port
        port = default_port
        while is_port_in_use(port) and port < default_port + 20:
            port += 1
        if port != default_port:
            print(f"[PredictiveRuntime] Port {default_port} in use. Switching to port {port}.")
    else:
        port = default_port

    print("=" * 60)
    print(f"[PredictiveRuntime] Web Dashboard & API Server on http://localhost:{port}")
    print("=" * 60)

    print("[PredictiveRuntime] Loading simulator and AI libraries. First startup may take a moment...", flush=True)
    from rts_predictive.api.server import app
    print("[PredictiveRuntime] Libraries loaded. Starting web server...", flush=True)

    threading.Thread(target=open_browser, args=(port,), daemon=True).start()
    uvicorn.run(app, host=host, port=port, log_level="info")

if __name__ == "__main__":
    main()
