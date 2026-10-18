# Kensa scope

This is the product the repository is building. Version 0.1 implements the local review loop below. A change to behavior should update this file.

## Product

Kensa is an open source local review tool. People install it once and use it beside whichever agent writes their code, including Grok, Claude, and Cursor. The installed program is a build of this repository.

The interface is a browser tab. `kensa`, run in a repository, starts one local server if it is not already running and opens the tab. An IDE does not have to be open.

## Reviewing a change

- The server watches the git working tree and refreshes the diff against `HEAD`. It does not care which process saved the file.
- Opening a change shows the whole file. Changed lines stay highlighted. The rest of the file is visible and editable.
- Save writes the file to disk. The agent sees that write the next time it reads the file.
- A person can comment on a line and mark it `bug`, `suggestion`, or `nit`, and can mark a hunk `ok` or `change this`.

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
- An MCP server, `kensa mcp`, with `review_open`, `review_comments`, and `review_status`. It reads the same review files as the browser.

The installer registers that MCP server with every agent it finds. **Send** is how the next agent turn picks up the comments. **Hold** keeps the person on the current diff until they send.

Review state for the app itself lives in `~/.kensa/<repo>/`, not in the repository under review.

## Pull requests

`kensa pr <number>` loads that pull request's diff into the same page. **Submit review** posts one GitHub review through `gh`, with verdict `COMMENT`, `REQUEST_CHANGES`, or `APPROVE`. Each comment is attached to a line on the new side of the diff. This needs `gh auth login` once on that machine.

## Out of scope for the first version

A full editor, a language server, a terminal, a package of per-agent hooks, telemetry, and a second GitHub website.

## Implementation

- Python 3.11 or newer, standard library only. The page is static HTML, CSS, and JavaScript served by that process.
- The server listens on `127.0.0.1:4317`.
- Symbol jump is a repository search with declaration lines ranked first. There is no language server.
