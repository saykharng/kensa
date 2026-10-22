"""Local review actions shared by the browser and the MCP server."""

import hashlib
from pathlib import Path

from kensa.comments import (
    ReviewError,
    add_comment,
    delete_comment,
    load_state,
    place_comment,
    render_open_md,
    save_state,
    set_hunk,
)
from kensa.constants import FILE_SEARCH_LIMIT, GREP_READ_LIMIT, JUMP_LIMIT, SCOPE_ALL
from kensa.diff import align_panes, hunk_anchors, old_lines_from_hunks, render_document
from kensa.gitrepo import (
    RepoError,
    branch_hunks,
    branch_overview,
    changed_files,
    content_hash,
    diff_hunks,
    discover,
    ensure_notes_ignored,
    file_blob,
    list_paths,
    safe_path,
    search_symbol,
    show_ref_text,
    worktree_span,
    write_worktree_file,
)
from kensa.outline import outline, rank_hits
from kensa.paths import comments_path, open_md_path


def repository(start):
    return discover(start)


def snapshot(root, commit=None, scope=None):
    root = Path(root)
    state = _state(root)
    span = worktree_span(root, commit=commit, scope=scope)
    changes = []
    for change in span["files"]:
        item = dict(change)
        try:
            item["hash"] = content_hash(root, change["path"], change["status"])
        except RepoError:
            item["hash"] = ""
        item["binary"] = _binary_flag(root, change["path"], change["status"])
        changes.append(item)
    payload = {
        "repo": str(root.resolve()),
        "hold": bool(state.get("hold")),
        "base": span["baseLabel"],
        "changes": changes,
        "comments": _place_all(root, state),
        "hunks": state.get("hunks") or [],
    }
    payload.update(_range_payload(span))
    return payload


def open_file(root, relative, commit=None, scope=None):
    root = Path(root)
    safe_path(root, relative)
    state = _state(root)
    span = worktree_span(root, commit=commit, scope=scope)
    known = next((item for item in span["files"] if item["path"] == relative), None)
    status = known["status"] if known else "context"
    commit_view = bool(span["commitSha"]) and known is not None
    if commit_view and span["editTip"] and status != "D":
        text, binary = file_blob(root, relative, "M")
        editable = not binary
    elif commit_view:
        ref = span["pairRef"] if status == "D" else span["commitSha"]
        text, binary = show_ref_text(root, ref, relative)
        editable = False
    else:
        text, binary = _text(root, relative, status)
        editable = status != "D" and not binary
    lines = [] if binary else text.splitlines()
    if status == "context" or binary:
        hunks = []
    elif commit_view and not span["editTip"]:
        hunks = diff_hunks(root, relative, status, span["diffLeft"], span["diffRight"])
    else:
        hunks = diff_hunks(root, relative, status, span["pairRef"])
    if binary:
        rows, deletions = [], []
    elif status == "D":
        rows = [{"num": index, "text": line, "kind": "del"} for index, line in enumerate(lines, start=1)]
        deletions = []
        editable = False
    elif status == "A" and not hunks:
        rows = [{"num": index, "text": line, "kind": "add"} for index, line in enumerate(lines, start=1)]
        deletions = []
    else:
        rows, deletions = render_document(lines, hunks)
    placed = [row for row in _place_all(root, state) if row["path"] == relative]
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest() if not binary else ""
    old_path = known.get("oldPath") if known else None
    return {
        "path": relative,
        "status": status,
        "inReview": known is not None,
        "binary": binary,
        "editable": editable,
        "content": "" if binary else text,
        "hash": digest,
        "rows": rows,
        "deletions": deletions,
        "pairs": _pairs(root, relative, status, text, binary, old_path, span["pairRef"]),
        "anchors": hunk_anchors(hunks),
        "comments": placed,
    }


def save_file(root, relative, content):
    root = Path(root)
    current = open_file(root, relative)
    if current["binary"] or not current["editable"]:
        raise ReviewError("this file cannot be edited in Kensa")
    write_worktree_file(root, relative, content)
    return open_file(root, relative)


def create_comment(root, relative, line, severity, body):
    root = Path(root)
    opened = open_file(root, relative)
    if opened["binary"]:
        raise ReviewError("cannot comment on a binary file")
    rows = {row["num"]: row["text"] for row in opened["rows"]}
    if line not in rows:
        raise ReviewError("that line is not in the file")
    state = _state(root)
    comment = add_comment(state, relative, line, severity, body, rows[line])
    _store(root, state)
    return comment


def remove_comment(root, comment_id):
    state = _state(root)
    delete_comment(state, comment_id)
    _store(root, state)


def mark_hunk(root, relative, header, mark):
    safe_path(Path(root), relative)
    state = _state(root)
    set_hunk(state, relative, header, mark)
    _store(root, state)


def set_hold(root, hold):
    state = _state(root)
    state["hold"] = bool(hold)
    _store(root, state)
    _write_open_md(root, state)
    return {"hold": state["hold"]}


def send(root):
    state = _state(root)
    path = _write_open_md(root, state)
    return {"path": str(path), "hold": bool(state.get("hold"))}


def search_files(root, query):
    names = list_paths(Path(root))
    needle = (query or "").strip().lower()
    if needle:
        ranked = []
        for name in names:
            lowered = name.lower()
            if needle not in lowered:
                continue
            base = Path(name).name.lower()
            score = 0 if base.startswith(needle) else 1
            ranked.append((score, name))
        ranked.sort()
        names = [name for _, name in ranked]
    return names[:FILE_SEARCH_LIMIT]


def file_outline(root, relative):
    opened = open_file(root, relative)
    if opened["binary"]:
        return []
    return outline(opened["content"])


def jump(root, symbol):
    hits = search_symbol(Path(root), symbol)[:GREP_READ_LIMIT]
    return rank_hits(symbol, hits)[:JUMP_LIMIT]


def open_branch(root, name, base_name=None, commit=None, scope=None):
    """Diff of a branch against its inferred base, or a one-off base."""
    from kensa.pull_request import find_pull_request

    overview = branch_overview(Path(root), name, base_name, commit=commit, scope=scope)
    overview["pullRequest"] = find_pull_request(Path(root), overview["resolved"])
    return overview


def open_branch_file(root, name, relative, base_name=None, commit=None, scope=None):
    """Whole file at the branch tip, or at one commit, with that diff highlighted."""
    root = Path(root)
    safe_path(root, relative)
    overview = branch_overview(root, name, base_name, commit=commit, scope=scope)
    known = next((item for item in overview["files"] if item["path"] == relative), None)
    if known is None:
        raise RepoError("that file did not change on this branch")
    status = known["status"]
    commit_view = bool(overview["commitSha"])
    checked_out = overview["checkedOut"] and status != "D" and (not commit_view or overview["editTip"])
    if checked_out:
        text, binary = file_blob(root, relative, "M")
        source = "worktree"
    elif commit_view:
        ref = overview["pairRef"] if status == "D" else overview["commitSha"]
        text, binary = show_ref_text(root, ref, relative)
        source = "commit"
    else:
        ref = overview["base"] if status == "D" else overview["resolved"]
        text, binary = show_ref_text(root, ref, relative)
        source = "branch"
    if binary:
        hunks = []
    elif commit_view and not overview["editTip"]:
        hunks = branch_hunks(
            root,
            overview["base"],
            overview["resolved"],
            relative,
            overview["diffLeft"],
            overview["diffRight"],
        )
    elif commit_view:
        hunks = diff_hunks(root, relative, status, overview["diffLeft"])
    else:
        hunks = branch_hunks(root, overview["base"], overview["resolved"], relative)
    editable = checked_out and not binary
    document = _document(text, binary, hunks, status)
    state = _state(root)
    placed = [row for row in _place_all(root, state) if row["path"] == relative]
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest() if not binary else ""
    return {
        "path": relative,
        "status": status,
        "inReview": True,
        "binary": binary,
        "editable": editable,
        "content": "" if binary else text,
        "hash": digest,
        "rows": document["rows"],
        "deletions": document["deletions"],
        "pairs": _pairs(
            root,
            relative,
            status,
            text,
            binary,
            known.get("oldPath"),
            overview["pairRef"] if commit_view else overview["base"],
        ),
        "anchors": hunk_anchors(hunks),
        "comments": placed,
        "source": source,
        "branch": {
            "name": overview["name"],
            "base": overview["baseLabel"],
            "checkedOut": overview["checkedOut"],
        },
    }


def open_pull_file(root, number, relative):
    """Same shape as open_file, using the pull request diff for highlights."""
    from kensa.pull_request import pull_request_file

    root = Path(root)
    loaded = pull_request_file(root, number, relative)
    state = _state(root)
    binary = loaded["binary"]
    lines = [] if binary else loaded["content"].splitlines()
    if binary:
        rows, deletions = [], []
    elif loaded["hunks"]:
        rows, deletions = render_document(lines, loaded["hunks"])
    else:
        rows = [
            {"num": index, "text": line, "kind": "context"}
            for index, line in enumerate(lines, start=1)
        ]
        deletions = []
    placed = [row for row in _place_all(root, state) if row["path"] == relative]
    digest = hashlib.sha256(loaded["content"].encode("utf-8")).hexdigest() if not binary else ""
    pairs = _pull_pairs(lines, binary, loaded)
    return {
        "path": relative,
        "status": "M",
        "inReview": True,
        "binary": binary,
        "editable": loaded["editable"],
        "content": loaded["content"],
        "hash": digest,
        "rows": rows,
        "deletions": deletions,
        "pairs": pairs,
        "anchors": hunk_anchors(loaded["hunks"]),
        "comments": placed,
        "pullRequest": loaded["pullRequest"],
        "source": loaded["source"],
    }


def agent_view(root):
    """What an agent should read: live comments, plus the last file that was sent."""
    root = Path(root)
    state = _state(root)
    written = ""
    path = open_md_path(root)
    if path.is_file():
        written = path.read_text(encoding="utf-8")
    live = render_open_md(state, _place_all(root, state))
    return {
        "repo": str(root.resolve()),
        "hold": bool(state.get("hold")),
        "comments": _place_all(root, state),
        "hunks": state.get("hunks") or [],
        "pendingSend": live != written,
        "openMarkdown": written,
        "liveMarkdown": live,
    }


def _pairs(root, relative, status, text, binary, old_path, ref):
    """Aligned old and new lines. Context shows the same text on both sides."""
    if binary:
        return []
    if status == "D":
        return align_panes(text.splitlines(), [])
    if status == "A":
        return align_panes([], text.splitlines())
    if status == "context":
        lines = text.splitlines()
        return align_panes(lines, lines)
    previous = _previous_blob(root, ref, old_path or relative)
    return align_panes(previous.splitlines(), text.splitlines())


def _previous_blob(root, ref, relative):
    try:
        text, binary = show_ref_text(root, ref, relative)
    except RepoError:
        return ""
    if binary:
        return ""
    return text


def _pull_pairs(lines, binary, loaded):
    if binary:
        return []
    if loaded.get("newPath") is None:
        return align_panes(lines, [])
    if not loaded.get("oldPath"):
        return align_panes([], lines)
    previous = old_lines_from_hunks(lines, loaded["hunks"])
    return align_panes(previous, lines)


def _document(text, binary, hunks, status):
    if binary:
        return {"rows": [], "deletions": []}
    lines = text.splitlines()
    if status == "D":
        rows = [
            {"num": index, "text": line, "kind": "del"}
            for index, line in enumerate(lines, start=1)
        ]
        return {"rows": rows, "deletions": []}
    if status == "A" and not hunks:
        rows = [
            {"num": index, "text": line, "kind": "add"}
            for index, line in enumerate(lines, start=1)
        ]
        return {"rows": rows, "deletions": []}
    rows, deletions = render_document(lines, hunks)
    return {"rows": rows, "deletions": deletions}


def review_summary(root, branch=None, base_name=None, commit=None):
    """Resolved range for the agent: base, merge-base, commit count, and file count."""
    root = Path(root)
    if branch:
        info = branch_overview(root, branch, base_name, commit=commit)
    else:
        info = worktree_span(root, commit=commit)
    summary = _range_payload(info)
    summary["base"] = summary["baseLabel"]
    summary["commit"] = summary["commit"] or None
    return summary


def _range_payload(span):
    return {
        "subject": span["subject"],
        "baseLabel": span["baseLabel"],
        "baseRef": span["base"],
        "baseSource": span["baseSource"],
        "mergeBase": span["mergeBase"],
        "mergeBaseShort": span["mergeBaseShort"],
        "commits": span["commits"],
        "commitCount": span["commitCount"],
        "excludedMerges": span["excludedMerges"],
        "commit": span["commit"],
        "commitSubject": span["commitSubject"],
        "fileCount": span["fileCount"],
        "title": span["title"],
    }


def _binary_flag(root, relative, status):
    try:
        _, binary = file_blob(root, relative, status)
    except RepoError:
        return False
    return binary


def _state(root):
    ensure_notes_ignored(root)
    return load_state(comments_path(root))


def _store(root, state):
    save_state(comments_path(root), state)


def _write_open_md(root, state):
    ensure_notes_ignored(root)
    path = open_md_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_open_md(state, _place_all(root, state)), encoding="utf-8")
    return path


def _text(root, relative, status):
    if status == "context":
        return file_blob(root, relative, "M")
    return file_blob(root, relative, status)


def _place_all(root, state):
    cache = {}
    changes = {item["path"]: item for item in changed_files(root, scope=SCOPE_ALL)}
    placed = []
    for comment in state.get("comments") or []:
        path = comment.get("path")
        if path not in cache:
            cache[path] = _lines(root, path, changes)
        line, orphaned = place_comment(cache[path], comment)
        placed.append(
            {
                "id": comment["id"],
                "path": path,
                "line": line,
                "severity": comment.get("severity"),
                "body": comment.get("body"),
                "orphaned": orphaned,
            }
        )
    return placed


def _lines(root, relative, changes):
    try:
        safe_path(root, relative)
    except RepoError:
        return []
    status = changes.get(relative, {}).get("status", "context")
    try:
        text, binary = _text(root, relative, status)
    except RepoError:
        return []
    if binary:
        return []
    return text.splitlines()
