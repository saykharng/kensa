"""Parse git unified diffs and place them on a full file."""

import difflib
import re

_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def parse_name_status_z(blob):
    """Parse `git diff --name-status -z` output.

    Returns a list of (status, path, old_path). status is one letter.
    Renames and copies put the new path in path and the previous path in old_path.
    """
    parts = blob.split("\0")
    index = 0
    rows = []
    while index < len(parts) and parts[index] != "":
        raw = parts[index]
        index += 1
        if not raw:
            break
        if raw[0] in ("R", "C"):
            if index + 1 >= len(parts):
                break
            old_path = parts[index]
            new_path = parts[index + 1]
            index += 2
            rows.append((raw[0], new_path, old_path))
            continue
        if index >= len(parts):
            break
        rows.append((raw[0], parts[index], None))
        index += 1
    return rows


def _strip_diff_prefix(value):
    if value == "/dev/null":
        return None
    if value.startswith('"') and value.endswith('"') and len(value) >= 2:
        value = value[1:-1]
    if len(value) >= 2 and value[1] == "/" and value[0] in ("a", "b"):
        return value[2:]
    return value


def parse_unified_diff(text):
    """Parse a unified diff into files, hunks, and lines.

    Each file dict has old_path, new_path, binary, and hunks.
    A hunk line is add, del, or context, with 1-based line numbers.
    """
    files = []
    current = None
    hunk = None
    old_line = 0
    new_line = 0
    for line in text.splitlines():
        if line.startswith("diff --git "):
            current = {
                "old_path": None,
                "new_path": None,
                "binary": False,
                "hunks": [],
            }
            files.append(current)
            hunk = None
            continue
        if current is None:
            continue
        if line.startswith("Binary files "):
            current["binary"] = True
            hunk = None
            continue
        if line.startswith("--- "):
            current["old_path"] = _strip_diff_prefix(line[4:])
            continue
        if line.startswith("+++ "):
            current["new_path"] = _strip_diff_prefix(line[4:])
            continue
        if line.startswith("@@"):
            match = _HUNK_HEADER.match(line)
            if match is None:
                hunk = None
                continue
            old_line = int(match.group(1))
            new_line = int(match.group(2))
            hunk = {
                "header": line,
                "new_start": new_line,
                "lines": [],
            }
            current["hunks"].append(hunk)
            continue
        if hunk is None or not line:
            continue
        prefix = line[0]
        body = line[1:]
        if prefix == "+":
            hunk["lines"].append(
                {"type": "add", "text": body, "new_line": new_line, "old_line": None}
            )
            new_line += 1
        elif prefix == "-":
            hunk["lines"].append(
                {"type": "del", "text": body, "new_line": None, "old_line": old_line}
            )
            old_line += 1
        elif prefix == " ":
            hunk["lines"].append(
                {
                    "type": "context",
                    "text": body,
                    "new_line": new_line,
                    "old_line": old_line,
                }
            )
            old_line += 1
            new_line += 1
        elif prefix == "\\":
            continue
    return files


def render_document(new_lines, hunks):
    """Mark additions and attach deleted lines onto a full new file.

    Returns (rows, deletions). rows are {num, text, kind}. deletions are
    {before, text}, where before is the 1-based new line they precede.
    A before value of len(new_lines)+1 means the deletion is at the end.
    """
    added = set()
    deletions_before = {}
    for hunk in hunks:
        pending = []
        saw_new = False
        for item in hunk["lines"]:
            if item["type"] == "del":
                pending.append(item["text"])
                continue
            saw_new = True
            if pending:
                deletions_before.setdefault(item["new_line"], []).extend(pending)
                pending = []
            if item["type"] == "add":
                added.add(item["new_line"])
        if pending:
            anchor = hunk["new_start"] if not saw_new else None
            if anchor is None:
                last_new = 0
                for item in hunk["lines"]:
                    if item["new_line"]:
                        last_new = item["new_line"]
                anchor = last_new + 1
            if anchor < 1:
                anchor = 1
            deletions_before.setdefault(anchor, []).extend(pending)

    rows = []
    for number, text in enumerate(new_lines, start=1):
        kind = "add" if number in added else "context"
        rows.append({"num": number, "text": text, "kind": kind})
    deletions = []
    for before in sorted(deletions_before):
        for text in deletions_before[before]:
            deletions.append({"before": before, "text": text})
    return rows, deletions


def align_panes(old_lines, new_lines):
    """Line up two full files for a side-by-side view.

    Each pair has oldNum, oldText, newNum, newText, and kind.
    kind is context, add, del, or change. A missing side is None,
    so the shorter side of a replacement stays blank instead of shifting.
    """
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    pairs = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset, text in enumerate(old_lines[i1:i2]):
                pairs.append(_pair(i1 + offset, text, j1 + offset, new_lines[j1 + offset], "context"))
            continue
        if tag == "delete":
            for offset, text in enumerate(old_lines[i1:i2]):
                pairs.append(_pair(i1 + offset, text, None, None, "del"))
            continue
        if tag == "insert":
            for offset, text in enumerate(new_lines[j1:j2]):
                pairs.append(_pair(None, None, j1 + offset, text, "add"))
            continue
        old_slice = old_lines[i1:i2]
        new_slice = new_lines[j1:j2]
        count = max(len(old_slice), len(new_slice))
        for offset in range(count):
            has_old = offset < len(old_slice)
            has_new = offset < len(new_slice)
            if has_old and has_new:
                kind = "change"
            elif has_old:
                kind = "del"
            else:
                kind = "add"
            pairs.append(
                _pair(
                    i1 + offset if has_old else None,
                    old_slice[offset] if has_old else None,
                    j1 + offset if has_new else None,
                    new_slice[offset] if has_new else None,
                    kind,
                )
            )
    return pairs


def _pair(old_index, old_text, new_index, new_text, kind):
    return {
        "oldNum": None if old_index is None else old_index + 1,
        "oldText": old_text,
        "newNum": None if new_index is None else new_index + 1,
        "newText": new_text,
        "kind": kind,
    }


def old_lines_from_hunks(new_lines, hunks):
    """Rebuild the previous file when only the new file and a unified diff exist.

    Lines outside hunks are copied through. A hunk with no new-file lines treats
    new_start as the first new line after the deletion.
    """
    if not hunks:
        return list(new_lines)
    old = []
    cursor = 0
    limit = len(new_lines)
    for hunk in hunks:
        start = hunk.get("new_start") or 1
        if start < 1:
            start = 1
        target = start - 1
        if target < cursor:
            target = cursor
        if target > limit:
            target = limit
        old.extend(new_lines[cursor:target])
        cursor = target
        for item in hunk["lines"]:
            kind = item["type"]
            if kind == "add":
                cursor += 1
            elif kind == "context":
                old.append(item["text"])
                cursor += 1
            elif kind == "del":
                old.append(item["text"])
            if cursor > limit:
                cursor = limit
    if cursor < limit:
        old.extend(new_lines[cursor:])
    return old


def hunk_anchors(hunks):
    """Line in the new file where a changed hunk begins."""
    anchors = []
    for hunk in hunks:
        line = None
        for item in hunk["lines"]:
            if item["new_line"]:
                line = item["new_line"]
                break
        if line is None:
            line = hunk.get("new_start") or 1
        if line < 1:
            line = 1
        anchors.append({"header": hunk["header"], "line": line})
    return anchors


def commentable_new_lines(hunks):
    """New-file line numbers GitHub will accept on the RIGHT side of a review."""
    numbers = set()
    for hunk in hunks:
        for item in hunk["lines"]:
            if item["new_line"]:
                numbers.add(item["new_line"])
    return numbers


def added_line_numbers(hunks):
    numbers = set()
    for hunk in hunks:
        for item in hunk["lines"]:
            if item["type"] == "add" and item["new_line"]:
                numbers.add(item["new_line"])
    return numbers
