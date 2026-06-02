"""Command line interface for Agentify Cloud."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .auth import parse_api_keys, save_backend_selection
from .server import positive_port, run_server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=Path(sys.argv[0]).name)
    subparsers = parser.add_subparsers(dest="command", required=True)

    login_parser = subparsers.add_parser("login", help="select and record the Pi Agent backend")
    login_parser.add_argument("--backend", help="Pi Agent backend name or URL")

    server_parser = subparsers.add_parser("server", help="start the Agentify Cloud server")
    server_parser.add_argument("--port", type=positive_port, default=8000)
    server_parser.add_argument("--md-file", default="AGENTS.md", help="markdown seed file for Pi agent prompts")
    server_parser.add_argument("-api_key", dest="api_key", help="comma-separated API keys")
    server_parser.add_argument("-api_key_file", dest="api_key_file", help="file with one API key per line")

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "login":
        backend = args.backend or input("Pi Agent backend: ").strip()
        if not backend:
            parser.error("login requires a backend selection")
        path = save_backend_selection(backend)
        print(f"Saved Pi Agent backend selection to {path}")
        return

    if args.command == "server":
        api_keys = parse_api_keys(args.api_key, args.api_key_file)
        markdown_seed = read_markdown_seed(args.md_file, parser)
        run_server(args.port, api_keys, markdown_seed)
        return

    parser.error(f"unknown command: {args.command}")


app = main


def read_markdown_seed(md_file: str, parser: argparse.ArgumentParser) -> str:
    path = Path(md_file)
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        parser.error(f"cannot read markdown seed file {path}: {exc}")


if __name__ == "__main__":
    main()
