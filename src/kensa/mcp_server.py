"""Minimal MCP server so Grok, Claude, and Cursor can read a Kensa review."""

import json
import sys
from pathlib import Path

from kensa.constants import MCP_PROTOCOL, PRODUCT_NAME, VERSION
from kensa.gitrepo import RepoError
from kensa.review import agent_view, repository, send

_TOOLS = (
    {
        "name": "review_status",
        "description": "Open comments, hold state, and whether the review was sent.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository path. Defaults to the working directory."}
            },
        },
    },
    {
        "name": "review_comments",
        "description": "Live review comments and the markdown last sent to .kensa/open.md.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository path. Defaults to the working directory."}
            },
        },
    },
    {
        "name": "review_open",
        "description": "Write .kensa/open.md so the agent can read the current review.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository path. Defaults to the working directory."}
            },
        },
    },
)


def serve_stdio(stdin=None, stdout=None):
    reader = stdin if stdin is not None else sys.stdin.buffer
    writer = stdout if stdout is not None else sys.stdout.buffer
    while True:
        message = _read_message(reader)
        if message is None:
            return
        response = _handle(message)
        if response is not None:
            _write_message(writer, response)


def _handle(message):
    method = message.get("method")
    message_id = message.get("id")
    if method and str(method).startswith("notifications/"):
        return None
    if method == "initialize":
        return _result(
            message_id,
            {
                "protocolVersion": MCP_PROTOCOL,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": PRODUCT_NAME, "version": VERSION},
            },
        )
    if method == "ping":
        return _result(message_id, {})
    if method == "tools/list":
        return _result(message_id, {"tools": list(_TOOLS)})
    if method == "tools/call":
        params = message.get("params") or {}
        try:
            text = _call_tool(params.get("name"), params.get("arguments") or {})
            return _result(message_id, {"content": [{"type": "text", "text": text}]})
        except (RepoError, OSError, ValueError) as exc:
            return _result(
                message_id,
                {"content": [{"type": "text", "text": str(exc)}], "isError": True},
            )
    if message_id is None:
        return None
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "error": {"code": -32601, "message": "method not found"},
    }


def _call_tool(name, arguments):
    root = repository(arguments.get("repo") or Path.cwd())
    if name == "review_open":
        sent = send(root)
        view = agent_view(root)
        payload = {"sent": sent, "review": view}
    elif name in ("review_status", "review_comments"):
        payload = agent_view(root)
    else:
        raise ValueError(f"unknown tool {name}")
    return json.dumps(payload, indent=2)


def _result(message_id, result):
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _read_message(reader):
    headers = {}
    while True:
        line = reader.readline()
        if line == b"":
            return None
        if line in (b"\r\n", b"\n"):
            break
        decoded = line.decode("ascii", errors="replace").strip()
        if ":" in decoded:
            key, value = decoded.split(":", 1)
            headers[key.lower()] = value.strip()
    length = int(headers.get("content-length") or 0)
    if length <= 0:
        return None
    body = reader.read(length)
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def _write_message(writer, message):
    body = json.dumps(message).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    writer.write(header)
    writer.write(body)
    writer.flush()
