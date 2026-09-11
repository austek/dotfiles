# AI Assistant Guidelines for Dotfiles

This document provides guidelines for AI assistants (like Gemini, Claude, or GitHub Copilot) when contributing to or modifying this repository.

## Repository Context
- This repository contains personal configuration files (dotfiles) for an Ubuntu-based development environment.
- It is designed to be automated, preset-aware, and easily deployed on new machines.
- The core architecture relies on **GNU Stow** to manage symlinks and a custom `setup.sh` script to orchestrate the installation.

## Architecture & Design Principles

### 1. Package Management (Strict Rule)
- **NEVER** suggest or use `apt-get install` directly to add applications.
- To add or remove applications, update the text files located in the `~/.dotfiles/packages/` directory.
- Available package lists include: `apt_common.txt` (all presets, headless-safe), `apt_desktop.txt` (GUI packages, pulled in by `work`/`personal` only), `apt_work.txt`, `apt_personal.txt`, `apt_homelab.txt`, and `github_bins.txt`.
- The `setup.sh` script handles downloading and installing `.deb` packages from GitHub releases based on the text list.

### 2. Snap-Free Environment
- This is a strictly Snap-Free edition.
- `snapd` is automatically removed and blocked via an `apt` preference file in the `system/` package. Do not write scripts that rely on snap packages.

### 3. Preset-Aware Setup
- The setup is preset-aware; the `setup.sh` script requires a `--preset work`, `--preset personal`, or `--preset homelab` argument.
- It builds configuration files based on the chosen preset.
- Per-preset Claude Code settings are stored in `~/.dotfiles/claude-profiles/`. See "Presets and Portability" below for how a preset's package list is resolved and forked per machine.

### 4. Apt Repositories
- Third-party `apt` repositories are declaratively managed using `.sources` files within the `apt/` package.
- The setup script handles securely downloading the latest GPG keys.

### 5. Claude Code Skills
- Shareable Claude Code skills and commands live in a separate public marketplace repo, [austek/claude-skills](https://github.com/austek/claude-skills), referenced from `claude/.claude/settings.json`'s `extraKnownMarketplaces`/`enabledPlugins`.
- This repo carries no vendored skills or commands of its own.
- To add a new skill, author it in `austek/claude-skills`, not here.

## Presets and Portability
- Presets are manifests at `presets/<name>.json` (this repo ships `work`, `personal`, `homelab`); each lists which `packages/` files to install and which `claude-profiles/*.json` supplies Claude Code settings. Add a machine type by dropping in a new `presets/<name>.json`, not by editing code.
- `dotfiles-setup install --preset <name>` resolves a preset's package files and, the first time it runs for that preset on a machine, forks the result to `~/.config/dotfiles/packages/<name>.txt`. That forked file is then the user's to hand-edit; never suggest deleting or wholesale-regenerating it.
- Later runs only append package names the preset has newly gained since the last run — never anything the user removed from the forked file, regardless of what else in the preset changed. Preserve this behavior in any change that touches the reconcile logic.
- An optional sibling clone at `~/.dotfiles-private` (or `$DOTFILES_PRIVATE_ROOT`) is auto-detected and layered on top of this public repo: `git/gitconfig-work` for git identity overrides, `packages/<preset>_extra.txt` for extra packages, and `claude-profiles/<preset>.json` for extra Claude settings merged over this repo's own. It is a separate repo — never assume it exists, and never put its content in this one.

## Shell & Environment Standards

### Zsh Configuration
- Custom Zsh functions must be stored in `~/.config/zsh/functions`.
- They are efficiently loaded using `fpath` and `autoload`.
- Add to `PATH` with `path_prepend` / `path_append`, never `export PATH=...`. They skip directories that do not exist, and `typeset -U path` keeps entries unique.

### No Machine-Specific Paths
- **Never** hardcode an absolute home directory (`/home/<user>`, `/Users/<user>`). Use `$HOME` or `~`, so the file works on every machine.
- Inside a JSON hook `command`, write `"$HOME/..."` with **double** quotes. Single quotes stop the shell expanding it, leaving a dead literal path.
- `~/.zshrc` is a symlink **into this repo**, so any installer that "adds a line to your `.zshrc`" edits the tracked dotfile and it propagates to every machine. After running one, check `git diff -- zsh/.zshrc`.
- `scripts/validate-no-machine-paths.sh` enforces this. It runs in CI and in `dotfiles-backup`, which refuses to commit while it fails.

### Secrets Management
- True secrets (API keys, tokens) must never be committed and are ignored by Git.
- Secrets should be manually placed in `~/.zshrc.secret`, which is sourced by `.zshrc`.

### Git Configuration
- The repository uses a layered Git configuration.
- `~/.dotfiles/git/.gitconfig` is stowed to `~/.gitconfig` and carries the shared non-identity settings (`core`, `gpg`, `commit`, `tag`, credential helpers) directly.
- `git/.gitconfig` carries no identity of its own — it includes `~/.gitconfig.local` (written by `dotfiles-setup install` on first run) for name/email, and conditionally includes `~/.dotfiles-private/git/gitconfig-work` (an optional sibling repo, not part of this one) for a work-specific override.

## Maintenance & Workflows

### Modifying Configurations
- Edit configuration files directly inside their respective `stow` packages (e.g., `~/.dotfiles/zsh/.zshrc`).
- Symlinks are managed by `stow <package-name>` (to create) and `stow -D <package-name>` (to delete).
- Manual stowing is for quick adjustments; `setup.sh` handles it automatically during normal installation.

### Saving Changes
- Use the provided `dotfiles-backup save` command to save changes.
- This helper script automatically stages changes, commits them with a standard message, and pushes them to the remote repository.
