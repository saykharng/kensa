# Kensa scope

This is the product the repository is building. Version 0.1 implements the local review loop below. A change to behavior should update this file. Install and the review commands are in the [README](../README.md).

## Product

Kensa is an open source local review tool. People install it once and use it beside whichever agent writes their code, including Grok, Claude, and Cursor. The installed program is a build of this repository.

The interface is a browser tab. The first install, from a checkout, is `python3 bin/kc setup`. That links `kc` onto `~/.local/bin` and registers the agent. If `~/.local/bin` is not on PATH, setup adds it in `~/.zshrc`. If a different `kc` is already installed, setup leaves that program in place. Setup also makes Kensa the reviewer for Grok and Claude when those are installed. It asks for the phrase that should open a review. The default phrase is `review`. `kc setup --prompt <phrase>` sets that phrase without asking. After that, `kc` in a repository starts one local server if it is not already running and opens the tab. An IDE does not have to be open. The command name is Kensa changes: it inspects the changes.

## Reviewing a change

- The server watches the git working tree and refreshes the diff against `HEAD`. It does not care which process saved the file.
- Opening a change shows the whole file in two panes: old on the left, new on the right. Changed lines stay highlighted. The rest of the file is visible. The file list can be collapsed. The page can be dark or bright, and the browser remembers the choice.
- **Edit** then **Save** writes the file to disk. The agent sees that write the next time it reads the file.
- A person comments by clicking a line. The note opens under that line. They mark it `bug`, `suggestion`, or `nit` and press **Save**. **Dismiss** removes it. The comment follows the line text when the file changes.

## Moving through the code

From the open file, in the same tab:

- An outline of functions and classes in that file.
- Quick open for any file in the repository.
- Jump from a symbol to its definition, using a symbol index built from the repository, plus search.
- Back, to the line you came from.

A file opened only for context stays marked as context. It joins the review list when the diff shows that it changed.

Version 1 does not run a language server. One can be added later.

## Talking to the agent

Two doors, same comments:

- `.kensa/open.md` in the repository under review, which any agent can read. Kensa gitignores that path in the repository it is reviewing so the notes are not committed by accident.
- An MCP server, `kc mcp`, with `open_review`, `review_open`, `review_comments`, and `review_status`. `open_review` opens the review screen. The other tools read the same review files as the browser.

The installer registers that MCP server with every agent it finds. For Grok, it writes the `kensa` skill, a home rule, and replaces `/review` when that skill is still the one setup wrote. For Claude, it writes the `kensa` skill and a marked block in `~/.claude/CLAUDE.md`. When a review is asked, the agent calls `open_review`. That opens the screen. **Send** writes `.kensa/open.md` so the next agent turn can read the comments. **Hold** tells the agent to stop new edits until Hold is turned off.

Review state for the app itself lives in `~/.kensa/<repo>/`, not in the repository under review.

## Someone else's branch

`kc <branch>` loads the diff of that branch against the default branch, usually `main`. The command takes the branch name. When GitHub has an open pull request for that branch, **Submit review** posts one review through `gh`, with verdict `COMMENT`, `REQUEST_CHANGES`, or `APPROVE`. Each comment is attached to a line on the new side of the diff. Submitting needs `gh auth login` once on that machine.

## Out of scope for the first version

A full editor, a language server, a terminal, a package of per-agent hooks, telemetry, and a second GitHub website.

## Implementation

- Python 3.11 or newer, standard library only. The page is static HTML, CSS, and JavaScript served by that process.
- The server listens on `127.0.0.1:4317`.
- Symbol jump is a repository search with declaration lines ranked first. There is no language server.
