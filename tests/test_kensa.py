import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from kensa.comments import add_comment, empty_state, place_comment, render_open_md
from kensa.diff import (
    align_panes,
    hunk_anchors,
    old_lines_from_hunks,
    parse_name_status_z,
    parse_unified_diff,
    render_document,
)
from kensa.gitrepo import RepoError, safe_path
from kensa.mcp_server import serve_stdio
from kensa.outline import outline, rank_hits
from kensa.pull_request import (
    build_review_body,
    build_review_request,
    split_inline_comments,
)
from kensa.server import serve_in_thread
from kensa.setup_agents import install

SAMPLE_DIFF = """diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,3 +1,3 @@
 def answer():
-    return 1
+    return 2
     # end
"""

DELETE_ONLY = """diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -2,1 +1,0 @@
-    return 1
"""


class DiffTests(unittest.TestCase):
    def test_name_status_rename(self):
        rows = parse_name_status_z("M\0src/app.py\0R100\0old.py\0new.py\0")
        self.assertEqual(rows, [("M", "src/app.py", None), ("R", "new.py", "old.py")])

    def test_parse_and_render_change(self):
        parsed = parse_unified_diff(SAMPLE_DIFF)
        self.assertEqual(parsed[0]["new_path"], "src/app.py")
        lines = ["def answer():", "    return 2", "    # end"]
        rows, deletions = render_document(lines, parsed[0]["hunks"])
        self.assertEqual([row["kind"] for row in rows], ["context", "add", "context"])
        self.assertEqual(deletions, [{"before": 2, "text": "    return 1"}])
        self.assertEqual(hunk_anchors(parsed[0]["hunks"])[0]["line"], 1)

    def test_deletion_at_end_of_short_file(self):
        parsed = parse_unified_diff(DELETE_ONLY)
        rows, deletions = render_document(["def answer():"], parsed[0]["hunks"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(deletions[0]["text"], "    return 1")
        self.assertGreaterEqual(deletions[0]["before"], 1)

    def test_align_panes_lines_up_a_replacement(self):
        pairs = align_panes(
            ["def answer():", "    return 1", "    # end"],
            ["def answer():", "    return 2", "    # end"],
        )
        changed = [pair for pair in pairs if pair["kind"] == "change"]
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0]["oldText"], "    return 1")
        self.assertEqual(changed[0]["newText"], "    return 2")
        self.assertEqual(changed[0]["oldNum"], 2)
        self.assertEqual(changed[0]["newNum"], 2)
        self.assertEqual(pairs[0]["kind"], "context")

    def test_align_panes_pads_the_shorter_side(self):
        pairs = align_panes(["keep", "gone"], ["keep", "added", "extra"])
        self.assertEqual(pairs[1]["kind"], "change")
        self.assertEqual(pairs[1]["oldText"], "gone")
        self.assertEqual(pairs[1]["newText"], "added")
        self.assertEqual(pairs[2]["kind"], "add")
        self.assertIsNone(pairs[2]["oldText"])
        self.assertEqual(pairs[2]["newText"], "extra")

    def test_old_lines_follow_the_hunk(self):
        parsed = parse_unified_diff(SAMPLE_DIFF)
        new_lines = ["def answer():", "    return 2", "    # end"]
        self.assertEqual(
            old_lines_from_hunks(new_lines, parsed[0]["hunks"]),
            ["def answer():", "    return 1", "    # end"],
        )


class CommentTests(unittest.TestCase):
    def test_anchor_follows_the_line_text(self):
        state = empty_state()
        add_comment(state, "src/app.py", 2, "bug", "restore the check", "    return 1")
        lines = ["def answer():", "    # note", "    return 1"]
        line, orphaned = place_comment(lines, state["comments"][0])
        self.assertEqual(line, 3)
        self.assertFalse(orphaned)

    def test_open_markdown_includes_hold(self):
        state = empty_state()
        state["hold"] = True
        add_comment(state, "src/app.py", 2, "nit", "name this", "x = 1")
        text = render_open_md(
            state,
            [{"path": "src/app.py", "line": 2, "severity": "nit", "body": "name this", "orphaned": False}],
        )
        self.assertIn("Hold: yes", text)
        self.assertIn("`src/app.py:2` nit — name this", text)
        self.assertIn("Do not commit this file.", text)


class OutlineTests(unittest.TestCase):
    def test_declarations_and_rank(self):
        found = outline("def answer():\n    return 1\nclass Box:\n    pass\n")
        self.assertEqual([item["name"] for item in found], ["answer", "Box"])
        hits = rank_hits(
            "answer",
            [
                {"path": "b.py", "line": 3, "text": "answer = 1"},
                {"path": "a.py", "line": 1, "text": "def answer():"},
            ],
        )
        self.assertEqual(hits[0]["path"], "a.py")


class PathTests(unittest.TestCase):
    def test_rejects_parent_segments(self):
        root = Path("/tmp/kensa-repo")
        with self.assertRaises(RepoError):
            safe_path(root, "../secrets")
        with self.assertRaises(RepoError):
            safe_path(root, "/etc/passwd")


class PullRequestPayloadTests(unittest.TestCase):
    def test_inline_comments_stay_on_diff_lines(self):
        files = parse_unified_diff(SAMPLE_DIFF)
        comments = [
            {"path": "src/app.py", "line": 2, "severity": "bug", "body": "wrong", "orphaned": False},
            {"path": "src/app.py", "line": 9, "severity": "nit", "body": "elsewhere", "orphaned": False},
        ]
        inline, overflow = split_inline_comments(files, comments)
        self.assertEqual(len(inline), 1)
        self.assertEqual(overflow[0]["line"], 9)
        body = build_review_body("Looks wrong.", overflow)
        payload = build_review_request("abc", "REQUEST_CHANGES", body, inline)
        self.assertEqual(payload["event"], "REQUEST_CHANGES")
        self.assertEqual(payload["comments"][0]["side"], "RIGHT")
        self.assertEqual(payload["comments"][0]["line"], 2)
        self.assertIn("elsewhere", payload["body"])


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = tempfile.TemporaryDirectory()
        os.environ["KENSA_HOME"] = self.home.name
        self.root = Path(self.tmp.name)
        quiet = {"cwd": self.root, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        subprocess.check_call(["git", "init", "-q", "-b", "main"], **quiet)
        subprocess.check_call(["git", "config", "user.email", "kensa@example.com"], **quiet)
        subprocess.check_call(["git", "config", "user.name", "Kensa Test"], **quiet)
        source = self.root / "src"
        source.mkdir()
        self.file = source / "app.py"
        self.file.write_text("def answer():\n    return 1\n")
        subprocess.check_call(["git", "add", "src/app.py"], **quiet)
        subprocess.check_call(["git", "commit", "-q", "-m", "init"], **quiet)
        self.file.write_text("def answer():\n    return 2\n")
        self.server = serve_in_thread(port=0)
        self.base = "http://127.0.0.1:%s" % self.server.server_address[1]
        self.repo = quote(str(self.root))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()
        self.home.cleanup()

    def get(self, path):
        with urlopen(self.base + path) as response:
            return json.loads(response.read().decode("utf-8"))

    def send(self, path, payload, method="POST"):
        request = Request(
            self.base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method=method,
        )
        with urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_review_edit_comment_and_send(self):
        page = urlopen(self.base + "/").read().decode("utf-8")
        self.assertIn("Kensa", page)
        snap = self.get("/api/snapshot?repo=" + self.repo)
        self.assertEqual(snap["changes"][0]["path"], "src/app.py")
        opened = self.get("/api/file?repo=%s&path=src/app.py" % self.repo)
        self.assertIn("return 2", opened["content"])
        self.assertTrue(any(row["kind"] == "add" for row in opened["rows"]))
        self.assertTrue(any(item["text"] == "    return 1" for item in opened["deletions"]))
        changed = [pair for pair in opened["pairs"] if pair["oldText"] == "    return 1"]
        self.assertEqual(changed[0]["newText"], "    return 2")
        self.assertEqual(changed[0]["kind"], "change")
        self.send(
            "/api/comments",
            {"repo": str(self.root), "path": "src/app.py", "line": 2, "severity": "bug", "body": "restore the check"},
        )
        saved = self.send(
            "/api/file?repo=" + self.repo,
            {"repo": str(self.root), "path": "src/app.py", "content": "def answer():\n    return 3\n"},
            method="PUT",
        )
        self.assertIn("return 3", saved["content"])
        sent = self.send("/api/send", {"repo": str(self.root)})
        note = Path(sent["path"]).read_text(encoding="utf-8")
        self.assertIn("restore the check", note)
        self.assertTrue((self.root / ".git" / "info" / "exclude").read_text(encoding="utf-8").endswith(".kensa/\n") or ".kensa/" in (self.root / ".git" / "info" / "exclude").read_text(encoding="utf-8"))
        with self.assertRaises(HTTPError):
            self.get("/api/file?repo=%s&path=../secret" % self.repo)

    def test_branch_review(self):
        quiet = {"cwd": self.root, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        subprocess.check_call(["git", "checkout", "-q", "-b", "feature"], **quiet)
        self.file.write_text("def answer():\n    return 2\n")
        subprocess.check_call(["git", "add", "src/app.py"], **quiet)
        subprocess.check_call(["git", "commit", "-q", "-m", "change"], **quiet)
        subprocess.check_call(["git", "checkout", "-q", "main"], **quiet)
        info = self.get("/api/branch?repo=%s&name=feature" % self.repo)
        self.assertEqual(info["baseLabel"], "main")
        self.assertFalse(info["checkedOut"])
        self.assertEqual(info["files"][0]["path"], "src/app.py")
        opened = self.get("/api/branch/file?repo=%s&name=feature&path=src/app.py" % self.repo)
        self.assertIn("return 2", opened["content"])
        self.assertFalse(opened["editable"])
        self.assertTrue(any(row["kind"] == "add" for row in opened["rows"]))
        changed = [pair for pair in opened["pairs"] if pair["oldText"] == "    return 1"]
        self.assertEqual(changed[0]["newText"], "    return 2")

    def test_quick_open_and_jump(self):
        files = self.get("/api/files?repo=%s&q=app.py" % self.repo)
        self.assertEqual(files["files"], ["src/app.py"])
        outline_body = self.get("/api/outline?repo=%s&path=src/app.py" % self.repo)
        self.assertEqual(outline_body["outline"][0]["name"], "answer")
        hits = self.get("/api/jump?repo=%s&symbol=answer" % self.repo)
        self.assertEqual(hits["hits"][0]["path"], "src/app.py")


class McpTests(unittest.TestCase):
    def test_initialize_and_tools(self):
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ]
        payload = b"".join(_frame(item) for item in messages)
        output = io.BytesIO()
        serve_stdio(io.BytesIO(payload), output)
        decoded = _frames(output.getvalue())
        self.assertEqual(decoded[0]["result"]["serverInfo"]["name"], "Kensa")
        names = [tool["name"] for tool in decoded[1]["result"]["tools"]]
        self.assertEqual(names, ["review_status", "review_comments", "review_open"])


class SetupTests(unittest.TestCase):
    def test_writes_project_mcp_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            home = Path(tmp) / "home"
            repo.mkdir()
            (home / ".grok").mkdir(parents=True)
            (home / ".grok" / "config.toml").write_text("theme = \"dark\"\n", encoding="utf-8")
            notes = install(repo, home)
            self.assertTrue(any(".mcp.json" in note for note in notes))
            config = json.loads((repo / ".mcp.json").read_text(encoding="utf-8"))
            self.assertEqual(config["mcpServers"]["kensa"]["args"][-1], "mcp")
            grok = (home / ".grok" / "config.toml").read_text(encoding="utf-8")
            self.assertIn("[mcp_servers.kensa]", grok)
            self.assertIn("theme = \"dark\"", grok)
            install(repo, home)
            self.assertEqual(grok.count("[mcp_servers.kensa]"), (home / ".grok" / "config.toml").read_text(encoding="utf-8").count("[mcp_servers.kensa]"))


def _frame(message):
    body = json.dumps(message).encode("utf-8")
    return ("Content-Length: %s\r\n\r\n" % len(body)).encode("ascii") + body


def _frames(blob):
    view = io.BytesIO(blob)
    found = []
    while True:
        headers = {}
        while True:
            line = view.readline()
            if line in (b"", b"\r\n", b"\n"):
                break
            key, value = line.decode("ascii").split(":", 1)
            headers[key.lower()] = value.strip()
        if not headers:
            break
        found.append(json.loads(view.read(int(headers["content-length"]))))
    return found


if __name__ == "__main__":
    unittest.main()
