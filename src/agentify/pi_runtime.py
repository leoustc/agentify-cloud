"""Embedded Pi AgentSession bridge process management."""

from __future__ import annotations

import json
import os
import select
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


class PiRuntimeError(RuntimeError):
    """Raised when the embedded Pi runtime cannot be started or addressed."""


@dataclass
class EmbeddedPiRuntime:
    """A running embedded Pi AgentSession bridge."""

    url: str
    process: subprocess.Popen[bytes]

    def close(self) -> None:
        if self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)


def default_vendor_pi_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "vendor" / "pi"


def start_embedded_pi_runtime(
    *,
    vendor_dir: Path | None = None,
    startup_timeout: float = 10.0,
) -> EmbeddedPiRuntime:
    """Start the vendored local Pi AgentSession bridge and return its POST URL."""

    runtime_dir = vendor_dir or default_vendor_pi_dir()
    bridge = runtime_dir / "agentify-bridge.mjs"
    if not runtime_dir.exists():
        raise PiRuntimeError(f"Embedded Pi runtime is missing at {runtime_dir}.")
    if not bridge.is_file():
        raise PiRuntimeError(f"Embedded Pi AgentSession bridge is missing at {bridge}.")

    node = os.environ.get("AGENTIFY_NODE", "node")
    try:
        process = subprocess.Popen(
            [node, str(bridge)],
            cwd=str(runtime_dir),
            env={
                **os.environ,
                "AGENTIFY_PI_BRIDGE_HOST": "127.0.0.1",
                "AGENTIFY_PI_BRIDGE_PORT": "0",
                "AGENTIFY_PI_CWD": os.getcwd(),
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise PiRuntimeError(f"Failed to start embedded Pi bridge with {node!r}: {exc}") from exc

    try:
        url = read_bridge_url(process, startup_timeout)
    except Exception:
        terminate_process(process)
        raise

    return EmbeddedPiRuntime(url=url, process=process)


def read_bridge_url(process: subprocess.Popen[bytes], startup_timeout: float) -> str:
    deadline = time.monotonic() + startup_timeout
    stdout_buffer = b""
    stderr_tail = ""

    while time.monotonic() < deadline:
        remaining = max(0.0, deadline - time.monotonic())
        stdout_buffer += read_available_bytes(process.stdout, timeout=min(remaining, 0.05))
        lines = stdout_buffer.splitlines(keepends=True)
        if lines and not lines[-1].endswith((b"\n", b"\r")):
            stdout_buffer = lines.pop()
        else:
            stdout_buffer = b""
        for raw_line in lines:
            line = raw_line.decode("utf-8", errors="replace")
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("type") == "ready" and isinstance(payload.get("url"), str):
                return payload["url"]
        if process.poll() is not None:
            stderr_tail = read_available(process.stderr)
            raise PiRuntimeError(
                "Embedded Pi bridge exited before reporting an address"
                + (f": {stderr_tail.strip()}" if stderr_tail.strip() else ".")
            )

    stderr_tail = read_available(process.stderr)
    raise PiRuntimeError(
        "Timed out waiting for embedded Pi bridge address"
        + (f": {stderr_tail.strip()}" if stderr_tail.strip() else ".")
    )


def read_available(pipe: object) -> str:
    return read_available_bytes(pipe).decode("utf-8", errors="replace")


def read_available_bytes(pipe: object, *, timeout: float = 0.0, max_bytes: int = 65536) -> bytes:
    if pipe is None:
        return b""
    try:
        fd = pipe.fileno()  # type: ignore[attr-defined]
        os.set_blocking(fd, False)
        ready, _, _ = select.select([fd], [], [], timeout)
        if not ready:
            return b""
        chunks: list[bytes] = []
        total = 0
        while total < max_bytes:
            try:
                chunk = os.read(fd, min(8192, max_bytes - total))
            except BlockingIOError:
                break
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            ready, _, _ = select.select([fd], [], [], 0)
            if not ready:
                break
        return b"".join(chunks)
    except Exception:
        return b""


def terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)
