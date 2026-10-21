"""Localhost HTTP server for the Kensa browser tab."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from kensa.comments import ReviewError
from kensa.constants import HOST, MAX_BODY_BYTES, POLL_MS, PORT, VERSION
from kensa.gitrepo import RepoError
from kensa.paths import server_path
from kensa.review import (
    create_comment,
    file_outline,
    jump,
    mark_hunk,
    open_branch,
    open_branch_file,
    open_file,
    open_pull_file,
    remove_comment,
    repository,
    save_file,
    search_files,
    send,
    set_hold,
    snapshot,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def do_PUT(self):
        self._route("PUT")

    def do_DELETE(self):
        self._route("DELETE")

    def log_message(self, fmt, *args):
        return

    def _route(self, method):
        try:
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            query = parse_qs(parsed.query)
            if method == "GET" and path in ("/", "/index.html"):
                self._static("index.html")
                return
            if method == "GET" and path in ("/app.js", "/app.css"):
                self._static(path[1:])
                return
            if method == "GET" and path == "/api/health":
                self._json({"ok": True, "version": VERSION, "pollMs": POLL_MS})
                return
            body = self._body() if method in ("POST", "PUT") else {}
            repo = _one(query, "repo") or body.get("repo")
            root = repository(repo) if repo else None
            self._api(method, path, query, body, root)
        except (ReviewError, RepoError, ValueError) as exc:
            self._json({"error": str(exc)}, status=400)
        except Exception:
            import traceback

            traceback.print_exc()
            self._json({"error": "internal error"}, status=500)

    def _api(self, method, path, query, body, root):
        if root is None:
            raise RepoError("missing repo")
        if method == "GET" and path == "/api/snapshot":
            self._json(snapshot(root))
            return
        if method == "GET" and path == "/api/file":
            self._json(open_file(root, _required(query, "path")))
            return
        if method == "PUT" and path == "/api/file":
            self._json(save_file(root, body.get("path", ""), body.get("content")))
            return
        if method == "POST" and path == "/api/comments":
            comment = create_comment(
                root,
                body.get("path", ""),
                int(body.get("line") or 0),
                body.get("severity", ""),
                body.get("body", ""),
            )
            self._json(comment, status=201)
            return
        if method == "DELETE" and path == "/api/comments":
            remove_comment(root, _required(query, "id"))
            self._json({"ok": True})
            return
        if method == "POST" and path == "/api/hunks":
            mark_hunk(root, body.get("path", ""), body.get("header", ""), body.get("mark", ""))
            self._json({"ok": True})
            return
        if method == "POST" and path == "/api/hold":
            self._json(set_hold(root, body.get("hold")))
            return
        if method == "POST" and path == "/api/send":
            self._json(send(root))
            return
        if method == "GET" and path == "/api/files":
            self._json({"files": search_files(root, _one(query, "q") or "")})
            return
        if method == "GET" and path == "/api/outline":
            self._json({"outline": file_outline(root, _required(query, "path"))})
            return
        if method == "GET" and path == "/api/jump":
            self._json({"hits": jump(root, _required(query, "symbol"))})
            return
        if method == "GET" and path == "/api/branch":
            self._json(open_branch(root, _required(query, "name"), _one(query, "base")))
            return
        if method == "GET" and path == "/api/branch/file":
            self._json(
                open_branch_file(
                    root,
                    _required(query, "name"),
                    _required(query, "path"),
                    _one(query, "base"),
                )
            )
            return
        if method == "POST" and path == "/api/branch/submit":
            from kensa.pull_request import find_pull_request, submit_pull_request
            from kensa.review import agent_view

            overview = open_branch(root, body.get("name") or "", body.get("base"))
            pull = overview.get("pullRequest") or find_pull_request(root, overview["resolved"])
            if not pull:
                raise RepoError("this branch has no GitHub pull request to submit")
            result = submit_pull_request(
                root,
                pull["number"],
                body.get("verdict", ""),
                body.get("summary", ""),
                agent_view(root)["comments"],
            )
            self._json(result)
            return
        if method == "GET" and path == "/api/pr":
            from kensa.pull_request import load_pull_request

            loaded = load_pull_request(root, _required(query, "number"))
            loaded.pop("diff", None)
            self._json(loaded)
            return
        if method == "GET" and path == "/api/pr/file":
            self._json(
                open_pull_file(root, _required(query, "number"), _required(query, "path"))
            )
            return
        if method == "POST" and path == "/api/pr/submit":
            from kensa.pull_request import submit_pull_request
            from kensa.review import agent_view

            result = submit_pull_request(
                root,
                body.get("number"),
                body.get("verdict", ""),
                body.get("summary", ""),
                agent_view(root)["comments"],
            )
            self._json(result)
            return
        self._json({"error": "not found"}, status=404)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            raise ReviewError("request is too large")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ReviewError("request body is not JSON") from exc
        if not isinstance(data, dict):
            raise ReviewError("request body must be an object")
        return data

    def _static(self, name):
        file_path = (STATIC_DIR / name).resolve()
        if not file_path.is_relative_to(STATIC_DIR) or not file_path.is_file():
            self._json({"error": "not found"}, status=404)
            return
        data = file_path.read_bytes()
        content_type = STATIC_TYPES.get(file_path.suffix, "application/octet-stream")
        self._bytes(data, content_type=content_type)

    def _json(self, payload, status=200):
        data = json.dumps(payload).encode("utf-8")
        self._bytes(data, status=status, content_type="application/json; charset=utf-8")

    def _bytes(self, data, status=200, content_type="application/octet-stream"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def serve(host=HOST, port=PORT):
    try:
        server = ThreadingHTTPServer((host, port), Handler)
    except OSError as exc:
        raise RepoError("port %s is already in use on %s" % (port, host)) from exc
    _write_server_record(server.server_address[1])
    try:
        server.serve_forever()
    finally:
        _clear_server_record()
        server.server_close()


def serve_in_thread(host=HOST, port=0):
    import threading

    server = ThreadingHTTPServer((host, port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _write_server_record(port):
    import os

    path = server_path()
    path.write_text(json.dumps({"pid": os.getpid(), "port": port, "host": HOST}) + "\n", encoding="utf-8")


def _clear_server_record():
    path = server_path()
    if path.is_file():
        path.unlink()


def _one(query, key):
    values = query.get(key) or []
    return values[0] if values else None


def _required(query, key):
    value = _one(query, key)
    if not value:
        raise RepoError(f"missing {key}")
    return value
