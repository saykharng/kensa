# Kensa

Review code changes locally. Install Kensa, then let your agent run `kc`. It opens the diff.

## Install

From a checkout of this repository:

```bash
python3 bin/kc setup
```

This links `kc` into `~/.local/bin` and registers it with your agent. If that directory is not on your PATH, setup adds it in `~/.zshrc`. Open a new terminal after that. If another program is already named `kc`, setup leaves it alone.

Setup also makes Kensa the reviewer for Grok and Claude when those are installed. It asks for the phrase that should open a review. Press enter to use `review`. Saying that phrase opens the Kensa screen. In a non-interactive shell, setup uses `review`.

```bash
python3 bin/kc setup --prompt "review my changes"
```

## Review

```bash
kc                # your uncommitted changes
kc their-branch   # that branch against main
```

[MIT](LICENSE). Copyright (c) 2026 Shekhar Gyanwali. See [CONTRIBUTING.md](CONTRIBUTING.md), [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md), and [SECURITY.md](SECURITY.md).
