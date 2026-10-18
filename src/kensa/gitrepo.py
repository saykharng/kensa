"""Read and write a git working tree. Kensa does not care who saved the file."""

import hashlib
import subprocess
from pathlib import Path

from kensa.constants import EXCLUDE_LINE, MAX_FILE_BYTES, REPO_NOTES_DIR
from kensa.diff import parse_name_status_z, parse_unified_diff


class RepoError(ValueError):
    pass


def discover(start):
    start = Path(start).resolve()
    proc = _git(start, ["rev-parse", "--show-toplevel"], check=False)
    if proc.returncode != 0:
        raise RepoError(f"{start} is not inside a git repository")
    return Path(proc.stdout.strip())


def ensure_notes_ignored(root):
    """Keep `.kensa/` out of commits without editing the project's gitignore."""
    exclude = root / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text(encoding="utf-8") if exclude.is_file() else ""
    if EXCLUDE_LINE in existing.splitlines():
        return
    suffix = "" if existing.endswith("\n") or existing == "" else "\n"
    exclude.write_text(existing + suffix + EXCLUDE_LINE + "\n", encoding="utf-8")


def safe_path(root, relative):
    if not relative or relative.startswith("/") or "\\" in relative or "\n" in relative or "\0" in relative:
        raise RepoError("path is outside the repository")
    parts = Path(relative).parts
    if ".." in parts or Path(relative).is_absolute():
        raise RepoError("path is outside the repository")
    root_resolved = Path(root).resolve()
    full = (root_resolved / relative).resolve()
    if not full.is_relative_to(root_resolved):
        raise RepoError("path is outside the repository")
    return full


def has_head(root):
    proc = _git(root, ["rev-parse", "--verify", "--quiet", "HEAD"], check=False)
    return proc.returncode == 0


def head_sha(root):
    if not has_head(root):
        return None
    proc = _git(root, ["rev-parse", "HEAD"])
    return proc.stdout.strip()


def changed_files(root):
    """Working tree compared with HEAD, plus untracked files."""
    rows = []
    if has_head(root):
        proc = _git(root, ["diff", "-M", "--name-status", "-z", "HEAD"])
        rows.extend(parse_name_status_z(proc.stdout))
    untracked = _git(
        root,
        ["ls-files", "--others", "--exclude-standard", "-z"],
    )
    for path in [part for part in untracked.stdout.split("\0") if part]:
        rows.append(("A", path, None))
    changes = []
    seen = set()
    for status, path, old_path in rows:
        if path in seen:
            continue
        seen.add(path)
        changes.append(
            {
                "path": path,
                "status": status,
                "oldPath": old_path,
                "binary": _is_binary_change(root, path, status),
            }
        )
    changes.sort(key=lambda item: item["path"])
    return changes


def file_blob(root, relative, status):
    """Return (text, binary). Deleted files are read from HEAD."""
    if status == "D":
        if not has_head(root):
            return "", False
        proc = subprocess.run(
            ["git", "show", f"HEAD:{relative}"],
            cwd=root,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            message = proc.stderr.decode("utf-8", errors="replace").strip()
            raise RepoError(message or "could not read the deleted file")
        return _decode_blob(proc.stdout)
    full = safe_path(root, relative)
    if not full.is_file():
        raise RepoError("file is not in the working tree")
    return _decode_blob(full.read_bytes())


def content_hash(root, relative, status):
    if status == "D":
        text, binary = file_blob(root, relative, status)
        payload = text if not binary else "binary"
    else:
        full = safe_path(root, relative)
        if not full.is_file():
            return ""
        payload = hashlib.sha256(full.read_bytes()).hexdigest()
        return payload
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def diff_hunks(root, relative, status):
    if status == "A" and not _tracked(root, relative):
        return []
    if not has_head(root):
        return []
    proc = _git(root, ["diff", "-M", "-U3", "HEAD", "--", relative], check=False)
    parsed = parse_unified_diff(proc.stdout)
    for item in parsed:
        if item["new_path"] == relative or item["old_path"] == relative:
            return item["hunks"]
    if parsed:
        return parsed[0]["hunks"]
    return []


def write_worktree_file(root, relative, content):
    if not isinstance(content, str):
        raise RepoError("file content must be text")
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_FILE_BYTES:
        raise RepoError("file is too large to save")
    full = safe_path(root, relative)
    if full.is_dir():
        raise RepoError("path is a directory")
    full.parent.mkdir(parents=True, exist_ok=True)
    temporary = full.with_name(full.name + ".kensa-tmp")
    temporary.write_bytes(encoded)
    temporary.replace(full)


def list_paths(root):
    tracked = _git(root, ["ls-files", "-z"])
    others = _git(root, ["ls-files", "--others", "--exclude-standard", "-z"])
    names = []
    seen = set()
    for blob in (tracked.stdout, others.stdout):
        for name in blob.split("\0"):
            if name and name not in seen and not name.startswith(f"{REPO_NOTES_DIR}/"):
                seen.add(name)
                names.append(name)
    names.sort()
    return names


def search_symbol(root, symbol):
    if not symbol or any(char.isspace() for char in symbol):
        raise RepoError("symbol is empty")
    if symbol.startswith("-"):
        raise RepoError("symbol is empty")
    proc = _git(
        root,
        ["grep", "-n", "-I", "-F", "-e", symbol, "--", "."],
        check=False,
    )
    if proc.returncode not in (0, 1):
        raise RepoError(proc.stderr.strip() or "search failed")
    hits = []
    for line in proc.stdout.splitlines():
        path, sep, rest = line.partition(":")
        if sep != ":":
            continue
        number, sep2, text = rest.partition(":")
        if sep2 != ":" or not number.isdigit():
            continue
        if path.startswith(f"{REPO_NOTES_DIR}/"):
            continue
        hits.append({"path": path, "line": int(number), "text": text})
    return hits


def _tracked(root, relative):
    proc = _git(root, ["ls-files", "--", relative], check=False)
    return bool(proc.stdout.strip())


def _is_binary_change(root, relative, status):
    try:
        _, binary = file_blob(root, relative, status)
    except RepoError:
        return False
    return binary


def _decode_blob(data):
    if len(data) > MAX_FILE_BYTES:
        raise RepoError("file is too large to open in Kensa")
    if b"\0" in data[:8192]:
        return "", True
    return data.decode("utf-8", errors="replace"), False


def resolve_branch(root, name):
    """Return a git revision for a local branch or origin/name."""
    if not _valid_branch_name(name):
        raise RepoError("branch name is not valid")
    for candidate in (name, f"origin/{name}"):
        proc = _git(root, ["rev-parse", "--verify", "--quiet", candidate], check=False)
        if proc.returncode == 0 and proc.stdout.strip():
            return candidate
    raise RepoError(f"branch {name} was not found")


def default_base(root):
    """The branch a review is compared with. Prefers origin's default branch."""
    proc = _git(root, ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], check=False)
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip()
    for name in ("main", "master"):
        proc = _git(root, ["rev-parse", "--verify", "--quiet", name], check=False)
        if proc.returncode == 0:
            return name
    raise RepoError("could not find a base branch such as main")


def branch_overview(root, name):
    """Files changed on a branch since it diverged from the base branch."""
    resolved = resolve_branch(root, name)
    base = default_base(root)
    proc = _git(root, ["diff", "-M", "--name-status", "-z", f"{base}...{resolved}"])
    files = []
    seen = set()
    for status, path, old_path in parse_name_status_z(proc.stdout):
        if path in seen:
            continue
        seen.add(path)
        files.append({"path": path, "status": status, "oldPath": old_path})
    files.sort(key=lambda item: item["path"])
    tip = _git(root, ["rev-parse", resolved]).stdout.strip()
    return {
        "name": name,
        "resolved": resolved,
        "base": base,
        "baseLabel": base[len("origin/") :] if base.startswith("origin/") else base,
        "checkedOut": head_sha(root) == tip,
        "files": files,
    }


def branch_hunks(root, base, resolved, relative):
    proc = _git(
        root,
        ["diff", "-M", "-U3", f"{base}...{resolved}", "--", relative],
        check=False,
    )
    parsed = parse_unified_diff(proc.stdout)
    for item in parsed:
        if item["new_path"] == relative or item["old_path"] == relative:
            return item["hunks"]
    if parsed:
        return parsed[0]["hunks"]
    return []


def show_ref_text(root, ref, relative):
    """Return (text, binary) for a file at a git revision."""
    safe_path(root, relative)
    proc = subprocess.run(
        ["git", "show", f"{ref}:{relative}"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RepoError(message or "could not read that file on the branch")
    return _decode_blob(proc.stdout)


def _valid_branch_name(name):
    if not name or name.startswith("-") or name.startswith("/"):
        return False
    if any(part in ("", ".", "..") for part in name.split("/")):
        return False
    forbidden = set(" \n\t~^:?*[\\")
    return not any(char in forbidden for char in name)


def _git(cwd, args, check=True):
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and proc.returncode != 0:
        message = proc.stderr.strip() or proc.stdout.strip() or "git failed"
        raise RepoError(message)
    return proc
