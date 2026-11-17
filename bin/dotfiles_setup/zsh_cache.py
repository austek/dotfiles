"""Drops zsh's completion dump when the completion files change, so a renamed or added completer takes effect.

compinit rebuilds its dump only when the number of completion files changes, so a rename that keeps the
count equal leaves the old registrations in place.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from dotfiles_setup.tooling import Tooling, dry_run_all

# The fpath directories ~/.zshrc and oh-my-zsh have set up by the time compinit runs.
COMPLETION_DIRS = (".config/zsh/completions", ".oh-my-zsh/custom/completions")
FINGERPRINT_FILE = ".local/state/dotfiles/zsh-completions.sha256"
DUMP_GLOB = ".zcompdump*"


def _header(path: Path) -> str:
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            return handle.readline().strip()
    except OSError:
        return ""


def fingerprint(home: Path) -> str:
    """Hashes the name and first line (normally the #compdef header) of every completer in the watched directories."""
    digest = hashlib.sha256()
    for directory in COMPLETION_DIRS:
        for path in sorted((home / directory).glob("_*")):
            digest.update(f"{directory}/{path.name}\0{_header(path)}\0".encode())
    return digest.hexdigest()


def _remembered(store: Path) -> str:
    try:
        return store.read_text().strip()
    except (OSError, UnicodeDecodeError):
        return ""


def _remove_dumps(t: Tooling) -> int | None:
    """Returns how many dump files it removed, or None after a failure."""
    removed = 0
    for path in sorted(t.home.glob(DUMP_GLOB)):
        try:
            if not path.is_symlink() and path.is_dir():
                continue
            path.unlink()
        except OSError as error:
            t.logger.warn(f"Could not remove {path} ({error}); delete ~/.zcompdump* by hand so new completions load.")
            return None
        removed += 1
    return removed


def _remember(t: Tooling, store: Path, current: str) -> bool:
    try:
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(current + "\n")
    except OSError as error:
        t.logger.warn(f"Could not record the zsh completion fingerprint in {store} ({error}); the cache is dropped again next run.")
        return False
    return True


def refresh_zsh_completion_cache(t: Tooling) -> None:
    """Removes ~/.zcompdump* on the first run and once per change to the completers. It never fails the install: a problem only warns."""
    store = t.home / FINGERPRINT_FILE
    current = fingerprint(t.home)
    if _remembered(store) == current or dry_run_all(t, "Would remove ~/.zcompdump* so zsh rebuilds its completion cache"):
        return
    removed = _remove_dumps(t)
    if removed is not None and _remember(t, store, current) and removed:
        t.logger.info("Removed zsh's completion cache; open a new shell to load the new completions.")
