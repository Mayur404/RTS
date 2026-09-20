"""
Helper script to launch the Streamlit live dashboard.
"""

import subprocess
import sys
import os

def main():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    app_path = os.path.join(root_dir, "ghostguard", "dashboard", "app.py")
    venv_python = os.path.join(root_dir, ".venv", "Scripts", "python.exe")
    python_exe = venv_python if os.path.exists(venv_python) else sys.executable

    print(f"Using Python: {python_exe}")
    print(f"Launching Streamlit Dashboard from: {app_path}")
    cmd = [python_exe, "-m", "streamlit", "run", app_path]
    subprocess.run(cmd, cwd=root_dir)

if __name__ == "__main__":
    main()
