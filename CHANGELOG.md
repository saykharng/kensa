# Changelog

All notable changes to Kensa are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
once it ships releases.

## [Unreleased]

### Added

- Open source repository: MIT license, contributing guide, code of conduct, security policy, and issue templates.
- Local review server and browser page: full-file view, diff highlights, edit and save, line comments, hunk marks, quick open, outline, and symbol jump.
- `.kensa/open.md` for any coding agent, plus an MCP server with `review_open`, `review_comments`, and `review_status`.
- `kensa setup` registers that MCP server with the agents it finds.
- `kensa pr <number>` loads a GitHub pull request and can submit one review through `gh`.
