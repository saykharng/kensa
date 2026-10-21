"""Where Kensa keeps review state, on this machine and in the repo."""

import hashlib
import json
import os
from pathlib import Path

from kensa.constants import (
    BASE_BRANCH_KEY,
    COMMENTS_FILE,
    CONFIG_FILE,
    DEFAULT_BASE_BRANCH,
    HOME_DIR_NAME,
    HOME_ENV,
    OPEN_MD_NAME,
    REPO_NOTES_DIR,
    SERVER_FILE,
)


def kensa_home():
    override = os.environ.get(HOME_ENV)
    if override:
        return Path(override)
    return Path.home() / HOME_DIR_NAME


def repo_state_dir(root):
    digest = hashlib.sha256(str(Path(root).resolve()).encode("utf-8")).hexdigest()[:16]
    directory = kensa_home() / "repos" / digest
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / "repo-path"
    resolved = str(Path(root).resolve())
    if not marker.is_file() or marker.read_text(encoding="utf-8") != resolved:
        marker.write_text(resolved, encoding="utf-8")
    return directory


def comments_path(root):
    return repo_state_dir(root) / COMMENTS_FILE


def server_path():
    home = kensa_home()
    home.mkdir(parents=True, exist_ok=True)
    return home / SERVER_FILE


def open_md_path(root):
    return Path(root) / REPO_NOTES_DIR / OPEN_MD_NAME


def read_config():
    path = kensa_home() / CONFIG_FILE
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(loaded, dict):
        return {}
    return loaded


def write_config(data):
    home = kensa_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / CONFIG_FILE).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def base_branch_name():
    """Comparison branch chosen at setup. Defaults to develop."""
    stored = read_config().get(BASE_BRANCH_KEY)
    if isinstance(stored, str) and stored.strip():
        return stored.strip()
    return DEFAULT_BASE_BRANCH


def save_base_branch(name):
    data = read_config()
    data[BASE_BRANCH_KEY] = name
    write_config(data)
    return name
