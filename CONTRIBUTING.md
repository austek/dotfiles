# Contributing

Personal dotfiles for Ubuntu machines, installed by `dfctl` and linked by GNU Stow. `AGENTS.md` holds the architecture notes and the rules for AI assistants; this file holds what a contributor needs to change the repo.

## Where to develop

- `~/.dotfiles` and `~/.dotfiles-overlay` are live checkouts for `dfctl` only. Stow links point into them, so never switch branches or develop there.
- Develop in a clone under `~/Workspace/austek/`, branching from `origin/main` after `git fetch origin`. For parallel work add a worktree: `git worktree add ~/Workspace/austek/<repo>-wt/<slug> -b <branch> origin/main`.
- Never run `dfctl apply` or `stow` from a worktree. `apply` refuses (exit 1) unless it is a `--dry-run`.
- `main` is protected: PR and CI required. Never push to it.

## Branches, commits, PRs

- Branch: `<type>/<ID>_<snake_case_description>`, for example `feature/365_apple_xcframework` or `chore/NO_ISSUE_bump_deps`. `<ID>` is the GitHub issue number, or `NO_ISSUE`.
- Commit: `<type>[(<scope>)]: <subject> (#<issue>)`, or `<type>[(<scope>)]: <subject> NO_ISSUE` when there is no issue.
- Split mechanical cleanup from semantic changes into separate PRs.
- Use `dfctl propose` only to save drift in the live checkouts (hand edits, lines an installer added). Planned changes go through branches and PRs.

## Checks

`mise.toml` pins the dev tools and defines the tasks CI runs, so `mise run ci` reproduces CI locally.

| Task | Runs |
|---|---|
| `lint-shell`, `lint-python`, `check-python` | linters and type checks |
| `test`, `smoke`, `completions` | unit tests, smoke test, completion checks |
| `e2e <preset>` | container install of one preset |
| `pin`, `pin-check` | record or report stale download digests |

The `.githooks/pre-commit` hook runs the shell and machine-path validation before each commit.

## Rules for every change

- No absolute home paths (`/home/<user>`, `/Users/<user>`). Use `$HOME` or `~`. In a JSON hook `command`, use double quotes: `"$HOME/..."`. `scripts/validate-no-machine-paths.sh` enforces this in CI.
- No secrets in the repo. Env-var secrets go in `~/.config/dotfiles/secrets.env` (mode 600, plain `KEY=value` lines).
- No snap. `snapd` is removed and blocked, so nothing may depend on it.
- Never edit `~/.claude/settings.json`; it is generated. Edit `claude/.claude/settings.json`, a `claude-profiles/*.json` file, or the overlay.
- A step that changes system state records an undo entry in the rollback log (`RollbackLog.track`). A new sudo step goes in `install_flow.SYSTEM_STEPS`, and in `system_check` if its state can be read without root.
- Output goes through `Logger`, not `print`, so it reaches syslog and the install transcript.
- Zsh functions live in `~/.config/zsh/functions`. The base `PATH` lives in `zsh/.zshenv`.
- Shareable Claude Code skills belong in `austek/ustekai-skills`, not here.
- Private or employer-specific content belongs in the overlay (`austek/dotfiles-overlay`), never in this repo.

## Where executables go

A tool `dfctl` installs at user level puts its executable in `~/.local/bin`, or symlinks it there, so managed executables live in one place. The directory is on `PATH` through `zsh/.zshenv` and the foothold unit. The exceptions are listed below.

- **Install or link, never spell the path.** Call `release_installers.user_bin_dir` for the directory. `fsutil.install_executable` writes a file there atomically (mode 0755). `fsutil.link_executable` makes an atomic symlink, replaces only a symlink, and returns an error for a regular file or directory instead of replacing it. A file that appears between its check and the replace can still be overwritten.
- **A tool with its own directory** (JetBrains Toolbox, SonarQube CLI, AWS CLI) installs there and gets a symlink in `~/.local/bin`, so it needs no `PATH` entry of its own. Do not add a single-tool entry to `zsh/.zshenv`.
- **Exceptions:** files dpkg owns (apt, `github_bins.txt`, zoom), Flatpak exports, self-managing toolchains under `~/.sdkman`, `~/.nvm` and `~/.cargo`, and Antigravity, which is a root-owned `/opt` install in the system stage. `tests/test_bin_policy.py` holds the allowed roots (also `~/.oh-my-zsh`, `~/.local/aws-cli` and `~/.local/share/<tool>/`) and the exempt modules, each with its reason. A new installer that needs sudo or another location extends that file in the same change.
- **No sudo in the user stage.** A sudo call outside a declared module fails `tests/test_bin_policy.py`, and each declared module lists the sudo verbs it may run: any other verb in it fails too. A step that needs root belongs in `SYSTEM_STEPS`.
- **Spelling the path:** the same test fails on code that spells `~/.local/bin` as a path outside `release_installers.py`: a string literal that ends in or runs through `.local/bin`, or `.local` then `bin` joined with `/`, `os.path.join`, `joinpath` or `Path(...)`. A path built by concatenation or from a variable escapes it. `foothold.py` is a named exception because a systemd unit needs the `%h/.local/bin` specifier.
- **Rollback:** record what you installed (`BIN_INSTALLED`, `LINK_INSTALLED`, `DIR_CREATED`) so an undo removes only what you installed: a file only while it is still the file you wrote, a directory only when it is empty.
- **Existing copies are reported, never deleted.** `report_stale_copies` logs a same-named file in `~/.dotfiles/bin`, `~/bin` or `/usr/local/bin` that resolves to a different file. `~/bin` precedes `~/.local/bin` on `PATH`, so a hand-installed `~/bin/<tool>` wins until you remove it.

## Adding a package

Never run `apt-get install` to add an application. Declare it in `packages/`, then run `dfctl apply`. It installs what a list gained and, after a confirmation prompt, removes what a list dropped. A machine that does not want a package adds it to its own opt-out file (`~/.config/dotfiles/packages/<preset>.txt`) instead of changing the repo.

### 1. Pick the mechanism

Take the first row that fits.

| # | Case | Mechanism | Declare in |
|---|---|---|---|
| 1 | In the Ubuntu archive or an apt repo already under `apt/` | apt | an `apt_*.txt` list |
| 2 | GUI app that Flathub ships | Flatpak, user-level, no sudo | `flatpak:<app-id>` in a `flatpak_*.txt` list |
| 3 | CLI whose GitHub release has a `.deb` | pinned GitHub `.deb` | a line in `packages/github_bins.txt` |
| 4 | Release binary or archive that needs no custom steps | pinned release | a line in `packages/release_specs.json`, plus its name in an `apt_*.txt` list |
| 5 | Publishes its own apt repository | third-party apt repo | a `.sources` file under `apt/`, a signing-key entry in `KEYS` and an entry in `SOURCE_FILES` (both in `apt_sources.py`), then case 1 |
| 6 | Only an install script, or needs custom install steps | vendor installer | `vendor_installers.py` or `release_installers.py`, plus its name in `CUSTOM_INSTALL_PACKAGES` (`apt_packages.py`) |

Prefer a pin (cases 3 and 4) over apt only when the archive version is too old or missing. Pins cost a version bump per release.

Apt-installed packages stay at whatever the archive offers. Pinned ones move only when someone bumps the pin.

### 2. Pick the preset

The list file you choose decides which presets install the package. `presets/<name>.json` holds the mapping.

| File | work | personal | homelab |
|---|:-:|:-:|:-:|
| `apt_common.txt` (headless-safe only) | yes | yes | yes |
| `apt_k8s.txt` | yes | yes | yes |
| `apt_desktop.txt` (GUI) | yes | yes | no |
| `apt_rust.txt` | no | yes | yes |
| `apt_work.txt` | yes | no | no |
| `apt_personal.txt` | no | yes | no |
| `apt_homelab.txt` | no | no | yes |
| `flatpak_desktop.txt` | yes | yes | no |
| `flatpak_work.txt` | yes | no | no |
| `github_bins.txt` | yes | yes | yes |

Put a package in the narrowest file that covers every machine that needs it. A package only one employer needs goes in the overlay's `packages/<preset>_extra.txt`, never here. A new machine type is a new `presets/<name>.json`, not a code change.

### 3. How versions are tracked

| Mechanism | Version source | Bump |
|---|---|---|
| apt | the archive or repo | `dfctl apply --upgrade` runs `apt-get dist-upgrade` |
| Flatpak | Flathub | `dfctl apply --upgrade` runs `flatpak update` |
| `github_bins.txt` | `<user>/<repo> <version> <deb-filename>` | edit the line; it installs when the package is absent or older than the pin, never a downgrade |
| `release_specs.json` | `version` field, with `url` and `cache_key` templates over `{version}` | edit `version`, update the URL in `checksums.txt`, run `mise run pin <url substring>` |
| vendor installer | URL and digest in `packages/checksums.txt` | `mise run pin`, then review the diff: it trusts whatever the URL serves now |
| `mise.toml` (repo dev tools only) | pinned in the file | Renovate |

Renovate bumps the version and URL together for lazydocker, istioctl, AWS CLI, zizmor and mcp-grafana, but cannot recompute the digest. Run `mise run pin <url substring>` on its PR. It bumps no version for zoom or JetBrains Toolbox, and bumps Antigravity's `PINNED_BUILD` without that build's `checksums.txt` URL, so those need the same follow-up edits by hand. `pin` only updates a URL already listed in `checksums.txt`, so change the URL there first after a hand bump. The nightly `pin-check` workflow reports digest drift.

### 4. Checklist per mechanism

**apt:** add the name to the list file. For a third-party repo, add the `.sources` file under `apt/`, a `KEYS` entry (the key never downloads without it) and a `SOURCE_FILES` entry first. A source whose repo is unreachable is skipped with its packages, and the next run retries.

**Flatpak:** add `flatpak:<app-id>` to `flatpak_desktop.txt` or `flatpak_work.txt`. Apt skips these entries. Apps that need the host (D-Bus, sandbox-hostile) stay on apt, `.deb` or a vendor script.

**GitHub `.deb`:** add `<user>/<repo> <version> <deb-filename>` to `github_bins.txt`. The dpkg package name must equal the repo name, which removal uses, and start the `.deb` filename, which the install check uses. If the repo name differs, removal silently skips it.

**Pinned release:**
1. Add the line to `packages/release_specs.json`. A `binary` field installs that binary as the user into `~/.local/bin` (no sudo, user stage); kind `binary` is a raw, non-archived download installed under that name.
2. Add a line for the resolved URL to `packages/checksums.txt` with a placeholder 64-hex digest (`pin` never adds a URL), then run `mise run pin <url substring>` to record the real digest.
3. Name the package in the `apt_*.txt` file that selects its presets.
4. Give it a `binary` field so it installs at user level. Only a root-owned package (a `.deb` like zoom, whose install is keyed in code) installs with sudo: list it in `PRIVILEGED_PACKAGES` in `release_installers.py` so the system stage and `system_check` cover it. The exempt-module table in `tests/test_bin_policy.py` changes only if the sudo call lives in a new module.

**Vendor installer:** record the installer URL and digest in `checksums.txt`, write the install step, add the name to `CUSTOM_INSTALL_PACKAGES`, and record an undo entry in the rollback log.

### 5. Removal

Dropping a name from a list uninstalls it after confirmation, but only for some mechanisms:

- apt and Flatpak entries are removed. apt removal is simulation-checked and never cascades or autoremoves.
- A GitHub `.deb` is removed through dpkg, and its undo only warns to reinstall by hand. zoom, which is `.deb`-backed, is removed the same way when dpkg reports it installed.
- Every other vendor-script entry is reported once and never removed.

`--prune` approves removals without a prompt, and `--dry-run` only lists them. Keep these rules intact in any change that touches package planning.
