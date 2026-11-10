"""Generates ~/.claude/settings.json and stops an install when it was edited by hand."""
from __future__ import annotations

import argparse
import stat
from datetime import datetime
from pathlib import Path
from typing import Any

from dotfiles_setup import fsutil, overlay, settings_drift
from dotfiles_setup.env import Env
from dotfiles_setup.log import Logger
from dotfiles_setup.presets import Preset

DRIFT_EXIT_CODE = 3
SETTINGS_FILE = "settings.json"
NEW_SETTINGS_MODE = 0o600


def _replace_settings_target(target: Path, rendered: str, now: datetime) -> None:
    existing = target.is_file() and not target.is_symlink()
    if existing and target.read_text(encoding="utf-8") == rendered:
        return
    mode = stat.S_IMODE(target.stat().st_mode) if existing else NEW_SETTINGS_MODE
    staged = fsutil.stage_text(target, rendered, mode)
    try:
        if existing:
            fsutil.keep_copy(target, target.with_name(f"{target.name}.bak-{now:%Y%m%d%H%M%S}"))
        fsutil.commit_staged(staged, target)
    except BaseException:
        staged.unlink(missing_ok=True)
        raise


def _merged_claude_settings(
    dotfiles_dir: Path, overlay_root: Path | None, preset: Preset, home: Path,
) -> dict[str, Any]:
    profile = dotfiles_dir / "claude-profiles" / preset.claude_settings if preset.claude_settings else None
    merged = overlay.load_preset_settings(
        dotfiles_dir / "claude" / ".claude" / SETTINGS_FILE, profile, overlay_root, preset.name,
    )
    return overlay.expand_home_in_env(merged, home)


def _write_claude_settings(logger: Logger, merged: dict[str, Any], env: Env) -> None:
    target = env.claude_home / SETTINGS_FILE
    if logger.dry_run_notice(f"Would generate {target}."):
        return
    env.claude_home.mkdir(parents=True, exist_ok=True)
    rendered = settings_drift.render(merged)
    _replace_settings_target(target, rendered, env.clock())
    settings_drift.record_baseline(env.state_dir, rendered)


def _settings_drift_exit_code(args: argparse.Namespace, logger: Logger, env: Env) -> int | None:
    target = env.claude_home / SETTINGS_FILE
    diff = settings_drift.drift_diff(target, env.state_dir)
    if not diff or args.accept_drift:
        return None
    logger.warn(f"{target} was edited since the last install:")
    print(diff, end="")
    if args.dry_run:
        logger.warn("A real install would stop here; pass --accept-drift to overwrite these edits.")
        return None
    logger.error(
        "Stopping before any change. Move the edits into claude/.claude/settings.json or the overlay's "
        "claude-settings/settings.json, or pass --accept-drift to overwrite them (the old file is kept as .bak)."
    )
    return DRIFT_EXIT_CODE
