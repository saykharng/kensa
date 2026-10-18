# Kensa

Local code review in a browser tab. Kensa watches a git repo while an agent writes code, and lets you read the whole changed file, comment, edit, and send that review back. It is meant to work with Grok, Claude, Cursor, and any other coding agent.

**Status:** version 0.1 runs locally. It can review the working tree, edit a file, comment, and hand that review to an agent. Opening a GitHub pull request needs `gh auth login`. The public GitHub repository is not created yet.

## What it is for

Keep a browser tab open instead of an IDE.

- See changes as they land on disk.
- Open a changed file in full, with the edits highlighted, and change any part of that file.
- Jump to other code from the open file: an outline, quick open, and jump to a symbol.
- Comment on a line and send those comments to the agent.
- Review someone else's GitHub pull request and submit that review from the same page.

Kensa is a local program. Review notes and GitHub credentials stay on your machine. The app does not phone home.

## Run

Requires Python 3.11 or newer and `git`. No extra packages.

```bash
python3 bin/kensa
```

That starts the server on `127.0.0.1:4317` if it is not already running, and opens this repository in a browser tab.

```bash
python3 bin/kensa pr 123
python3 bin/kensa setup
```

`setup` writes a Kensa MCP server into this repo's `.mcp.json` and `.cursor/mcp.json`, and into the agent configs it finds under your home directory. The tools are `review_open`, `review_comments`, and `review_status`.

Press **Send** to write `.kensa/open.md`. Kensa adds `.kensa/` to `.git/info/exclude` so that file is not committed. Review state stays in `~/.kensa/`.

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
