"""Session defaults: Zsh as the login shell, Ghostty as the default terminal, IBus off Ctrl+Shift+U."""
from __future__ import annotations

import ast
import getpass
import os
import pwd
import re
import shutil
from pathlib import Path

from dotfiles_setup.tooling import Tooling, dry_run_all

GHOSTTY_ENTRY_ID = "com.mitchellh.ghostty.desktop"
LIST_LINE = re.compile(r"[\w.@+-]+\.desktop|#.*")
TERMINAL_SCHEMA = "org.gnome.desktop.default-applications.terminal"
IBUS_EMOJI_SCHEMA = "org.freedesktop.ibus.panel.emoji"
IBUS_UNICODE_KEY = "unicode-hotkey"
EMPTY_STRING_ARRAY = "@as []"


def _config_dir(home: Path) -> Path:
    """Returns XDG_CONFIG_HOME when it is an absolute path inside home, else ~/.config."""
    configured = Path(os.environ.get("XDG_CONFIG_HOME", ""))
    if configured.is_absolute() and configured.resolve().is_relative_to(home.resolve()):
        return configured.resolve()
    return home / ".config"


def shell_change_pending() -> bool:
    """Reads the passwd entry, which `usermod -s` updates at once; $SHELL only changes at the next login."""
    return pwd.getpwuid(os.getuid()).pw_shell != (shutil.which("zsh") or "/usr/bin/zsh")


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


def _kept_entries(listing: Path) -> list[str]:
    if not listing.is_file():
        return []
    lines = listing.read_text().splitlines()
    return [line for line in lines if line != GHOSTTY_ENTRY_ID and LIST_LINE.fullmatch(line)]


def _prefer_ghostty(listing: Path) -> bool:
    others = _kept_entries(listing)
    try:
        listing.write_text("".join(f"{line}\n" for line in [GHOSTTY_ENTRY_ID, *others]))
    except OSError:
        return False
    return True


def _update_terminal_lists(t: Tooling, config_dir: Path) -> None:
    # xdg-terminal-exec reads the desktop-prefixed lists before the generic one, so patch both.
    config_dir.mkdir(parents=True, exist_ok=True)
    names = ["xdg-terminals.list", *sorted(p.name for p in config_dir.glob("*-xdg-terminals.list"))]
    updated = 0
    for listing in (config_dir / os.path.basename(name) for name in names):
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
    config_dir = _config_dir(t.home)
    if dry_run_all(
        t, f"Would register and set x-terminal-emulator alternative to {ghostty}",
        f"Would set {GHOSTTY_ENTRY_ID} as the preferred entry in {config_dir / 'xdg-terminals.list'}",
    ):
        return
    _set_alternative(t, ghostty)
    _update_terminal_lists(t, config_dir)
    _set_gnome_terminal(t, ghostty)


def _is_ctrl_shift_u(binding: str) -> bool:
    modifiers = {m.lower() for m in re.findall(r"<(\w+)>", binding)}
    return modifiers in ({"control", "shift"}, {"primary", "shift"}) and binding.rsplit(">", 1)[-1].lower() == "u"


def _ibus_bindings(t: Tooling) -> list[str] | None:
    """Returns the bound accelerators, or None when the schema is missing or the value is not a string list."""
    probe = t.run(["gsettings", "get", IBUS_EMOJI_SCHEMA, IBUS_UNICODE_KEY], capture_output=True, text=True)
    text = (probe.stdout or "").strip().removeprefix("@as ")
    try:
        bindings = ast.literal_eval(text) if probe.returncode == 0 else None
    except (ValueError, SyntaxError):
        return None
    ok = isinstance(bindings, list) and all(isinstance(b, str) for b in bindings)
    return bindings if ok else None


def _bindings_literal(bindings: list[str]) -> str:
    return repr(bindings) if bindings else EMPTY_STRING_ARRAY


def disable_ibus_unicode_hotkey(t: Tooling) -> None:
    t.logger.step("Step 10: Freeing Ctrl+Shift+U from IBus Unicode entry...")
    if shutil.which("gsettings") is None:
        return
    bindings = _ibus_bindings(t)
    kept = [b for b in bindings or [] if not _is_ctrl_shift_u(b)]
    if bindings is None:
        t.logger.info("IBus Unicode hotkey not readable (schema missing or unexpected value). Skipping.")
    elif kept == bindings:
        t.logger.info("IBus Unicode hotkey does not use Ctrl+Shift+U. Skipping.")
    elif not dry_run_all(t, f"Would remove Ctrl+Shift+U from {IBUS_EMOJI_SCHEMA} {IBUS_UNICODE_KEY}"):
        literal = _bindings_literal(kept)
        if t.run(["gsettings", "set", IBUS_EMOJI_SCHEMA, IBUS_UNICODE_KEY, literal]).returncode == 0:
            t.logger.success("Removed Ctrl+Shift+U from the IBus Unicode hotkey; GTK apps may still use it for Unicode entry.")
        else:
            t.logger.error(f"Failed to update the IBus Unicode hotkey. Please run 'gsettings set {IBUS_EMOJI_SCHEMA} {IBUS_UNICODE_KEY} \"{literal}\"' manually.")
