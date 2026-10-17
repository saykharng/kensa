# Kensa

Local code review in a browser tab. Kensa watches a git repo while an agent writes code, and lets you read the whole changed file, comment, edit, and send that review back. It is meant to work with Grok, Claude, Cursor, and any other coding agent.

**Status:** the repository is public and the product scope is locked. The review server and page are not implemented yet, so there is nothing to install.

## What it is for

Keep a browser tab open instead of an IDE.

- See changes as they land on disk.
- Open a changed file in full, with the edits highlighted, and change any part of that file.
- Jump to other code from the open file: an outline, quick open, and jump to a symbol.
- Comment on a line and send those comments to the agent.
- Review someone else's GitHub pull request and submit that review from the same page.

Kensa is a local program. Review notes and GitHub credentials stay on your machine. The app does not phone home.

## Repository layout

| Path | Purpose |
| --- | --- |
| `docs/scope.md` | Locked product scope |
| `CONTRIBUTING.md` | How to suggest a change |
| `CODE_OF_CONDUCT.md` | Community standards |
| `SECURITY.md` | How to report a vulnerability |
| `CHANGELOG.md` | Notable changes |

## Contributing

Please read [CONTRIBUTING.md](CONTRIBUTING.md) and the [code of conduct](CODE_OF_CONDUCT.md) before opening a pull request. Product behavior belongs in [docs/scope.md](docs/scope.md) until the app exists.

## Security

Report vulnerabilities privately. See [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE). Copyright (c) 2026 Shekhar Gyanwali.
