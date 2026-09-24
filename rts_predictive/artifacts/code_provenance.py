"""Version identifiers for the Python source used by a simulation run."""

import hashlib
from pathlib import Path
import subprocess


def code_provenance():
    root = Path(__file__).resolve().parents[2]
    digest = hashlib.sha256()
    for path in sorted((root / "rts_predictive").rglob("*.py")):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                              capture_output=True, text=True, check=False)
    status = subprocess.run(["git", "status", "--porcelain"], cwd=root,
                            capture_output=True, text=True, check=False)
    return {
        "code_revision": revision.stdout.strip() if revision.returncode == 0 else None,
        "source_sha256": digest.hexdigest(),
        "working_tree_dirty": bool(status.stdout.strip()),
    }
