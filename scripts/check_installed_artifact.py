"""Check that the built wheel starts the embedded Pi runtime after installation."""

from __future__ import annotations

import glob
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def run(command: list[str], **kwargs: object) -> None:
    subprocess.run(command, check=True, **kwargs)


def main() -> int:
    wheels = sorted(glob.glob("dist/agentify_cloud-*.whl"))
    if len(wheels) != 1:
        print(f"Expected exactly one built wheel, found {len(wheels)}: {wheels}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="agentify-installed-artifact-") as tmp:
        temp_dir = Path(tmp)
        venv_dir = temp_dir / "venv"
        cache_dir = temp_dir / "pi-cache"
        run([sys.executable, "-m", "venv", str(venv_dir)])
        python = venv_dir / "bin" / "python"
        run([str(python), "-m", "pip", "install", "-q", "--upgrade", "pip"])
        run([str(python), "-m", "pip", "install", "-q", wheels[0]])
        env = {**os.environ, "AGENTIFY_PI_VENDOR_CACHE": str(cache_dir)}
        probe = """
from agentify.pi_runtime import default_vendor_pi_dir, start_embedded_pi_runtime

vendor = default_vendor_pi_dir()
if (vendor / "node_modules").exists():
    raise SystemExit(f"installed artifact unexpectedly contains node_modules at {vendor}")
runtime = start_embedded_pi_runtime(startup_timeout=120)
try:
    print(f"embedded Pi bridge ready: {runtime.url}")
finally:
    runtime.close()
"""
        run([str(python), "-c", probe], env=env)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
