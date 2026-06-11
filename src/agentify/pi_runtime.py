"""Embedded Pi AgentSession bridge process management."""

from __future__ import annotations

import json
import os
import select
import shutil
import subprocess
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import IO


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


def materialize_vendor_pi_runtime(vendor_dir: Path) -> Path:
    """Return a Pi runtime directory with npm dependencies installed."""

    dependency = vendor_dir / "node_modules" / "@earendil-works" / "pi-coding-agent"
    if dependency.exists():
        return vendor_dir

    package_json = vendor_dir / "package.json"
    package_lock = vendor_dir / "package-lock.json"
    bridge = vendor_dir / "agentify-bridge.mjs"
    missing = [path.name for path in (package_json, package_lock, bridge) if not path.is_file()]
    if missing:
        raise PiRuntimeError(
            "Embedded Pi runtime cannot be materialized because "
            f"{', '.join(missing)} {'is' if len(missing) == 1 else 'are'} missing from {vendor_dir}."
        )

    cache_dir = Path(
        os.environ.get(
            "AGENTIFY_PI_VENDOR_CACHE",
            Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "agentify-cloud" / "pi-runtime",
        )
    )
    digest = sha256()
    for path in (package_json, package_lock, bridge):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    target = cache_dir / digest.hexdigest()[:16]
    cached_dependency = target / "node_modules" / "@earendil-works" / "pi-coding-agent"
    ready_marker = target / ".agentify-pi-runtime-ready"
    if ready_marker.is_file() and cached_dependency.exists():
        return target

    npm = os.environ.get("AGENTIFY_NPM", "npm")
    temp_target = cache_dir / f".materializing-{os.getpid()}-{time.monotonic_ns()}"
    cache_dir.mkdir(parents=True, exist_ok=True)
    lock_path = cache_dir / f"{target.name}.lock"
    with open(lock_path, "a+b") as lock_file:
        lock_cache_target(lock_file)
        if ready_marker.is_file() and cached_dependency.exists():
            return target
        if target.exists():
            shutil.rmtree(target)
        materialize_cache_target(
            npm=npm,
            temp_target=temp_target,
            target=target,
            package_json=package_json,
            package_lock=package_lock,
            bridge=bridge,
            ready_marker_name=ready_marker.name,
        )
    return target


def lock_cache_target(lock_file: IO[bytes]) -> None:
    try:
        import fcntl
    except ImportError as exc:  # pragma: no cover - fcntl is available on supported Unix-like targets.
        raise PiRuntimeError("Embedded Pi runtime cache locking requires fcntl on this platform.") from exc

    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)


def materialize_cache_target(
    *,
    npm: str,
    temp_target: Path,
    target: Path,
    package_json: Path,
    package_lock: Path,
    bridge: Path,
    ready_marker_name: str,
) -> None:
    try:
        if temp_target.exists():
            shutil.rmtree(temp_target)
        temp_target.mkdir(parents=True)
        for path in (package_json, package_lock, bridge):
            shutil.copy2(path, temp_target / path.name)
        result = subprocess.run(
            [npm, "ci", "--omit=dev"],
            cwd=str(temp_target),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=300,
            check=False,
        )
    except OSError as exc:
        shutil.rmtree(temp_target, ignore_errors=True)
        raise PiRuntimeError(
            f"Embedded Pi runtime needs npm dependencies, but {npm!r} could not be started: {exc}."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        shutil.rmtree(temp_target, ignore_errors=True)
        output = "\n".join(part for part in (exc.stdout, exc.stderr) if part)
        raise PiRuntimeError(
            "Timed out while materializing embedded Pi runtime with npm ci --omit=dev"
            + (f": {output.strip()}" if output.strip() else ".")
        ) from exc

    if result.returncode != 0:
        shutil.rmtree(temp_target, ignore_errors=True)
        output = "\n".join(part for part in (result.stdout, result.stderr) if part)
        raise PiRuntimeError(
            "Failed to materialize embedded Pi runtime with npm ci --omit=dev. "
            "Install Node.js/npm and ensure the npm registry is reachable, then retry."
            + (f"\n{output.strip()}" if output.strip() else "")
        )

    (temp_target / ready_marker_name).write_text("ok\n", encoding="utf-8")
    temp_target.replace(target)


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
    runtime_dir = materialize_vendor_pi_runtime(runtime_dir)
    bridge = runtime_dir / "agentify-bridge.mjs"

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
