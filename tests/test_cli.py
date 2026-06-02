import pytest

from agentify import cli


def test_parser_uses_invoked_console_script_name(monkeypatch) -> None:
    monkeypatch.setattr(cli.sys, "argv", ["/tmp/agentify-cloud"])

    parser = cli.build_parser()

    assert parser.prog == "agentify-cloud"


def test_server_parser_defaults_md_file_to_agents_md() -> None:
    parser = cli.build_parser()

    args = parser.parse_args(["server"])

    assert args.md_file == "AGENTS.md"


def test_server_parser_accepts_md_file_override() -> None:
    parser = cli.build_parser()

    args = parser.parse_args(["server", "--md-file", "runtime/AGENTS.md"])

    assert args.md_file == "runtime/AGENTS.md"


def test_server_reads_md_file_before_starting(monkeypatch, tmp_path) -> None:
    seed = tmp_path / "seed.md"
    seed.write_text("seed instructions", encoding="utf-8")
    calls = []

    def fake_run_server(port, api_keys, context_system_instruction):
        calls.append((port, api_keys, context_system_instruction))

    monkeypatch.setattr(cli, "run_server", fake_run_server)

    cli.main(["server", "--port", "8001", "--md-file", str(seed), "-api_key", "abc"])

    assert calls == [(8001, {"abc"}, "seed instructions")]


def test_server_fails_fast_when_default_md_file_cannot_be_read(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        cli.main(["server"])

    assert exc_info.value.code == 2
    assert "cannot read markdown seed file AGENTS.md" in capsys.readouterr().err
