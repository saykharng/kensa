# Contributing to Kensa

Thanks for helping. Kensa is open source under the MIT license, and this file is how changes get in.

## Before you start

Read [docs/scope.md](docs/scope.md). That file is the product until the app exists. A pull request that changes behavior should update it in the same pull request.

The review server and page are not implemented yet. Issues and pull requests about the scope, docs, and project setup are welcome. Please open an issue before a large code change so the approach can be agreed.

## How to send a change

1. Fork the repository and create a short-lived branch.
2. Make the change. Keep the diff limited to that change.
3. Open a pull request using the template.
4. A maintainer reviews it. Committers may ask for edits.

By submitting a contribution, you agree that it is licensed under the MIT license in [LICENSE](LICENSE).

## Reports

- Bugs and features: [GitHub issues](https://github.com/saykharng/kensa/issues).
- Security: follow [SECURITY.md](SECURITY.md). Do not file a public issue for a vulnerability.
- Conduct: follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## What not to commit

- Tokens, passwords, or GitHub credentials.
- Review notes, local Kensa state, or anything from `~/.kensa/`.
- Generated dependency folders (`node_modules/`, `dist/`, `target/`).

## Tests

There is no test suite yet. When one exists, a behavior change needs a test run recorded in the pull request.
