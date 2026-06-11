import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from agentify.pi_runtime import PiRuntimeError, materialize_vendor_pi_runtime, read_available, start_embedded_pi_runtime


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
    (tmp_path / "node_modules" / "@earendil-works" / "pi-coding-agent").mkdir(parents=True)
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


def write_minimal_vendor_runtime(vendor_dir: Path) -> None:
    vendor_dir.mkdir()
    (vendor_dir / "agentify-bridge.mjs").write_text(
        "\n".join(
            [
                "import http from 'node:http';",
                "import '@earendil-works/pi-coding-agent';",
                "const server = http.createServer();",
                "server.listen(0, '127.0.0.1', () => {",
                "  const address = server.address();",
                "  process.stdout.write(JSON.stringify({ type: 'ready', url: `http://127.0.0.1:${address.port}` }) + '\\n');",
                "});",
                "process.on('SIGTERM', () => server.close(() => process.exit(0)));",
            ]
        ),
        encoding="utf-8",
    )
    (vendor_dir / "package.json").write_text(
        '{"dependencies":{"@earendil-works/pi-coding-agent":"0.78.0"}}\n',
        encoding="utf-8",
    )
    (vendor_dir / "package-lock.json").write_text(
        '{"lockfileVersion":3,"packages":{"":{"dependencies":{"@earendil-works/pi-coding-agent":"0.78.0"}}}}\n',
        encoding="utf-8",
    )


def test_materializes_missing_node_modules_into_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vendor_dir = tmp_path / "vendor-pi"
    cache_dir = tmp_path / "cache"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_npm = fake_bin / "npm"
    fake_npm.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                "set -eu",
                "test \"$1\" = ci",
                "test \"$2\" = --omit=dev",
                "mkdir -p node_modules/@earendil-works/pi-coding-agent",
                "printf '{\"type\":\"module\"}\\n' > node_modules/@earendil-works/pi-coding-agent/package.json",
                "printf 'export {};\\n' > node_modules/@earendil-works/pi-coding-agent/index.js",
            ]
        ),
        encoding="utf-8",
    )
    fake_npm.chmod(0o755)
    write_minimal_vendor_runtime(vendor_dir)
    monkeypatch.setenv("AGENTIFY_PI_VENDOR_CACHE", str(cache_dir))
    monkeypatch.setenv("AGENTIFY_NPM", str(fake_npm))

    materialized_dir = materialize_vendor_pi_runtime(vendor_dir)

    assert materialized_dir != vendor_dir
    assert (materialized_dir / "agentify-bridge.mjs").is_file()
    assert (materialized_dir / ".agentify-pi-runtime-ready").is_file()
    assert (materialized_dir / "node_modules" / "@earendil-works" / "pi-coding-agent").is_dir()


def test_concurrent_first_run_materialization_uses_one_cache_winner(tmp_path: Path) -> None:
    vendor_dir = tmp_path / "vendor-pi"
    cache_dir = tmp_path / "cache"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    npm_log = tmp_path / "npm.log"
    fake_npm = fake_bin / "npm"
    fake_npm.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                "set -eu",
                "test \"$1\" = ci",
                "test \"$2\" = --omit=dev",
                f"printf '%s\\n' \"$$\" >> {npm_log}",
                "sleep 0.25",
                "mkdir -p node_modules/@earendil-works/pi-coding-agent",
                "printf '{\"type\":\"module\"}\\n' > node_modules/@earendil-works/pi-coding-agent/package.json",
                "printf 'export {};\\n' > node_modules/@earendil-works/pi-coding-agent/index.js",
            ]
        ),
        encoding="utf-8",
    )
    fake_npm.chmod(0o755)
    write_minimal_vendor_runtime(vendor_dir)

    probe = "\n".join(
        [
            "from pathlib import Path",
            "from agentify.pi_runtime import materialize_vendor_pi_runtime",
            f"path = materialize_vendor_pi_runtime(Path({str(vendor_dir)!r}))",
            "print(path)",
        ]
    )
    env = {
        **os.environ,
        "AGENTIFY_PI_VENDOR_CACHE": str(cache_dir),
        "AGENTIFY_NPM": str(fake_npm),
        "PYTHONPATH": str(Path.cwd() / "src"),
    }
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", probe],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(4)
    ]
    results = [process.communicate(timeout=10) for process in processes]

    for process, (stdout, stderr) in zip(processes, results, strict=True):
        assert process.returncode == 0, stderr
        assert stdout.strip()
    materialized_dirs = {Path(stdout.strip()) for stdout, _ in results}
    assert len(materialized_dirs) == 1
    materialized_dir = materialized_dirs.pop()
    assert (materialized_dir / ".agentify-pi-runtime-ready").is_file()
    assert (materialized_dir / "node_modules" / "@earendil-works" / "pi-coding-agent").is_dir()
    assert len(npm_log.read_text(encoding="utf-8").splitlines()) == 1


def test_embedded_startup_uses_materialized_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vendor_dir = tmp_path / "vendor-pi"
    cache_dir = tmp_path / "cache"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_npm = fake_bin / "npm"
    fake_npm.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                "set -eu",
                "mkdir -p node_modules/@earendil-works/pi-coding-agent",
                "printf '{\"type\":\"module\"}\\n' > node_modules/@earendil-works/pi-coding-agent/package.json",
                "printf 'export {};\\n' > node_modules/@earendil-works/pi-coding-agent/index.js",
            ]
        ),
        encoding="utf-8",
    )
    fake_npm.chmod(0o755)
    write_minimal_vendor_runtime(vendor_dir)
    monkeypatch.setenv("AGENTIFY_PI_VENDOR_CACHE", str(cache_dir))
    monkeypatch.setenv("AGENTIFY_NPM", str(fake_npm))

    runtime = start_embedded_pi_runtime(vendor_dir=vendor_dir, startup_timeout=2)
    try:
        assert runtime.url.startswith("http://127.0.0.1:")
    finally:
        runtime.close()


def test_materialization_failure_explains_npm_requirement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vendor_dir = tmp_path / "vendor-pi"
    write_minimal_vendor_runtime(vendor_dir)
    monkeypatch.setenv("AGENTIFY_PI_VENDOR_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("AGENTIFY_NPM", str(tmp_path / "missing-npm"))

    with pytest.raises(PiRuntimeError, match="needs npm dependencies") as exc:
        materialize_vendor_pi_runtime(vendor_dir)

    assert "could not be started" in str(exc.value)
