import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from kensa.cli import main as cli_main
from kensa.comments import add_comment, empty_state, place_comment, render_open_md
from kensa.constants import (
    AGENT_CLAUDE,
    AGENT_GROK,
    COMMAND,
    DEFAULT_REVIEW_PROMPT,
    OPEN_REVIEW_TOOL,
    REVIEWER_MARKER,
    REVIEWER_SKILL,
)
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
from kensa.setup_agents import (
    detect_review_agents,
    install,
    install_command,
    install_reviewer,
    read_review_prompt,
    setup_prompt_arg,
)

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


class CommandInstallTests(unittest.TestCase):
    def test_setup_links_kc_and_refuses_a_different_program(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            source = Path(tmp) / "bin" / "kc"
            source.parent.mkdir()
            source.write_text("from kensa.cli import main\n", encoding="utf-8")
            env = dict(os.environ)
            env["KENSA_BIN"] = str(source)
            env["PATH"] = "/usr/bin"
            with patch.dict(os.environ, env, clear=True):
                notes = install_command(home)
            link = home / ".local" / "bin" / "kc"
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.resolve(), source.resolve())
            self.assertTrue((home / ".zshrc").is_file())
            self.assertIn(".local/bin", (home / ".zshrc").read_text(encoding="utf-8"))
            with patch.dict(os.environ, env, clear=True):
                again = install_command(home)
            self.assertEqual((home / ".zshrc").read_text(encoding="utf-8").count(".local/bin"), 1)
            self.assertTrue(any("already" in note for note in again))
            link.unlink()
            link.write_text("#!/bin/sh\necho other\n", encoding="utf-8")
            with patch.dict(os.environ, env, clear=True):
                refused = install_command(home)
            self.assertIn("other", link.read_text(encoding="utf-8"))
            self.assertTrue(any("Another program" in note for note in refused))
            self.assertTrue(any("installed" in note for note in notes))


class CommandTests(unittest.TestCase):
    def test_help_uses_kc(self):
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            code = cli_main(["--help"])
        self.assertEqual(code, 0)
        text = stdout.getvalue()
        self.assertIn(f"{COMMAND} opens Kensa changes", text)
        self.assertIn(f"{COMMAND} <branch>", text)
        self.assertNotIn("kensa <branch>", text)

    def test_pr_asks_for_a_branch(self):
        stderr = io.StringIO()
        with patch("sys.stderr", stderr):
            code = cli_main(["pr"])
        self.assertEqual(code, 1)
        self.assertIn(f"{COMMAND} feature", stderr.getvalue())


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
        self.assertEqual(names, [OPEN_REVIEW_TOOL, "review_status", "review_comments", "review_open"])

    def test_open_review_opens_the_screen(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            quiet = {"cwd": root, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
            subprocess.check_call(["git", "init", "-q", "-b", "main"], **quiet)
            call = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": OPEN_REVIEW_TOOL, "arguments": {"repo": str(root), "branch": "feature"}},
            }
            output = io.BytesIO()
            with patch("kensa.cli._ensure_server"), patch("kensa.cli.webbrowser.open") as opened:
                serve_stdio(io.BytesIO(_frame(call)), output)
            decoded = _frames(output.getvalue())
            url = json.loads(decoded[0]["result"]["content"][0]["text"])["url"]
            self.assertIn("branch=feature", url)
            self.assertEqual(opened.call_args.args[0], url)


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


class ReviewerSetupTests(unittest.TestCase):
    def test_setup_prompt_arg(self):
        self.assertIsNone(setup_prompt_arg([]))
        self.assertEqual(setup_prompt_arg(["--prompt", "look here"]), "look here")
        with self.assertRaises(RepoError):
            setup_prompt_arg(["--prompt"])

    def test_read_review_prompt(self):
        self.assertEqual(read_review_prompt(None, io.StringIO("")), DEFAULT_REVIEW_PROMPT)
        tty = io.StringIO("\n")
        tty.isatty = lambda: True
        custom = io.StringIO("look here\n")
        custom.isatty = lambda: True
        with patch("sys.stdout", io.StringIO()):
            self.assertEqual(read_review_prompt(None, tty), DEFAULT_REVIEW_PROMPT)
            self.assertEqual(read_review_prompt(None, custom), "look here")
        with self.assertRaises(RepoError):
            read_review_prompt("x" * 201, io.StringIO(""))

    def test_installs_grok_and_claude_reviewer(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".claude" / "CLAUDE.md").parent.mkdir(parents=True)
            (home / ".claude" / "CLAUDE.md").write_text("# Mine\n\nKeep this.\n", encoding="utf-8")
            notes = install_reviewer("look here", home, agents=(AGENT_GROK, AGENT_CLAUDE))
            skill = (home / ".grok" / "skills" / REVIEWER_SKILL / "SKILL.md").read_text(encoding="utf-8")
            review = (home / ".grok" / "skills" / "review" / "SKILL.md").read_text(encoding="utf-8")
            rule = (home / ".grok" / "rules" / "kensa.md").read_text(encoding="utf-8")
            claude_skill = (home / ".claude" / "skills" / REVIEWER_SKILL / "SKILL.md").read_text(encoding="utf-8")
            memory = (home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
            self.assertIn("name: kensa", skill)
            self.assertIn("look here", skill)
            self.assertIn(OPEN_REVIEW_TOOL, skill)
            self.assertNotIn("Apply the comments", skill)
            self.assertIn(OPEN_REVIEW_TOOL, rule)
            self.assertIn(REVIEWER_MARKER, skill)
            self.assertIn("name: review", review)
            self.assertIn("look here", rule)
            self.assertEqual(skill, claude_skill)
            self.assertIn("# Mine", memory)
            self.assertIn("Keep this.", memory)
            self.assertEqual(memory.count(REVIEWER_MARKER), 2)
            install_reviewer('say "review"', home, agents=(AGENT_GROK, AGENT_CLAUDE))
            updated = (home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
            self.assertEqual(updated.count(f"<!-- {REVIEWER_MARKER} -->"), 1)
            self.assertIn("# Mine", updated)
            self.assertIn('say "review"', (home / ".grok" / "skills" / "review" / "SKILL.md").read_text(encoding="utf-8"))
            self.assertTrue(any("Phrase: look here" in note for note in notes))

    def test_leaves_a_foreign_review_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            review = home / ".grok" / "skills" / "review" / "SKILL.md"
            review.parent.mkdir(parents=True)
            review.write_text("---\nname: review\n---\nMine.\n", encoding="utf-8")
            notes = install_reviewer("review", home, agents=(AGENT_GROK,))
            self.assertEqual(review.read_text(encoding="utf-8"), "---\nname: review\n---\nMine.\n")
            self.assertTrue(any("left" in note for note in notes))
            self.assertIn("name: kensa", (home / ".grok" / "skills" / REVIEWER_SKILL / "SKILL.md").read_text(encoding="utf-8"))

    def test_detects_installed_agents(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".grok").mkdir()
            with patch("kensa.setup_agents.shutil.which", return_value=None):
                self.assertEqual(detect_review_agents(home), [AGENT_GROK])
                (home / ".claude.json").write_text("{}\n", encoding="utf-8")
                self.assertEqual(detect_review_agents(home), [AGENT_GROK, AGENT_CLAUDE])

    def test_setup_command_passes_the_phrase(self):
        with patch("kensa.cli.install_command", return_value=["linked"]), \
             patch("kensa.cli.install_reviewer", return_value=["reviewer"]) as reviewer, \
             patch("kensa.cli.install", return_value=["mcp"]), \
             patch("kensa.cli.discover", return_value=Path("/tmp/repo")), \
             patch("sys.stdin", io.StringIO("")), \
             patch("sys.stdout", io.StringIO()):
            code = cli_main(["setup", "--prompt", "look here"])
            default_code = cli_main(["setup"])
        self.assertEqual(code, 0)
        self.assertEqual(default_code, 0)
        self.assertEqual(reviewer.call_args_list[0].args[0], "look here")
        self.assertEqual(reviewer.call_args_list[1].args[0], DEFAULT_REVIEW_PROMPT)
        stderr = io.StringIO()
        with patch("sys.stderr", stderr):
            refused = cli_main(["setup", "--nope"])
        self.assertEqual(refused, 1)
        self.assertIn("--prompt", stderr.getvalue())


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
