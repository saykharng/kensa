# Kensa

Local code review in a browser tab. Kensa watches a git repo while an agent writes code, and lets you read the whole changed file, comment, edit, and send that review back. It is meant to work with Grok, Claude, Cursor, and any other coding agent.

**Status:** version 0.1 runs locally. Reviewing your own uncommitted changes needs no branch argument. Reviewing someone else's branch is `kensa` plus the branch name.

Kensa is a local program. Review notes stay on your machine. The page is served at `127.0.0.1:4317`. Kensa contacts GitHub only when that branch has a pull request and you submit the review.

## Review your own changes

Use this while you, or your coding agent, are editing the repository. No pull request number is required. Kensa compares the working tree with the last commit.

```bash
python3 bin/kensa
```

The left column is headed **Changes**. `M` is a modified file, `A` is a new file, and `D` is a deleted file.

Open a file and you get the whole file. Added lines are highlighted, deleted lines sit beside them, and the rest of the file is normal source so you can scroll to it.

- Click a line number and write a comment. Mark it `bug`, `suggestion`, or `nit`.
- On a changed hunk, press **OK** or **Change**.
- Press **Edit**, change the file, and **Save**. That writes the file on disk.
- **Send** writes `.kensa/open.md` for your coding agent. GitHub does not see it.
- **Hold** tells the agent to stop making new edits until you turn Hold off.

Quick open, the outline, and jump-to-symbol stay in the same tab. A file you open only for context is marked **Context**.

## Review someone else's branch

Use this when another person asked you to review their branch. Pass the branch name. Kensa compares that branch with the default branch, usually `main`.

```bash
python3 bin/kensa their-branch
```

A bar shows `their-branch compared with main`. The left column is headed **Branch** and lists only files that branch changed.

- **read only** means you do not have that branch checked out. You can read the whole file and comment. **Edit** is hidden.
- **checked out** means your current commit is the tip of that branch. **Edit** and **Save** write your working tree.

Comment the same way as on your own changes. **Send** writes `.kensa/open.md` on your machine.

If GitHub has an open pull request for that branch, the bar also shows a verdict, **Comment**, **Request changes**, or **Approve**, and **Submit review**. That posts the review on the pull request. You still do not put a number in the command. A comment on a line outside the diff is included in the summary, because GitHub rejects it as an inline comment.

## Where the review goes

| | Your own changes | Someone else's branch |
| --- | --- | --- |
| Command | `python3 bin/kensa` | `python3 bin/kensa their-branch` |
| File list | Files you have not committed | Files that branch changed since `main` |
| Save | Writes your working tree | Writes your working tree only when that branch is checked out |
| Send | `.kensa/open.md` for your agent | Same local file |
| Submit review | Not on this screen | Shown when that branch has a GitHub pull request |

## Run

Requires Python 3.11 or newer and `git`. No extra packages. The commands above start the server on `127.0.0.1:4317` if it is not already running.

```bash
python3 bin/kensa setup
```

`setup` writes a Kensa MCP server into this repo's `.mcp.json` and `.cursor/mcp.json`, and into the agent configs it finds under your home directory. The tools are `review_open`, `review_comments`, and `review_status`.

Kensa adds `.kensa/` to `.git/info/exclude` so the notes file is not committed. Review state stays in `~/.kensa/`.

```bash
PYTHONPATH=src python3 -m unittest
```

## Repository layout

| Path | Purpose |
| --- | --- |
| `bin/kensa` | Command |
| `src/kensa/` | Server, review, and MCP |
| `docs/scope.md` | Product scope |
| `CONTRIBUTING.md` | How to suggest a change |
| `CODE_OF_CONDUCT.md` | Community standards |
| `SECURITY.md` | How to report a vulnerability |
| `CHANGELOG.md` | Notable changes |

## Contributing

Please read [CONTRIBUTING.md](CONTRIBUTING.md) and the [code of conduct](CODE_OF_CONDUCT.md) before opening a pull request. A behavior change should update [docs/scope.md](docs/scope.md).

## Security

Report vulnerabilities privately. See [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE). Copyright (c) 2026 Shekhar Gyanwali.
