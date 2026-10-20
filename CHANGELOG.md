# Changelog

All notable changes to Kensa are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
once it ships releases.

## [Unreleased]

### Added

- Open source repository: MIT license, contributing guide, code of conduct, security policy, and issue templates.
- Local review server and browser page: full-file view, diff highlights, edit and save, line comments, quick open, outline, and symbol jump.
- `.kensa/open.md` for any coding agent, plus an MCP server with `review_open`, `review_comments`, and `review_status`.
- `kensa setup` registers that MCP server with the agents it finds.
- `kensa <branch>` reviews that branch against the default branch. If the branch has a GitHub pull request, Submit review posts it through `gh`.
- The diff is two panes, old on the left and new on the right. The file list can be collapsed.
- The page has Dark and Bright themes. The choice is kept in the browser.
- The review page was redesigned: quieter chrome, a clearer file list, and a calmer diff.
- A comment is written on the line. Click the line, write the note, and Save.
- The README explains how to use each feature.
