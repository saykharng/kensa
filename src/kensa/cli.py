"""Command line for Kensa."""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from urllib.parse import quote

from kensa.constants import HOST, PORT, SERVER_FILE, VERSION
from kensa.gitrepo import RepoError, discover
from kensa.mcp_server import serve_stdio
from kensa.paths import kensa_home
from kensa.server import serve
from kensa.setup_agents import install


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        return _main(argv)
    except RepoError as exc:
        print(str(exc), file=sys.stderr)
        return 1


def _main(argv):
    if not argv:
        _open_tab(Path.cwd())
        return 0
    command = argv[0]
    if command in ("-h", "--help", "help"):
        print(_help())
        return 0
    if command in ("-v", "--version"):
        print(VERSION)
        return 0
    if command == "serve":
        serve()
        return 0
    if command == "mcp":
        serve_stdio()
        return 0
    if command == "setup":
        for note in install(discover(Path.cwd())):
            print(note)
        return 0
    if command == "pr":
        print("Pass a branch name. Example: kensa feature", file=sys.stderr)
        return 1
    if len(argv) != 1:
        print(_help(), file=sys.stderr)
        return 1
    _open_tab(Path.cwd(), branch=command)
    return 0


def _open_tab(start, branch=None):
    root = discover(start)
    _ensure_server()
    query = f"repo={quote(str(root))}"
    if branch:
        query += f"&branch={quote(branch)}"
    url = f"http://{HOST}:{PORT}/?{query}"
    print(url)
    webbrowser.open(url)


def _ensure_server():
    if _healthy():
        return
    home = kensa_home()
    home.mkdir(parents=True, exist_ok=True)
    log_path = home / "server.log"
    log = open(log_path, "a", encoding="utf-8")
    command = _server_command()
    subprocess.Popen(
        command,
        start_new_session=True,
        stdout=log,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        env=os.environ.copy(),
    )
    for _ in range(50):
        if _healthy():
            return
        time.sleep(0.1)
    raise RepoError(f"Kensa did not start. See {log_path}")


def _server_command():
    binary = os.environ.get("KENSA_BIN")
    if binary:
        return [sys.executable, binary, "serve"]
    return [sys.executable, "-m", "kensa", "serve"]


def _healthy():
    url = f"http://{HOST}:{PORT}/api/health"
    try:
        with urllib.request.urlopen(url, timeout=0.3) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return False
    return bool(payload.get("ok"))


def _help():
    record = ""
    path = kensa_home() / SERVER_FILE
    if path.is_file():
        record = f"\nServer record: {path}"
    return (
        "Kensa reviews code in a browser tab.\n"
        "\n"
        "  kensa              Review your uncommitted changes\n"
        "  kensa <branch>     Review that branch against the default branch\n"
        "  kensa setup        Register the MCP server with agents you have\n"
        "  kensa serve        Run the server in the foreground\n"
        "  kensa mcp          Speak MCP on stdin. Agents launch this.\n"
        f"{record}"
    )
