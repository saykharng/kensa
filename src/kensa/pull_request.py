"""Load a GitHub pull request and post one review through gh."""

import json
import subprocess
from urllib.parse import quote

from kensa.constants import DIFF_SIDE, VERDICTS
from kensa.diff import commentable_new_lines, parse_unified_diff
from kensa.gitrepo import RepoError, head_sha


def build_review_body(summary, overflow):
    parts = [summary.strip() or "Review from Kensa."]
    if overflow:
        parts.append("")
        parts.append("Comments on lines outside the diff:")
        for item in overflow:
            parts.append(
                f"- `{item['path']}:{item['line']}` {item['severity']} — {item['body']}"
            )
    return "\n".join(parts)


def build_review_request(head_sha_value, verdict, body, inline_comments):
    if verdict not in VERDICTS:
        raise RepoError("verdict must be COMMENT, REQUEST_CHANGES, or APPROVE")
    payload = {
        "commit_id": head_sha_value,
        "event": verdict,
        "body": body,
    }
    if inline_comments:
        payload["comments"] = [
            {
                "path": item["path"],
                "line": item["line"],
                "side": DIFF_SIDE,
                "body": f"{item['severity']}\n\n{item['body']}",
            }
            for item in inline_comments
        ]
    return payload


def split_inline_comments(diff_files, comments):
    """Keep comments GitHub can attach to the diff. The rest go in the summary."""
    allowed = {}
    for parsed in diff_files:
        path = parsed["new_path"] or parsed["old_path"]
        if path:
            allowed[path] = commentable_new_lines(parsed["hunks"])
    inline = []
    overflow = []
    for comment in comments:
        lines = allowed.get(comment["path"])
        if lines and comment["line"] in lines and not comment.get("orphaned"):
            inline.append(comment)
        else:
            overflow.append(comment)
    return inline, overflow


def find_pull_request(root, branch):
    """Open GitHub pull request for a branch, if gh can see one."""
    short = branch[len("origin/") :] if branch.startswith("origin/") else branch
    try:
        raw = _gh(
            root,
            [
                "pr",
                "list",
                "--head",
                short,
                "--state",
                "open",
                "--json",
                "number,title,url",
                "--limit",
                "1",
            ],
        )
    except RepoError:
        return None
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not rows:
        return None
    row = rows[0]
    return {"number": row.get("number"), "title": row.get("title") or "", "url": row.get("url") or ""}


def load_pull_request(root, number):
    if not str(number).isdigit():
        raise RepoError("pull request number must be digits")
    view = _gh_json(
        root,
        [
            "pr",
            "view",
            str(number),
            "--json",
            "headRefOid,title,url,baseRefName,headRefName",
        ],
    )
    diff_text = _gh(root, ["pr", "diff", str(number)])
    files = []
    for parsed in parse_unified_diff(diff_text):
        path = parsed["new_path"] or parsed["old_path"]
        if not path:
            continue
        files.append(
            {
                "path": path,
                "oldPath": parsed["old_path"],
                "binary": parsed["binary"],
                "anchors": [
                    {"header": hunk["header"], "line": hunk["new_start"]}
                    for hunk in parsed["hunks"]
                ],
            }
        )
    local = head_sha(root)
    return {
        "number": int(number),
        "title": view.get("title") or "",
        "url": view.get("url") or "",
        "head": view.get("headRefOid") or "",
        "base": view.get("baseRefName") or "",
        "branch": view.get("headRefName") or "",
        "checkedOut": bool(local and local == view.get("headRefOid")),
        "files": files,
        "diff": diff_text,
    }


def pull_request_file(root, number, relative):
    """Full file at the pull request head, plus hunks from the pull request diff."""
    loaded = load_pull_request(root, number)
    matched = None
    for parsed in parse_unified_diff(loaded["diff"]):
        path = parsed["new_path"] or parsed["old_path"]
        if path == relative:
            matched = parsed
            break
    if matched is None:
        raise RepoError("that file is not in the pull request diff")
    if loaded["checkedOut"]:
        from kensa.gitrepo import file_blob

        text, binary = file_blob(root, relative, "M" if matched["new_path"] else "D")
        source = "worktree"
    else:
        text, binary = _github_file(root, relative, loaded["head"])
        source = "github"
    return {
        "pullRequest": {key: loaded[key] for key in ("number", "title", "url", "head", "checkedOut")},
        "path": relative,
        "binary": binary or matched["binary"],
        "content": "" if binary or matched["binary"] else text,
        "hunks": matched["hunks"],
        "source": source,
        "editable": loaded["checkedOut"] and not (binary or matched["binary"]) and matched["new_path"] is not None,
    }


def submit_pull_request(root, number, verdict, summary, comments):
    loaded = load_pull_request(root, number)
    diff_files = parse_unified_diff(loaded["diff"])
    inline, overflow = split_inline_comments(diff_files, comments)
    body = build_review_body(summary, overflow)
    payload = build_review_request(loaded["head"], verdict, body, inline)
    name = _name_with_owner(root)
    raw = _gh(
        root,
        [
            "api",
            "--method",
            "POST",
            f"repos/{name}/pulls/{int(number)}/reviews",
            "--input",
            "-",
        ],
        input_text=json.dumps(payload),
    )
    try:
        created = json.loads(raw)
    except json.JSONDecodeError:
        created = {"raw": raw}
    return {
        "url": created.get("html_url") or loaded["url"],
        "inline": len(inline),
        "overflow": len(overflow),
    }


def _name_with_owner(root):
    view = _gh_json(root, ["repo", "view", "--json", "nameWithOwner"])
    name = view.get("nameWithOwner")
    if not name or "/" not in name:
        raise RepoError("could not tell which GitHub repository this is")
    return name


def _github_file(root, relative, sha):
    name = _name_with_owner(root)
    quoted = quote(relative)
    raw = _gh_bytes(
        root,
        [
            "api",
            f"repos/{name}/contents/{quoted}?ref={sha}",
            "-H",
            "Accept: application/vnd.github.raw",
        ],
    )
    if b"\0" in raw[:8192]:
        return "", True
    return raw.decode("utf-8", errors="replace"), False


def _gh_json(root, args):
    raw = _gh(root, args)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RepoError("gh returned something that is not JSON") from exc


def _gh(root, args, input_text=None):
    proc = _run(root, args, input_text)
    return proc.stdout


def _gh_bytes(root, args):
    proc = _run(root, args, None, text=False)
    return proc.stdout


def _run(root, args, input_text, text=True):
    try:
        proc = subprocess.run(
            ["gh", *args],
            cwd=root,
            input=input_text,
            capture_output=True,
            text=text,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RepoError("gh is not installed") from exc
    if proc.returncode != 0:
        err = proc.stderr if text else proc.stderr.decode("utf-8", errors="replace")
        message = err.strip() or "gh failed"
        if "auth" in message.lower() or "not logged" in message.lower():
            message = "gh is not logged in. Run gh auth login, then try again."
        raise RepoError(message)
    return proc
