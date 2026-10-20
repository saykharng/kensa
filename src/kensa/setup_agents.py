"""Register Kensa's MCP server with the coding agents installed on this machine."""

import json
import os
import shutil
import sys
from pathlib import Path

from kensa.constants import (
    AGENT_CLAUDE,
    AGENT_GROK,
    BUNDLED_REVIEW_SKILL,
    COMMAND,
    DEFAULT_REVIEW_PROMPT,
    OPEN_REVIEW_TOOL,
    PATH_LINE,
    REVIEW_PROMPT_LIMIT,
    REVIEWER_MARKER,
    REVIEWER_SKILL,
    USER_BIN,
)
from kensa.gitrepo import RepoError

LAUNCHER_MARK = "from kensa.cli import main"


def install_command(home=None):
    """Link kc into ~/.local/bin. Leave a different kc program where it is."""
    home = Path(home) if home is not None else Path.home()
    binary = os.environ.get("KENSA_BIN")
    if not binary:
        return [f"Run python3 bin/{COMMAND} setup from the Kensa checkout to install {COMMAND}."]
    source = Path(binary).resolve()
    bindir = home / USER_BIN
    bindir.mkdir(parents=True, exist_ok=True)
    target = bindir / COMMAND
    if target.is_symlink() or target.exists():
        if _our_command(target):
            if target.is_symlink() and _link_matches(target, source):
                notes = [f"{COMMAND} is already installed at {target}"]
            else:
                target.unlink()
                target.symlink_to(source)
                notes = [f"updated {COMMAND} at {target}"]
        else:
            return [f"left {target} alone. Another program is already named {COMMAND}."]
    else:
        target.symlink_to(source)
        notes = [f"installed {COMMAND} at {target}"]
    notes.extend(_ensure_user_bin_on_path(home, bindir))
    return notes


def _link_matches(target, source):
    try:
        return target.resolve() == source
    except OSError:
        return False


def _our_command(path):
    if path.is_symlink():
        linked = Path(os.readlink(path))
        if linked.name == COMMAND and "kensa" in str(linked):
            return True
    candidate = path
    if path.is_symlink() and path.exists():
        candidate = path.resolve()
    if not candidate.is_file():
        return False
    try:
        text = candidate.read_text(encoding="utf-8")
    except OSError:
        return False
    return LAUNCHER_MARK in text


def _ensure_user_bin_on_path(home, bindir):
    directories = os.environ.get("PATH", "").split(os.pathsep)
    if str(bindir) in directories:
        return []
    rc = home / ".zshrc"
    existing = rc.read_text(encoding="utf-8") if rc.is_file() else ""
    if USER_BIN in existing:
        return [f"Open a new terminal so {bindir} is on PATH, then type {COMMAND}."]
    prefix = "" if existing.endswith("\n") or existing == "" else "\n"
    rc.write_text(existing + prefix + "\n# Kensa\n" + PATH_LINE + "\n", encoding="utf-8")
    return [f"Added {bindir} to {rc}. Open a new terminal, then type {COMMAND}."]


def agent_invocation():
    binary = os.environ.get("KENSA_BIN")
    if binary:
        return sys.executable, [binary, "mcp"]
    return sys.executable, ["-m", "kensa", "mcp"]


def install(repo, home=None):
    """Write MCP config for agents we can find. Returns notes about each file."""
    home = Path(home) if home is not None else Path.home()
    repo = Path(repo)
    command, args = agent_invocation()
    entry = {"command": command, "args": args}
    notes = []
    notes.append(_merge_mcp_json(repo / ".mcp.json", entry))
    cursor_project = repo / ".cursor"
    cursor_project.mkdir(parents=True, exist_ok=True)
    notes.append(_merge_mcp_json(cursor_project / "mcp.json", entry))
    if (home / ".grok").is_dir() or shutil.which("grok"):
        grok_dir = home / ".grok"
        grok_dir.mkdir(parents=True, exist_ok=True)
        notes.append(_append_grok(grok_dir / "config.toml", command, args))
    claude = home / ".claude.json"
    if claude.is_file():
        notes.append(_merge_mcp_json(claude, entry))
    cursor_user = home / ".cursor"
    if cursor_user.is_dir():
        notes.append(_merge_mcp_json(cursor_user / "mcp.json", entry))
    return notes


def _merge_mcp_json(path, entry):
    data = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return f"skipped {path} (not valid JSON)"
        if not isinstance(loaded, dict):
            return f"skipped {path} (not a JSON object)"
        data = loaded
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    servers["kensa"] = entry
    data["mcpServers"] = servers
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return f"wrote {path}"


def _append_grok(path, command, args):
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    if "[mcp_servers.kensa]" in existing:
        return f"already configured {path}"
    block = (
        "\n[mcp_servers.kensa]\n"
        f"command = {_toml_string(command)}\n"
        f"args = [{', '.join(_toml_string(arg) for arg in args)}]\n"
        "enabled = true\n"
    )
    suffix = "" if existing.endswith("\n") or existing == "" else "\n"
    path.write_text(existing + suffix + block, encoding="utf-8")
    return f"wrote {path}"


def _toml_string(value):
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def setup_prompt_arg(argv):
    """Return the phrase passed to setup, or None when setup should ask."""
    if not argv:
        return None
    if len(argv) == 2 and argv[0] == "--prompt":
        return argv[1]
    raise RepoError(f"Use {COMMAND} setup or {COMMAND} setup --prompt <phrase>")


def valid_review_prompt(prompt):
    text = str(prompt).strip()
    if not text or any(char in text for char in "\n\r\x00"):
        raise RepoError("The review phrase must be one non-empty line.")
    if len(text) > REVIEW_PROMPT_LIMIT:
        raise RepoError(f"The review phrase must be {REVIEW_PROMPT_LIMIT} characters or fewer.")
    if REVIEWER_MARKER in text or "<!--" in text or "-->" in text:
        raise RepoError("The review phrase cannot include a Kensa marker.")
    return text


def read_review_prompt(given, stdin):
    """Use --prompt, else ask on a terminal, else the default phrase."""
    if given is not None:
        return valid_review_prompt(given)
    if not stdin.isatty():
        return DEFAULT_REVIEW_PROMPT
    print(
        "Kensa will be the reviewer for Grok and Claude.\n"
        f"Phrase that opens a review [{DEFAULT_REVIEW_PROMPT}]: ",
        end="",
        flush=True,
    )
    line = stdin.readline()
    if line.strip() == "":
        return DEFAULT_REVIEW_PROMPT
    return valid_review_prompt(line)


def detect_review_agents(home):
    home = Path(home)
    found = []
    if (home / ".grok").is_dir() or shutil.which(AGENT_GROK):
        found.append(AGENT_GROK)
    if (home / ".claude").is_dir() or (home / ".claude.json").is_file() or shutil.which(AGENT_CLAUDE):
        found.append(AGENT_CLAUDE)
    return found


def install_reviewer(prompt=None, home=None, agents=None):
    """Install Kensa as the reviewer for Grok and Claude. Returns notes."""
    home = Path(home) if home is not None else Path.home()
    phrase = valid_review_prompt(DEFAULT_REVIEW_PROMPT if prompt is None else prompt)
    chosen = list(agents) if agents is not None else detect_review_agents(home)
    if not chosen:
        return ["No Grok or Claude found. Kensa is not set as a reviewer."]
    notes = []
    if AGENT_GROK in chosen:
        notes.extend(_install_grok_reviewer(home, phrase))
    if AGENT_CLAUDE in chosen:
        notes.extend(_install_claude_reviewer(home, phrase))
    return notes


def _install_grok_reviewer(home, phrase):
    skill = home / ".grok" / "skills" / REVIEWER_SKILL / "SKILL.md"
    review = home / ".grok" / "skills" / BUNDLED_REVIEW_SKILL / "SKILL.md"
    rule = home / ".grok" / "rules" / f"{REVIEWER_SKILL}.md"
    notes = [f"Kensa is the reviewer for Grok. Phrase: {phrase}"]
    notes.append(_write_text(skill, reviewer_skill(REVIEWER_SKILL, phrase)))
    notes.append(_claim_review_skill(review, reviewer_skill(BUNDLED_REVIEW_SKILL, phrase)))
    notes.append(_write_text(rule, reviewer_rule(phrase)))
    return notes


def _install_claude_reviewer(home, phrase):
    skill = home / ".claude" / "skills" / REVIEWER_SKILL / "SKILL.md"
    memory = home / ".claude" / "CLAUDE.md"
    notes = [f"Kensa is the reviewer for Claude. Phrase: {phrase}"]
    notes.append(_write_text(skill, reviewer_skill(REVIEWER_SKILL, phrase)))
    notes.append(_merge_marked(memory, reviewer_rule(phrase)))
    return notes


def reviewer_skill(name, prompt):
    triggers = _triggers(prompt)
    description = (
        f"Open the Kensa review screen. Use when the user says {prompt} or asks for a review. "
        f"Call the {OPEN_REVIEW_TOOL} tool and stop."
    )
    when = "Use when the user says " + ", ".join(triggers) + "."
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {_yaml_quote(description)}\n"
        f"when-to-use: {_yaml_quote(when)}\n"
        'argument-hint: "[branch]"\n'
        "user-invocable: true\n"
        "metadata:\n"
        f"  kensa: {REVIEWER_MARKER}\n"
        "---\n"
        "\n"
        f"{_skill_body(prompt)}"
    )


def reviewer_rule(prompt):
    shown = prompt.replace('"', "'")
    return (
        "# Kensa\n"
        "\n"
        f'When the user says "{shown}" or asks for a review, call the Kensa tool `{OPEN_REVIEW_TOOL}`. '
        "That opens the review screen.\n"
    )


def _triggers(prompt):
    ordered = [
        prompt,
        DEFAULT_REVIEW_PROMPT,
        "code review",
        "review my changes",
        "review my branch",
        f"/{REVIEWER_SKILL}",
        f"/{BUNDLED_REVIEW_SKILL}",
    ]
    found = []
    for item in ordered:
        if item not in found:
            found.append(item)
    return found


def _skill_body(prompt):
    return (
        "# Open the review screen\n"
        "\n"
        f"When the user says {prompt}, or asks for a review, call the Kensa tool `{OPEN_REVIEW_TOOL}`.\n"
        "\n"
        "Pass `branch` when they named a branch.\n"
        "\n"
        "The tool opens the review screen. Stop there.\n"
    )


def _yaml_quote(value):
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return f"wrote {path}"


def _claim_review_skill(path, text):
    if path.is_file() and REVIEWER_MARKER not in path.read_text(encoding="utf-8"):
        return f"left {path} alone. It is already a review skill."
    return _write_text(path, text)


def _merge_marked(path, block):
    begin = f"<!-- {REVIEWER_MARKER} -->"
    end = f"<!-- /{REVIEWER_MARKER} -->"
    wrapped = f"{begin}\n{block.rstrip()}\n{end}\n"
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    start = existing.find(begin)
    finish = existing.find(end)
    if start != -1 and finish > start:
        finish += len(end)
        if finish < len(existing) and existing[finish] == "\n":
            finish += 1
        updated = existing[:start] + wrapped + existing[finish:]
    elif existing == "":
        updated = wrapped
    else:
        prefix = existing if existing.endswith("\n") else existing + "\n"
        if not prefix.endswith("\n\n"):
            prefix += "\n"
        updated = prefix + wrapped
    return _write_text(path, updated)
