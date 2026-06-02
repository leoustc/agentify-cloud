import subprocess
import sys
import time
from pathlib import Path

import pytest

from agentify.pi_runtime import PiRuntimeError, read_available, start_embedded_pi_runtime


def test_bridge_entrypoint_uses_vendored_pi_agent_session() -> None:
    bridge = Path("src/vendor/pi/agentify-bridge.mjs").read_text(encoding="utf-8")

    assert '@earendil-works/pi-coding-agent' in bridge
    assert "createAgentSession" in bridge
    assert "session.prompt" in bridge
    assert "responseForPrompt" not in bridge


def test_read_available_does_not_block_on_live_partial_stderr() -> None:
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys, time; sys.stderr.write('partial stderr'); sys.stderr.flush(); time.sleep(5)",
        ],
        stderr=subprocess.PIPE,
    )
    try:
        time.sleep(0.1)
        started = time.monotonic()
        output = read_available(process.stderr)
        elapsed = time.monotonic() - started
    finally:
        process.terminate()
        process.wait(timeout=2)

    assert output == "partial stderr"
    assert elapsed < 0.5


def test_embedded_startup_timeout_is_bounded_with_live_partial_stderr(tmp_path: Path) -> None:
    bridge = tmp_path / "agentify-bridge.mjs"
    bridge.write_text(
        "process.stderr.write('partial startup failure'); setInterval(() => {}, 1000);\n",
        encoding="utf-8",
    )

    started = time.monotonic()
    with pytest.raises(PiRuntimeError, match="Timed out waiting for embedded Pi bridge address") as exc:
        start_embedded_pi_runtime(vendor_dir=tmp_path, startup_timeout=0.2)
    elapsed = time.monotonic() - started

    assert "partial startup failure" in str(exc.value)
    assert elapsed < 1.0
