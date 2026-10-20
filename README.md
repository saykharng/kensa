# Kensa

Local code review in a browser tab. Kensa watches a git repo while an agent writes code, and lets you read the whole changed file, comment, edit, and send that review back. It works with Grok, Claude, Cursor, and any other coding agent.

**Status:** version 0.1 runs locally. Review notes stay on your machine. The page is served at `127.0.0.1:4317`. Kensa contacts GitHub only when you submit a review on a pull request.

## Start a review

Review your own uncommitted changes. Kensa compares the working tree with the last commit and opens the browser.

```bash
python3 bin/kensa
```

Review someone else's branch. Pass the branch name. Kensa compares it with the default branch, usually `main`.

```bash
python3 bin/kensa their-branch
```

A bar shows `their-branch compared with main`. The file list is headed **Branch** and contains only files that branch changed. **read only** means that branch is not checked out, so you can read and comment. **checked out** means your current commit is the tip of that branch, so **Edit** and **Save** write your working tree.

Requires Python 3.11 or newer and `git`. No extra packages. The command starts the server if it is not already running.

## File list

The left column lists changed files. `M` is modified, `A` is new, and `D` is deleted. Click a path to open it. A number on the right is how many comments that file has.

## Diff

The open file is shown whole, in two panes. **Old** is on the left and **New** is on the right. Added lines are green, deleted lines are red, and the panes stay lined up as you scroll. The rest of the file stays visible.

Press `j` for the next added line and `k` for the previous one.

## Hide the file list

The double arrow at the top of the file list hides it. The arrow on the thin rail shows it again. On a narrow window the same arrow points up to hide and down to show. The choice lasts for this browser tab.

## Comment on a line

Click a line. A box opens under that line. Choose `bug`, `suggestion`, or `nit`, write the note, and press **Save**. **Cancel** closes the box. **Dismiss** removes a saved comment.

Click either side of the row. On a deleted file, click the old side. Click the line again to write another comment.

If the line text moves, the comment follows it. If the line disappears, the comment stays at the top of the file and is marked **moved**.

## Edit the file

Press **Edit**, change the text, and press **Save**. That writes the file on disk. **Cancel** drops the edit. **Edit** is hidden when the file is read only.

## Send

**Send** writes `.kensa/open.md` in the repository. That file is for the coding agent. It lists each comment, and it says whether Hold is on. Kensa keeps the file out of git. Your review state stays in `~/.kensa/`.

## Hold

Press **Hold** when you want the agent to stop making new edits. The button changes to **Holding**. Press it again to let the agent continue. **Send** includes that instruction in `.kensa/open.md`.

## Submit a GitHub review

This appears only when you opened a branch and GitHub has an open pull request for it. Choose **Comment**, **Request changes**, or **Approve**, write a summary, and press **Submit review**. That posts the review on the pull request. You still pass a branch name to Kensa, not a pull request number.

A comment on a line inside the diff is posted on that line. A comment outside the diff is included in the summary. Submitting needs `gh auth login` once on that machine.

## Quick open

Type in **Quick open** and click a path. You can open any file in the repository, including one that is not in the change list. A file opened only for context is marked **Context**. It joins the change list when the diff shows that it changed.

## Outline

The **Outline** menu lists functions and classes in the open file. Pick one and the page scrolls to it.

## Jump to a symbol

Type a name in **Jump to symbol**, or select a name in the file, and press **Jump**. Kensa opens the definition it finds in the repository. If several files match, they are listed under the file search.

## Back

**Back** returns to the file and line you came from.

## Dark and bright

The icon in the header switches the page. The moon turns on dark. The sun turns on bright. This browser remembers the choice.

## Connect an agent

```bash
python3 bin/kensa setup
```

`setup` registers a Kensa MCP server with the agents it finds, including this repo's `.mcp.json` and `.cursor/mcp.json`. The tools are `review_open`, `review_comments`, and `review_status`. They read the same notes as the page. **Send** is how the next agent turn picks up the comments.

## Which review is which

| | Your own changes | Someone else's branch |
| --- | --- | --- |
| Command | `python3 bin/kensa` | `python3 bin/kensa their-branch` |
| File list | Files you have not committed | Files that branch changed since `main` |
| Save | Writes your working tree | Writes your working tree only when that branch is checked out |
| Send | `.kensa/open.md` for your agent | Same local file |
| Submit review | Not on this screen | Shown when that branch has a GitHub pull request |

## Develop

```bash
PYTHONPATH=src python3 -m unittest
```

| Path | Purpose |
| --- | --- |
| `bin/kensa` | Command |
| `src/kensa/` | Server, review, and MCP |
| `docs/scope.md` | Product scope |
| `CONTRIBUTING.md` | How to suggest a change |
| `CODE_OF_CONDUCT.md` | Community standards |
| `SECURITY.md` | How to report a vulnerability |
| `CHANGELOG.md` | Notable changes |

Please read [CONTRIBUTING.md](CONTRIBUTING.md) and the [code of conduct](CODE_OF_CONDUCT.md) before opening a pull request. A behavior change should update [docs/scope.md](docs/scope.md). Report vulnerabilities privately. See [SECURITY.md](SECURITY.md).

[MIT](LICENSE). Copyright (c) 2026 Shekhar Gyanwali.
