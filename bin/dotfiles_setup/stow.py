"""Stows the dotfiles packages into $HOME, plus the optional private overlay.
With force, files that block stow are first moved to a timestamped backup."""
from __future__ import annotations

import re
import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from dotfiles_setup.rollback import RollbackLog
from dotfiles_setup.tooling import Tooling, dry_run_all

UNFOLD_LIMIT = 1000
FOLD_PACKAGES = frozenset({"gradle"})
_CONFLICT_PATTERNS = (
    re.compile(r"^.*existing target is (?:neither a link nor a directory|not owned by stow): (.+)$"),
    re.compile(r"^.*cannot stow .* over existing target (.+) since .*$"),
)
_REGEX_SPECIALS = re.compile(r"[.\[\\*^$()+?{}|]")


@dataclass(frozen=True)
class StowPlan:
    t: Tooling
    dotfiles_dir: Path
    private_root: Path | None
    force: bool
    backup_root: Path
    stamp: str
    changes: RollbackLog


def stow_regex_escape(path: str) -> str:
    """Stow reads --ignore and --override values as regexes, so a literal '.' would match any character."""
    return _REGEX_SPECIALS.sub(lambda match: "\\" + match.group(0), path)


def package_lines(stow_file: Path) -> list[str]:
    lines = (line.strip() for line in stow_file.read_text().splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def _conflicts(output: str) -> list[str]:
    found = {m.group(1) for line in output.splitlines() for p in _CONFLICT_PATTERNS if (m := p.match(line))}
    return sorted(found)


def _is_safe_relative(rel: str) -> bool:
    parts = rel.split("/")
    return not rel.startswith("/") and ".." not in parts


def _stage_conflict(plan: StowPlan, stage: Path, home_real: Path, rel: str) -> None:
    logger = plan.t.logger
    if not _is_safe_relative(rel):
        logger.warn(f"Not backing up suspicious path: {rel}")
        return
    source = plan.t.home / rel
    if not (source.exists() or source.is_symlink()):
        return
    try:
        parent_real = (plan.t.home / Path(rel).parent).resolve(strict=True)
    except OSError:
        return
    if parent_real != home_real and home_real not in parent_real.parents:
        logger.warn(f"Not backing up path outside HOME: {rel}")
        return
    (stage / rel).parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(stage / rel))
    logger.warn(f"Stow conflict: backing up ~/{rel}")


def stage_stow_conflicts(plan: StowPlan, stage: Path, args: Sequence[str], cwd: Path) -> None:
    """Moves each conflicting path under stage, keeping it relative to $HOME so restoring is a plain move."""
    home_real = plan.t.home.resolve(strict=True)
    simulated = plan.t.run(["stow", "--simulate", *args], capture_output=True, text=True, cwd=cwd)
    for rel in _conflicts((simulated.stdout or "") + (simulated.stderr or "")):
        _stage_conflict(plan, stage, home_real, rel)


def finalize_stow_backup(plan: StowPlan, stage: Path) -> bool:
    """Never removes stage unless every copy step succeeded: it holds the only copy of the originals."""
    logger = plan.t.logger
    if not any(stage.iterdir()):
        stage.rmdir()
        return True
    try:
        plan.backup_root.mkdir(parents=True, exist_ok=True)
        backup_dir = Path(tempfile.mkdtemp(prefix=f"{plan.stamp}.", dir=plan.backup_root))
        shutil.copytree(stage, backup_dir, symlinks=True, dirs_exist_ok=True)
    except OSError as error:
        logger.error(f"Could not back up to {plan.backup_root} ({error}); conflicting files remain staged in {stage}.")
        return False
    shutil.rmtree(stage)
    logger.warn(f"Backed up conflicting files to {backup_dir}")
    return True


def stow_with_backup(plan: StowPlan, args: Sequence[str], cwd: Path) -> bool:
    stage = Path(tempfile.mkdtemp(prefix=".stow-backup.", dir=plan.t.home)) if plan.force else None
    if stage is not None:
        stage_stow_conflicts(plan, stage, args, cwd)
    if plan.t.logger.quiet_run(["stow", *args], run=plan.t.run, cwd=cwd).returncode != 0:
        if stage is not None:
            finalize_stow_backup(plan, stage)
        plan.t.logger.error(
            "Stow failed. If files block it, re-run with --force (dotfiles-setup) or --force-stow (setup.sh) "
            "to back them up and stow anyway."
        )
        return False
    return stage is None or finalize_stow_backup(plan, stage)


def _first_package_file(package_dir: Path) -> Path | None:
    candidates = sorted(p for p in package_dir.rglob("*") if p.is_file() or p.is_symlink())
    return candidates[0] if candidates else None


def stow_pkg_is_linked(root: Path, pkg: str, target: Path) -> bool:
    first = _first_package_file(root / pkg)
    if first is None:
        return False
    linked = target / first.relative_to(root / pkg)
    return linked.exists() and linked.resolve() == first.resolve()


def pkgs_not_yet_linked(root: Path, target: Path, packages: Sequence[str]) -> list[str]:
    return [pkg for pkg in packages if not stow_pkg_is_linked(root, pkg, target)]


def _regular_files(directory: Path) -> list[Path]:
    return sorted(p for p in directory.rglob("*") if p.is_file() and not p.is_symlink())


def private_override_ignores(plan: StowPlan) -> list[str]:
    """Paths the private overlay overrides must be excluded from the public stow, or the two fight over them every rerun."""
    stow_file = plan.private_root / ".stow-packages" if plan.private_root else None
    if stow_file is None or not stow_file.is_file():
        return []
    ignores = []
    for pkg in package_lines(stow_file):
        if not (plan.dotfiles_dir / pkg).is_dir():
            continue
        for file in _regular_files(plan.private_root / pkg):
            rel = file.relative_to(plan.private_root / pkg)
            if (plan.dotfiles_dir / pkg / rel).is_file():
                ignores.append(f"--ignore={stow_regex_escape(str(rel))}")
    return ignores


def _file_count_over_limit(package_dir: Path) -> bool:
    count = 0
    for path in package_dir.rglob("*"):
        if path.is_file() or path.is_symlink():
            count += 1
            if count > UNFOLD_LIMIT:
                return True
    return False


def _track_new(plan: StowPlan, action: str, packages: Sequence[str]) -> None:
    for pkg in packages:
        plan.changes.track(f"{action}:{pkg}", dry_run=False)


def stow_common_to_home(plan: StowPlan, ignores: list[str]) -> bool:
    logger, home = plan.t.logger, plan.t.home
    stow_file = plan.dotfiles_dir / ".stow-packages"
    if not stow_file.is_file():
        logger.warn(f".stow-packages file not found. Skipping {home} stow.")
        return True
    logger.info(f"Reading {home} packages from .stow-packages...")
    packages = package_lines(stow_file)
    if not packages:
        logger.warn("No packages listed in .stow-packages. Skipping.")
        return True
    folded = [p for p in packages if p in FOLD_PACKAGES]
    nofold = [p for p in packages if p not in FOLD_PACKAGES]
    for pkg in nofold:
        if _file_count_over_limit(plan.dotfiles_dir / pkg):
            logger.error(f"Package '{pkg}' holds more than {UNFOLD_LIMIT} files; refusing to stow it unfolded.")
            logger.error("Add it to FOLD_PACKAGES in stow.py, or drop it from .stow-packages.")
            return False
    logger.info(f"Stowing common packages to {home}: {' '.join(packages)}...")
    if dry_run_all(plan.t, f"Would stow (unfolded) to {home}: {' '.join(nofold) or 'none'}",
                   f"Would stow (folded) to {home}: {' '.join(folded) or 'none'}"):
        return True
    newly_stowed = pkgs_not_yet_linked(plan.dotfiles_dir, home, packages)
    common = [*ignores, f"--target={home}", "--verbose=1"]
    if nofold and not stow_with_backup(plan, ["--restow", "--no-folding", *common, *nofold], plan.dotfiles_dir):
        return False
    if folded and not stow_with_backup(plan, ["--restow", *common, *folded], plan.dotfiles_dir):
        return False
    _track_new(plan, "STOW_HOME", newly_stowed)
    logger.success(f"All {home} packages stowed.")
    return True


def clear_public_symlink_at_private_path(plan: StowPlan, pkg: str, file: Path) -> None:
    """stow --override cannot make one source dir win over a symlink another already placed, so clear it first."""
    target = plan.t.home / file.relative_to(plan.private_root / pkg)
    if target.is_symlink() and str(target.resolve()).startswith(f"{plan.dotfiles_dir}/"):
        target.unlink()


def stow_private_to_home(plan: StowPlan) -> bool:
    if plan.private_root is None:
        return True
    logger, home = plan.t.logger, plan.t.home
    stow_file = plan.private_root / ".stow-packages"
    if not stow_file.is_file():
        logger.info(f"No .stow-packages in the private overlay ({plan.private_root}). Skipping private stow.")
        return True
    packages = package_lines(stow_file)
    if not packages:
        return True
    logger.info(f"Stowing private-overlay packages to {home}: {' '.join(packages)}...")
    if dry_run_all(plan.t, f"Would stow (unfolded, from {plan.private_root}, overriding any public file at the "
                           f"same path) to {home}: {' '.join(packages)}"):
        return True
    newly_stowed = pkgs_not_yet_linked(plan.private_root, home, packages)
    for pkg in packages:
        for file in _regular_files(plan.private_root / pkg):
            clear_public_symlink_at_private_path(plan, pkg, file)
    args = ["--restow", "--no-folding", f"--target={home}", "--verbose=1", *packages]
    if not stow_with_backup(plan, args, plan.private_root):
        return False
    _track_new(plan, "STOW_PRIVATE", newly_stowed)
    logger.success("All private-overlay packages stowed.")
    return True


def configure_git_hooks(plan: StowPlan) -> bool:
    plan.t.logger.info("Configuring pre-commit git hooks...")
    if dry_run_all(plan.t, "Would set core.hooksPath to .githooks"):
        return True
    result = plan.t.run(["git", "config", "--local", "core.hooksPath", ".githooks"], cwd=plan.dotfiles_dir)
    if result.returncode != 0:
        plan.t.logger.error("Failed to set core.hooksPath to .githooks.")
        return False
    plan.t.logger.success("Git hooks path set to .githooks.")
    return True


def configure_dotfiles(plan: StowPlan) -> bool:
    plan.t.logger.step("Step 7: Configuring dotfiles...")
    ignores = private_override_ignores(plan)
    return (
        stow_common_to_home(plan, ignores)
        and stow_private_to_home(plan)
        and configure_git_hooks(plan)
    )
