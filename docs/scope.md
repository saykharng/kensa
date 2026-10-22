# Kensa scope

This is the product the repository is building. Version 0.1 implements the local review loop below. A change to behavior should update this file. Install and the review commands are in the [README](../README.md).

## Product

Kensa is an open source local review tool. People install it once and use it beside whichever agent writes their code, including Grok, Claude, and Cursor. The installed program is a build of this repository.

The interface is a browser tab. The first install, from a checkout, is `python3 bin/kc setup`. That links `kc` onto `~/.local/bin` and registers the agent. If `~/.local/bin` is not on PATH, setup adds it in `~/.zshrc`. If a different `kc` is already installed, setup leaves that program in place. Setup also makes Kensa the reviewer for Grok and Claude when those are installed. It asks for the phrase that should open a review, and for a comparison branch to remember. The default phrase is `review`. The default branch is `develop`. Press enter to accept either. `kc setup --prompt <phrase> --base <branch>` sets both without asking. The choice is stored in `~/.kensa/config.json`. That saved name is one candidate, not the only base. Setup ends by printing `Setup complete. Run kc in a repository to open a review.` After that, `kc` in a repository starts one local server if it is not already running and opens the tab. An IDE does not have to be open. The command name is Kensa changes: it inspects the changes.

## Reviewing a change

- The header states the range that was opened: `feature vs master (merge-base 2091bcf) · 3 commits · 8 files`. When one commit is open, its id and subject replace the commit count. Merge commits that were left out are counted on that same line.
- The base is chosen per branch. An explicit base (`kc feature master`, or `base` on `open_review`) wins for that run. Otherwise Kensa uses the branch upstream when it names a different branch. Otherwise it picks whichever of the saved branch, `develop`, `main`, `master`, and `trunk` exists here and has the nearest merge-base. The saved setup branch wins a tie.
- The diff includes commits on the current branch and edits that are not committed yet. Files that changed only inside a merge commit are left out. A clean branch with exactly one non-merge commit opens that commit. The commit menu can switch to the whole range, or to another non-merge commit. It does not care which process saved the file.
- Opening a change shows two panes: old on the left, new on the right. Only the changed lines are shown first. **Full file** reveals the rest of that file in the same pane, and **Changes only** hides it again. Each file remembers that choice while the tab is open. A file opened only for context is shown in full. The file list can be collapsed. The page can be dark or bright, and the browser remembers the choice.
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
- An MCP server, `kc mcp`, with `open_review`, `review_open`, `review_comments`, and `review_status`. `open_review` opens the review screen and returns the resolved base, merge-base, commit count, and file count. Pass `commit` to open one commit. The other tools read the same review files as the browser.

The installer registers that MCP server with every agent it finds. For Grok, it writes the `kensa` skill, a home rule, and replaces `/review` when that skill is still the one setup wrote. For Claude, it writes the `kensa` skill and a marked block in `~/.claude/CLAUDE.md`. When a review is asked, the agent calls `open_review`. That opens the screen. **Send** writes `.kensa/open.md` so the next agent turn can read the comments. **Hold** tells the agent to stop new edits until Hold is turned off.

Review state for the app itself lives in `~/.kensa/<repo>/`, not in the repository under review.

## Someone else's branch

`kc <branch>` loads the diff of that branch. The base is inferred the same way as for the working tree, unless `kc <branch> <base>` names one for this run only. That one-off base does not change the branch saved at setup. When GitHub has an open pull request for that branch, **Submit review** posts one review through `gh`, with verdict `COMMENT`, `REQUEST_CHANGES`, or `APPROVE`. Each comment is attached to a line on the new side of the diff. Submitting needs `gh auth login` once on that machine.

## Out of scope for the first version

A full editor, a language server, a terminal, a package of per-agent hooks, telemetry, and a second GitHub website.

## Implementation

- Python 3.11 or newer, standard library only. The page is static HTML, CSS, and JavaScript served by that process.
- The server listens on `127.0.0.1:4317`.
- Symbol jump is a repository search with declaration lines ranked first. There is no language server.
