"""Session defaults: Zsh as the login shell and Ghostty as the default terminal."""
from __future__ import annotations

import getpass
import os
import shutil
from pathlib import Path

from dotfiles_setup.tooling import Tooling, dry_run_all

GHOSTTY_ENTRY_ID = "com.mitchellh.ghostty.desktop"
TERMINAL_SCHEMA = "org.gnome.desktop.default-applications.terminal"


def change_shell(t: Tooling) -> None:
    t.logger.step("Step 8: Changing default shell to Zsh...")
    zsh = shutil.which("zsh") or "/usr/bin/zsh"
    if os.environ.get("SHELL") == zsh:
        t.logger.info(f"Default shell is already {zsh}. Skipping.")
    elif not dry_run_all(
        t, f"Would change default shell to {zsh} using chsh", "Would require logout/login for changes to take effect",
    ):
        if t.run(["sudo", "usermod", "-s", zsh, getpass.getuser()]).returncode == 0:
            t.logger.success(f"Default shell changed to {zsh}.")
            t.logger.warn("You will need to log out and log back in for this change to take effect.")
        else:
            t.logger.error(f"Failed to change default shell. Please run 'chsh -s {zsh}' manually.")


def _set_alternative(t: Tooling, ghostty: str) -> None:
    install = ["sudo", "update-alternatives", "--install", "/usr/bin/x-terminal-emulator", "x-terminal-emulator", ghostty, "50"]
    select = ["sudo", "update-alternatives", "--set", "x-terminal-emulator", ghostty]
    if t.run(install).returncode == 0 and t.run(select).returncode == 0:
        t.logger.success("Default terminal set to Ghostty.")
    else:
        t.logger.error("Failed to set default terminal. Please run 'sudo update-alternatives --config x-terminal-emulator' manually.")


def _prefer_ghostty(listing: Path) -> bool:
    others = [line for line in listing.read_text().splitlines() if line != GHOSTTY_ENTRY_ID] if listing.is_file() else []
    try:
        listing.write_text("".join(f"{line}\n" for line in [GHOSTTY_ENTRY_ID, *others]))
    except OSError:
        return False
    return True


def _update_terminal_lists(t: Tooling, config_dir: Path) -> None:
    # xdg-terminal-exec reads the desktop-prefixed lists before the generic one, so patch both.
    config_dir.mkdir(parents=True, exist_ok=True)
    generic = config_dir / "xdg-terminals.list"
    updated = 0
    for listing in [generic, *sorted(config_dir.glob("*-xdg-terminals.list"))]:
        if _prefer_ghostty(listing):
            updated += 1
        else:
            t.logger.error(f"Failed to update {listing}. Please add '{GHOSTTY_ENTRY_ID}' as its first line manually.")
    if updated:
        t.logger.success(f"Ghostty set as preferred terminal in {updated} xdg-terminal-exec list(s).")


def _set_gnome_terminal(t: Tooling, ghostty: str) -> None:
    # gsd-media-keys reads this deprecated key directly whenever it holds a non-default override.
    if shutil.which("gsettings") is None:
        return
    first = t.run(["gsettings", "set", TERMINAL_SCHEMA, "exec", ghostty]).returncode == 0
    if first and t.run(["gsettings", "set", TERMINAL_SCHEMA, "exec-arg", "-e"]).returncode == 0:
        t.logger.success("Ghostty set as the GNOME Ctrl+Alt+T terminal.")
    else:
        t.logger.error(f"Failed to set the GNOME default terminal key. Please run 'gsettings set {TERMINAL_SCHEMA} exec {ghostty}' manually.")


def set_default_terminal(t: Tooling) -> None:
    t.logger.step("Step 9: Setting default terminal to Ghostty...")
    ghostty = shutil.which("ghostty")
    if ghostty is None:
        t.logger.warn("Ghostty is not installed. Skipping default terminal configuration.")
        return
    config_dir = Path(os.environ.get("XDG_CONFIG_HOME") or t.home / ".config")
    if dry_run_all(
        t, f"Would register and set x-terminal-emulator alternative to {ghostty}",
        f"Would set {GHOSTTY_ENTRY_ID} as the preferred entry in {config_dir / 'xdg-terminals.list'}",
    ):
        return
    _set_alternative(t, ghostty)
    _update_terminal_lists(t, config_dir)
    _set_gnome_terminal(t, ghostty)
