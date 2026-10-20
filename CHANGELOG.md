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
- The command is `kc` (Kensa changes). `kc` inspects your uncommitted changes. `kc <branch>` inspects that branch against the default branch. If the branch has a GitHub pull request, Submit review posts it through `gh`.
- The first install is `python3 bin/kc setup`. It links `kc` onto `~/.local/bin`, adds that directory to `~/.zshrc` when PATH needs it, and registers the MCP server. An existing `kc` program is left in place.
- Setup makes Kensa the reviewer for Grok and Claude. It asks for the phrase that opens a review, and uses `review` when you press enter or when the shell is not interactive. `kc setup --prompt <phrase>` sets the phrase directly. An existing Grok review skill that setup did not write is left in place.
- That phrase calls the `open_review` tool, which opens the Kensa screen.
- The diff is two panes, old on the left and new on the right. The file list can be collapsed.
- The page has Dark and Bright themes. The choice is kept in the browser.
- The review page was redesigned: quieter chrome, a clearer file list, and a calmer diff.
- A comment is written on the line. Click the line, write the note, and Save.
- The README is the short install and command page.
