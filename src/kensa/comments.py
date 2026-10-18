"""Review comments, hunk marks, and the markdown file agents read."""

import json
import uuid
from pathlib import Path

from kensa.constants import (
    HUNK_CHANGE,
    HUNK_MARKS,
    HUNK_OK,
    MAX_COMMENT_CHARS,
    SEVERITIES,
)


class ReviewError(ValueError):
    pass


def empty_state():
    return {"hold": False, "comments": [], "hunks": []}


def load_state(path):
    file_path = Path(path)
    if not file_path.is_file():
        return empty_state()
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_state()
    if not isinstance(data, dict):
        return empty_state()
    data.setdefault("hold", False)
    data.setdefault("comments", [])
    data.setdefault("hunks", [])
    return data


def save_state(path, state):
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = file_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    temporary.replace(file_path)


def place_comment(lines, comment):
    """Return (line, orphaned). Line numbers are 1-based."""
    anchor = comment.get("anchor", "")
    current = int(comment.get("line") or 0)
    if 1 <= current <= len(lines) and lines[current - 1] == anchor:
        return current, False
    for index, line in enumerate(lines):
        if line == anchor:
            return index + 1, False
    return current if current > 0 else 1, True


def add_comment(state, path, line, severity, body, anchor):
    if severity not in SEVERITIES:
        raise ReviewError("severity must be bug, suggestion, or nit")
    text = (body or "").strip()
    if not text:
        raise ReviewError("comment is empty")
    if len(text) > MAX_COMMENT_CHARS:
        raise ReviewError("comment is too long")
    if not path or line < 1:
        raise ReviewError("comment needs a file and a line")
    comment = {
        "id": uuid.uuid4().hex,
        "path": path,
        "line": line,
        "severity": severity,
        "body": text,
        "anchor": anchor,
    }
    state["comments"].append(comment)
    return comment


def delete_comment(state, comment_id):
    before = len(state["comments"])
    state["comments"] = [
        comment for comment in state["comments"] if comment["id"] != comment_id
    ]
    if len(state["comments"]) == before:
        raise ReviewError("comment was not found")


def set_hunk(state, path, header, mark):
    if mark not in HUNK_MARKS:
        raise ReviewError("hunk mark must be ok or change")
    if not path or not header:
        raise ReviewError("hunk mark needs a file and a hunk")
    state["hunks"] = [
        hunk
        for hunk in state["hunks"]
        if not (hunk["path"] == path and hunk["header"] == header)
    ]
    state["hunks"].append({"path": path, "header": header, "mark": mark})


def render_open_md(state, placed):
    """Markdown any coding agent can read. placed comments include orphaned."""
    hold = "yes" if state.get("hold") else "no"
    lines = [
        "# Kensa review",
        "",
        "These notes are for the coding agent working in this repository.",
        "Address each open comment. Do not commit this file.",
        "",
        f"Hold: {hold}",
    ]
    if state.get("hold"):
        lines.append("Do not continue with new edits until Hold is no.")
    lines.extend(["", "## Open", ""])
    open_rows = [row for row in placed if row["severity"]]
    if not open_rows:
        lines.append("- None.")
    for row in open_rows:
        where = f"`{row['path']}:{row['line']}`"
        if row.get("orphaned"):
            where = f"`{row['path']}` (line moved, was {row['line']})"
        lines.append(f"- {where} {row['severity']} — {row['body']}")
    lines.extend(["", "## Hunks", ""])
    if not state.get("hunks"):
        lines.append("- None.")
    for hunk in state["hunks"]:
        label = "accepted" if hunk["mark"] == HUNK_OK else "change this"
        lines.append(f"- `{hunk['path']}` {label} — {hunk['header']}")
    lines.append("")
    return "\n".join(lines)
