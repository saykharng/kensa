"""Register Kensa's MCP server with the coding agents installed on this machine."""

import json
import os
import shutil
import sys
from pathlib import Path


def agent_invocation():
    binary = os.environ.get("KENSA_BIN")
    if binary:
        return sys.executable, [binary, "mcp"]
    return sys.executable, ["-m", "kensa", "mcp"]


def install(repo, home=None):
    """Write MCP config for agents we can find. Returns notes about each file."""
    home = Path(home) if home is not None else Path.home()
    repo = Path(repo)
    command, args = agent_invocation()
    entry = {"command": command, "args": args}
    notes = []
    notes.append(_merge_mcp_json(repo / ".mcp.json", entry))
    cursor_project = repo / ".cursor"
    cursor_project.mkdir(parents=True, exist_ok=True)
    notes.append(_merge_mcp_json(cursor_project / "mcp.json", entry))
    if (home / ".grok").is_dir() or shutil.which("grok"):
        grok_dir = home / ".grok"
        grok_dir.mkdir(parents=True, exist_ok=True)
        notes.append(_append_grok(grok_dir / "config.toml", command, args))
    claude = home / ".claude.json"
    if claude.is_file():
        notes.append(_merge_mcp_json(claude, entry))
    cursor_user = home / ".cursor"
    if cursor_user.is_dir():
        notes.append(_merge_mcp_json(cursor_user / "mcp.json", entry))
    return notes


def _merge_mcp_json(path, entry):
    data = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return f"skipped {path} (not valid JSON)"
        if not isinstance(loaded, dict):
            return f"skipped {path} (not a JSON object)"
        data = loaded
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    servers["kensa"] = entry
    data["mcpServers"] = servers
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return f"wrote {path}"


def _append_grok(path, command, args):
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    if "[mcp_servers.kensa]" in existing:
        return f"already configured {path}"
    block = (
        "\n[mcp_servers.kensa]\n"
        f"command = {_toml_string(command)}\n"
        f"args = [{', '.join(_toml_string(arg) for arg in args)}]\n"
        "enabled = true\n"
    )
    suffix = "" if existing.endswith("\n") or existing == "" else "\n"
    path.write_text(existing + suffix + block, encoding="utf-8")
    return f"wrote {path}"


def _toml_string(value):
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
