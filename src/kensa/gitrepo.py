"""Read and write a git working tree. Kensa does not care who saved the file."""

import hashlib
import subprocess
from pathlib import Path

from kensa.constants import (
    BASE_BRANCH_LIMIT,
    BASE_SOURCE_EXPLICIT,
    BASE_SOURCE_INFERRED,
    BASE_SOURCE_SAVED,
    BASE_SOURCE_UPSTREAM,
    COMMIT_SUBJECT_LIMIT,
    COMMIT_TOKEN_MAX,
    COMMIT_TOKEN_MIN,
    EXCLUDE_LINE,
    EXCLUDED_MARK,
    GIT_EMPTY_TREE,
    MAX_FILE_BYTES,
    MERGE_BASE_ABBREV,
    MERGE_BASE_MARK,
    RANGE_SEP,
    RANGE_VS,
    REPO_NOTES_DIR,
    SCOPE_ALL,
    SUBJECT_HEAD,
    TRUNK_BRANCHES,
    WORD_COMMIT,
    WORD_COMMITS,
    WORD_FILE,
    WORD_FILES,
    WORD_MERGE,
    WORD_MERGES,
)
from kensa.diff import parse_name_status_z, parse_unified_diff
from kensa.paths import base_branch_name


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


def changed_files(root, commit=None, scope=None):
    """Working tree compared with the inferred base, including commits and uncommitted edits.

    Merge commits are left out. A clean tree with one non-merge commit reviews that commit.
    """
    span = worktree_span(root, commit=commit, scope=scope)
    return [_with_binary(root, item) for item in span["files"]]


def file_blob(root, relative, status):
    """Return (text, binary). Deleted files are read from the comparison branch."""
    if status == "D":
        if not has_head(root):
            return "", False
        return show_ref_text(root, comparison_ref(root), relative)
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


def diff_hunks(root, relative, status, left=None, right=None):
    if right is None and status == "A" and not _tracked(root, relative):
        return []
    if right is None and not has_head(root):
        return []
    if right is None:
        ref = left if left is not None else comparison_ref(root)
        args = ["diff", "-M", "-U3", ref, "--", relative]
    else:
        args = ["diff", "-M", "-U3", left, right, "--", relative]
    proc = _git(root, args, check=False)
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


def valid_base_branch(name):
    text = str(name).strip()
    if len(text) > BASE_BRANCH_LIMIT or not _valid_branch_name(text):
        raise RepoError("branch name is not valid")
    return text


def default_base(root):
    """The configured comparison branch, resolved in this repository."""
    return resolve_branch(root, base_branch_name())


def base_label(ref):
    if ref.startswith("origin/"):
        return ref[len("origin/") :]
    return ref


def comparison_ref(root):
    """Merge-base of HEAD and the inferred base, so commits and edits both show."""
    if not has_head(root):
        return default_base(root)
    base, _source = choose_base(root, "HEAD", current_branch_name(root))
    return _merge_base(root, base, "HEAD") or base


def worktree_span(root, commit=None, scope=None):
    """Review range for the working tree, including how the base was chosen."""
    if not has_head(root):
        base = default_base(root)
        return _finish_span(
            subject=SUBJECT_HEAD,
            base=base,
            source=BASE_SOURCE_SAVED,
            merge_base="",
            commits=[],
            files=_untracked_files(root),
            commit_info=None,
            dirty=False,
            pair_ref=base,
            diff_left=base,
            diff_right="",
            edit_tip=False,
        )
    branch = current_branch_name(root)
    base, source = choose_base(root, "HEAD", branch)
    return _build_span(
        root,
        "HEAD",
        base,
        source,
        branch or SUBJECT_HEAD,
        commit,
        scope,
        worktree=True,
    )


def branch_overview(root, name, base_name=None, commit=None, scope=None):
    """Files changed on a branch since it diverged from its base.

    base_name is a one-off comparison branch. Omit it to infer the base for this branch.
    """
    resolved = resolve_branch(root, name)
    if isinstance(base_name, str):
        base_name = base_name.strip()
    if base_name:
        base = resolve_branch(root, valid_base_branch(base_name))
        source = BASE_SOURCE_EXPLICIT
    else:
        base, source = choose_base(root, resolved, name)
    span = _build_span(root, resolved, base, source, name, commit, scope, worktree=False)
    tip = _git(root, ["rev-parse", resolved]).stdout.strip()
    span["name"] = name
    span["resolved"] = resolved
    span["checkedOut"] = head_sha(root) == tip
    return span


def choose_base(root, tip_ref, branch_name):
    """Upstream when it names another branch, else the trunk with the nearest merge-base."""
    upstream = upstream_ref(root, branch_name)
    if upstream:
        return upstream, BASE_SOURCE_UPSTREAM
    picked = nearest_base(root, tip_ref, candidate_bases(root))
    if picked is None:
        return default_base(root), BASE_SOURCE_SAVED
    source = BASE_SOURCE_SAVED if base_label(picked) == base_branch_name() else BASE_SOURCE_INFERRED
    return picked, source


def branch_hunks(root, base, resolved, relative, left=None, right=None):
    if right:
        args = ["diff", "-M", "-U3", left, right, "--", relative]
    else:
        args = ["diff", "-M", "-U3", f"{base}...{resolved}", "--", relative]
    proc = _git(root, args, check=False)
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


def upstream_ref(root, branch):
    """Tracking branch when it points at a different line of work."""
    if not branch or not _valid_branch_name(branch):
        return None
    proc = _git(root, ["rev-parse", "--abbrev-ref", branch + "@{upstream}"], check=False)
    if proc.returncode != 0:
        return None
    upstream = proc.stdout.strip()
    if not upstream or upstream == SUBJECT_HEAD or _tracks_itself(upstream, branch):
        return None
    check = _git(root, ["rev-parse", "--verify", "--quiet", upstream], check=False)
    if check.returncode != 0 or not check.stdout.strip():
        return None
    return upstream


def candidate_bases(root):
    """Saved comparison branch, then the trunks that exist in this repository."""
    names = []
    for name in (base_branch_name(), *TRUNK_BRANCHES):
        if name not in names:
            names.append(name)
    found = []
    seen = set()
    for name in names:
        try:
            ref = resolve_branch(root, name)
        except RepoError:
            continue
        proc = _git(root, ["rev-parse", "--verify", "--quiet", ref], check=False)
        if proc.returncode != 0 or not proc.stdout.strip():
            continue
        sha = proc.stdout.strip()
        if sha in seen:
            continue
        seen.add(sha)
        found.append(ref)
    return found


def nearest_base(root, tip_ref, candidates):
    """Candidate whose merge-base sits closest to tip. Ties keep the saved branch."""
    saved = base_branch_name()
    best = None
    best_key = None
    for index, ref in enumerate(candidates):
        merge_base = _merge_base(root, ref, tip_ref)
        if not merge_base:
            continue
        distance = _distance(root, merge_base, tip_ref)
        if distance is None:
            continue
        saved_rank = 0 if base_label(ref) == saved else 1
        key = (distance, saved_rank, index)
        if best_key is None or key < best_key:
            best = ref
            best_key = key
    return best


def current_branch_name(root):
    if not has_head(root):
        return None
    proc = _git(root, ["rev-parse", "--abbrev-ref", "HEAD"], check=False)
    name = proc.stdout.strip()
    if proc.returncode != 0 or not name or name == SUBJECT_HEAD:
        return None
    return name


def range_title(subject, base_label_text, merge_short, commit_count, file_count, commit_short="", commit_subject="", excluded=0):
    """Header line: subject vs base (merge-base sha) · commits · files."""
    merge = f" ({MERGE_BASE_MARK} {merge_short})" if merge_short else ""
    if commit_short:
        middle = commit_short
        clipped = _clip(commit_subject, COMMIT_SUBJECT_LIMIT)
        if clipped:
            middle = f"{commit_short} {clipped}"
    else:
        middle = _counted(commit_count, WORD_COMMIT, WORD_COMMITS)
    files = _counted(file_count, WORD_FILE, WORD_FILES)
    title = f"{subject}{RANGE_VS}{base_label_text}{merge}{RANGE_SEP}{middle}{RANGE_SEP}{files}"
    if excluded:
        title += f"{RANGE_SEP}{_counted(excluded, WORD_MERGE, WORD_MERGES)} {EXCLUDED_MARK}"
    return title


def _build_span(root, tip_ref, base, source, subject, commit, scope, worktree):
    commit, scope = _normalize_scope(commit, scope)
    merge_base = _merge_base(root, base, tip_ref) or ""
    commits = _commits_since(root, merge_base, tip_ref) if merge_base else []
    plain = [item for item in commits if not item["merge"]]
    tip_sha = ""
    if has_head(root):
        proc = _git(root, ["rev-parse", "--verify", "--quiet", tip_ref], check=False)
        if proc.returncode == 0:
            tip_sha = proc.stdout.strip()
    on_tip = bool(tip_sha) and tip_sha == (head_sha(root) or "")
    dirty = _worktree_dirty(root) if worktree or on_tip else False
    selected = _selected_commit(plain, commit, scope, dirty)
    if selected:
        parent = _commit_parent(root, selected["sha"])
        files = _commit_files(root, selected["sha"], parent)
        pair_ref = parent
        diff_left = parent
        diff_right = selected["sha"]
    elif worktree:
        files = _worktree_review_files(root, merge_base, base)
        pair_ref = merge_base or base
        diff_left = pair_ref
        diff_right = ""
    else:
        files = _branch_review_files(root, base, tip_ref, merge_base)
        pair_ref = base
        diff_left = base
        diff_right = ""
    head = head_sha(root) or ""
    edit_tip = bool(selected) and selected["sha"] == head
    return _finish_span(
        subject=subject,
        base=base,
        source=source,
        merge_base=merge_base,
        commits=commits,
        files=files,
        commit_info=selected,
        dirty=dirty,
        pair_ref=pair_ref,
        diff_left=diff_left,
        diff_right=diff_right,
        edit_tip=edit_tip,
    )


def _finish_span(subject, base, source, merge_base, commits, files, commit_info, dirty, pair_ref, diff_left, diff_right, edit_tip):
    plain = [item for item in commits if not item["merge"]]
    merges = [item for item in commits if item["merge"]]
    public = [{"sha": item["sha"], "short": item["short"], "subject": item["subject"]} for item in plain]
    merge_short = merge_base[:MERGE_BASE_ABBREV] if merge_base else ""
    commit_short = commit_info["short"] if commit_info else ""
    commit_subject = commit_info["subject"] if commit_info else ""
    excluded = len(merges)
    return {
        "subject": subject,
        "base": base,
        "baseLabel": base_label(base),
        "baseSource": source,
        "mergeBase": merge_base,
        "mergeBaseShort": merge_short,
        "commits": public,
        "commitCount": len(plain),
        "excludedMerges": excluded,
        "commit": commit_short,
        "commitSha": commit_info["sha"] if commit_info else "",
        "commitSubject": commit_subject,
        "files": files,
        "fileCount": len(files),
        "title": range_title(
            subject,
            base_label(base),
            merge_short,
            len(plain),
            len(files),
            commit_short,
            commit_subject,
            excluded,
        ),
        "dirty": dirty,
        "pairRef": pair_ref,
        "diffLeft": diff_left,
        "diffRight": diff_right,
        "editTip": edit_tip,
    }


def _selected_commit(plain, commit, scope, dirty):
    if commit:
        return _match_commit(plain, commit)
    if scope == SCOPE_ALL or dirty or len(plain) != 1:
        return None
    return plain[0]


def _worktree_review_files(root, merge_base, base_ref):
    left = merge_base or base_ref
    proc = _git(root, ["diff", "-M", "--name-status", "-z", left], check=False)
    rows = parse_name_status_z(proc.stdout if proc.returncode == 0 else "")
    if not merge_base:
        files = _files_from_rows(rows)
    else:
        allowed = _paths_of_commits(root, merge_base, "HEAD")
        allowed.update(_dirty_paths(root))
        files = _filter_rows(rows, allowed)
    return _add_untracked(root, files)


def _branch_review_files(root, base_ref, tip_ref, merge_base):
    if not merge_base:
        proc = _git(root, ["diff", "-M", "--name-status", "-z", f"{base_ref}...{tip_ref}"])
        return _files_from_rows(parse_name_status_z(proc.stdout))
    proc = _git(root, ["diff", "-M", "--name-status", "-z", merge_base, tip_ref])
    allowed = _paths_of_commits(root, merge_base, tip_ref)
    return _filter_rows(parse_name_status_z(proc.stdout), allowed)


def _commit_files(root, sha, parent):
    if parent == GIT_EMPTY_TREE:
        proc = _git(
            root,
            ["diff-tree", "-r", "-M", "--no-commit-id", "--name-status", "-z", "--root", sha],
        )
    else:
        proc = _git(root, ["diff", "-M", "--name-status", "-z", parent, sha])
    return _files_from_rows(parse_name_status_z(proc.stdout))


def _paths_of_commits(root, start, tip):
    proc = _git(
        root,
        ["log", "--no-merges", "--name-status", "--pretty=format:", f"{start}..{tip}"],
        check=False,
    )
    paths = set()
    if proc.returncode != 0:
        return paths
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        paths.update(part for part in parts[1:] if part)
    return paths


def _dirty_paths(root):
    paths = set()
    proc = _git(root, ["diff", "-M", "--name-status", "-z", "HEAD"], check=False)
    if proc.returncode == 0:
        for status, path, old_path in parse_name_status_z(proc.stdout):
            paths.add(path)
            if old_path:
                paths.add(old_path)
    for path in _untracked_names(root):
        paths.add(path)
    return paths


def _add_untracked(root, files):
    seen = {item["path"] for item in files}
    for path in _untracked_names(root):
        if path not in seen:
            files.append({"path": path, "status": "A", "oldPath": None})
    files.sort(key=lambda item: item["path"])
    return files


def _untracked_files(root):
    return _add_untracked(root, [])


def _untracked_names(root):
    proc = _git(root, ["ls-files", "--others", "--exclude-standard", "-z"], check=False)
    if proc.returncode != 0:
        return []
    return [part for part in proc.stdout.split("\0") if part]


def _files_from_rows(rows):
    files = []
    seen = set()
    for status, path, old_path in rows:
        if not path or path in seen:
            continue
        seen.add(path)
        files.append({"path": path, "status": status, "oldPath": old_path})
    files.sort(key=lambda item: item["path"])
    return files


def _filter_rows(rows, allowed):
    kept = []
    for status, path, old_path in rows:
        if path in allowed or (old_path and old_path in allowed):
            kept.append((status, path, old_path))
    return _files_from_rows(kept)


def _commits_since(root, start, tip):
    proc = _git(
        root,
        ["log", "--reverse", "--format=%H%x1f%s%x1f%P", f"{start}..{tip}"],
        check=False,
    )
    if proc.returncode != 0:
        return []
    commits = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        sha, subject, parents = (line.split("\x1f", 2) + ["", ""])[:3]
        if not sha:
            continue
        commits.append(
            {
                "sha": sha,
                "short": sha[:MERGE_BASE_ABBREV],
                "subject": subject,
                "merge": len(parents.split()) > 1,
            }
        )
    return commits


def _commit_parent(root, sha):
    proc = _git(root, ["rev-parse", "--verify", "--quiet", sha + "^"], check=False)
    if proc.returncode != 0 or not proc.stdout.strip():
        return GIT_EMPTY_TREE
    return proc.stdout.strip()


def _match_commit(commits, token):
    needle = token.lower()
    matches = [item for item in commits if item["sha"].lower().startswith(needle)]
    if len(matches) != 1:
        raise RepoError("commit is not in this review")
    return matches[0]


def _normalize_scope(commit, scope):
    if isinstance(commit, str):
        commit = commit.strip()
    else:
        commit = ""
    if isinstance(scope, str):
        scope = scope.strip()
    else:
        scope = ""
    if scope and scope != SCOPE_ALL:
        raise RepoError("scope is not valid")
    if commit:
        _valid_commit_token(commit)
    return commit or None, scope or None


def _valid_commit_token(token):
    if token.startswith("-") or not COMMIT_TOKEN_MIN <= len(token) <= COMMIT_TOKEN_MAX:
        raise RepoError("commit is not valid")
    if any(char not in "0123456789abcdefABCDEF" for char in token):
        raise RepoError("commit is not valid")
    return token


def _merge_base(root, base, tip):
    proc = _git(root, ["merge-base", base, tip], check=False)
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _distance(root, start, tip):
    proc = _git(root, ["rev-list", "--count", f"{start}..{tip}"], check=False)
    if proc.returncode != 0:
        return None
    text = proc.stdout.strip()
    if not text.isdigit():
        return None
    return int(text)


def _worktree_dirty(root):
    proc = _git(root, ["status", "--porcelain"], check=False)
    return bool(proc.stdout.strip())


def _tracks_itself(upstream, branch):
    return upstream == branch or upstream.endswith("/" + branch)


def _with_binary(root, item):
    copied = dict(item)
    copied["binary"] = _is_binary_change(root, item["path"], item["status"])
    return copied


def _clip(text, limit):
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip()


def _counted(count, singular, plural):
    word = singular if count == 1 else plural
    return f"{count} {word}"


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
