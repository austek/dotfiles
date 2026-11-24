"""Stows the dotfiles packages into $HOME, plus the optional overlay.
With force, files that block stow are first moved to a timestamped backup."""
from __future__ import annotations

import os
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
    re.compile(r"existing target is (?:neither a link nor a directory|not owned by stow): (.+)$"),
    re.compile(r"cannot stow \S+ over existing target (\S+) since "),
)
STOW_PACKAGES_FILE = ".stow-packages"
VERBOSE_FLAG = "--verbose=1"
_REGEX_SPECIALS = re.compile(r"[.\[\\*^$()+?{}|]")


@dataclass(frozen=True)
class StowPlan:
    t: Tooling
    dotfiles_dir: Path
    overlay_root: Path | None
    force: bool
    backup_root: Path
    stamp: str
    changes: RollbackLog
    preset: str = ""


def stow_regex_escape(path: str) -> str:
    """Stow reads --ignore values as regexes, so a literal '.' would match any character."""
    return _REGEX_SPECIALS.sub(lambda match: "\\" + match.group(0), path)


def package_lines(stow_file: Path) -> list[str]:
    lines = (line.strip() for line in stow_file.read_text().splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def overlay_packages(plan: StowPlan) -> list[str]:
    """Packages for every preset (`.stow-packages`), then those scoped to this one (`.stow-packages.<preset>`)."""
    if plan.overlay_root is None:
        return []
    files = [plan.overlay_root / STOW_PACKAGES_FILE, plan.overlay_root / f"{STOW_PACKAGES_FILE}.{plan.preset}"]
    return list(dict.fromkeys(name for file in files if file.is_file() for name in package_lines(file)))


def other_preset_packages(plan: StowPlan) -> list[str]:
    """Packages scoped to other presets only; a package this preset also lists is never returned."""
    if plan.overlay_root is None:
        return []
    own = f"{STOW_PACKAGES_FILE}.{plan.preset}"
    scoped = sorted(f for f in plan.overlay_root.glob(f"{STOW_PACKAGES_FILE}.*") if f.name != own and f.is_file())
    keep = set(overlay_packages(plan))
    return [name for name in dict.fromkeys(n for f in scoped for n in package_lines(f)) if name not in keep]


def _conflicts(output: str) -> list[str]:
    found = {m.group(1) for line in output.splitlines() for p in _CONFLICT_PATTERNS if (m := p.search(line))}
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
            "Stow failed. If files block it, re-run with --force to back them up and stow anyway."
        )
        return False
    return stage is None or finalize_stow_backup(plan, stage)


def _package_files(package_dir: Path) -> list[Path]:
    return sorted(p for p in package_dir.rglob("*") if p.is_file() or p.is_symlink())


def _links_to(link: Path, source: Path) -> bool:
    return os.path.lexists(link) and os.path.realpath(link) == os.path.realpath(source)


def stow_pkg_is_linked(root: Path, pkg: str, target: Path) -> bool:
    files = _package_files(root / pkg)
    return bool(files) and _links_to(target / files[0].relative_to(root / pkg), files[0])


def stow_pkg_has_links(root: Path, pkg: str, target: Path) -> bool:
    return any(_links_to(target / file.relative_to(root / pkg), file) for file in _package_files(root / pkg))


def pkgs_not_yet_linked(root: Path, target: Path, packages: Sequence[str]) -> list[str]:
    return [pkg for pkg in packages if not stow_pkg_is_linked(root, pkg, target)]


def _regular_files(directory: Path) -> list[Path]:
    return sorted(p for p in directory.rglob("*") if p.is_file() and not p.is_symlink())


_IGNORED_ANYWHERE = re.compile(r"RCS|.+,v|CVS|\.#.+|\.cvsignore|\.svn|_darcs|\.hg|\.git|\.gitignore|\.gitmodules|.+~|\#.*\#")
_IGNORED_TOP_LEVEL = re.compile(r"README.*|LICENSE.*|COPYING")


LOCAL_IGNORE_FILE = ".stow-local-ignore"


GLOBAL_IGNORE_FILE = ".stow-global-ignore"


def _strip_comment(line: str) -> str:
    """Stow's `s/\\s+#.+//` in linear time: cut at the first `#` that follows whitespace and precedes more text."""
    for i, char in enumerate(line):
        if char == "#" and 0 < i < len(line) - 1 and line[i - 1].isspace():
            return line[:i].rstrip()
    return line


def _ignore_patterns(path: Path) -> list[str]:
    """Stow's reading of an ignore file: no blank or comment lines, no trailing ` # comment`, `\\#` is a literal `#`."""
    lines = (_strip_comment(line.strip()) for line in path.read_text().splitlines())
    return [line.replace("\\#", "#") for line in lines if line and not line.startswith("#")]


def _local_ignores(package_dir: Path, home: Path) -> list[str] | None:
    """The package's `.stow-local-ignore`, else `~/.stow-global-ignore`; either replaces stow's default list."""
    for path in (package_dir / LOCAL_IGNORE_FILE, home / GLOBAL_IGNORE_FILE):
        if path.is_file():
            return _ignore_patterns(path)
    return None


def _matches_local(pattern: str, rel: Path) -> bool:
    """A pattern with a slash matches at path-component boundaries; any other must fully match one component."""
    try:
        if "/" in pattern:
            return re.search(rf"(?:^|/)(?:{pattern})(?:/|$)", "/" + rel.as_posix()) is not None
        return any(re.fullmatch(pattern, part) for part in rel.parts)
    except re.error:
        return False


def _stow_ignores(rel: Path, local: list[str] | None = None) -> bool:
    """Whether stow never links `rel`: its default ignore list, or the package's own list when it has one."""
    if rel.name == LOCAL_IGNORE_FILE:
        return True
    if local is not None:
        return any(_matches_local(pattern, rel) for pattern in local)
    return any(_IGNORED_ANYWHERE.fullmatch(part) for part in rel.parts) or bool(_IGNORED_TOP_LEVEL.fullmatch(rel.parts[0]))


def _entry_lacks_link(entry: Path, dest: Path, rel: Path, local: list[str] | None, skip: set[Path]) -> bool:
    """One entry is linked whole; below a real directory stow links the children, so descend there only."""
    if rel in skip or _stow_ignores(rel, local) or _links_to(dest, entry):
        return False
    if entry.is_dir() and not entry.is_symlink() and dest.is_dir() and not dest.is_symlink():
        return any(_entry_lacks_link(c, dest / c.name, rel / c.name, local, skip) for c in sorted(entry.iterdir()))
    return True


def _lacks_folded_links(root: Path, pkg: str, target: Path, local: list[str] | None, skip: set[Path]) -> bool:
    entries = sorted((root / pkg).iterdir())
    return any(_entry_lacks_link(e, target / e.name, Path(e.name), local, skip) for e in entries)


def _lacks_links(root: Path, pkg: str, target: Path, skip: set[Path]) -> bool:
    local = _local_ignores(root / pkg, target)
    if pkg in FOLD_PACKAGES and (root / pkg).is_dir():
        return _lacks_folded_links(root, pkg, target, local, skip)
    for file in _package_files(root / pkg):
        rel = file.relative_to(root / pkg)
        if rel not in skip and not _stow_ignores(rel, local) and not _links_to(target / rel, file):
            return True
    return False


def _overridden_files(plan: StowPlan, pkg: str) -> set[Path]:
    """Package-relative paths of the files the overlay replaces; the public stow ignores them, so the plan skips them too."""
    if plan.overlay_root is None or pkg not in overlay_packages(plan):
        return set()
    own = _regular_files(plan.overlay_root / pkg)
    rels = {file.relative_to(plan.overlay_root / pkg) for file in own}
    return {rel for rel in rels if (plan.dotfiles_dir / pkg / rel).is_file()}


def pending_links(plan: StowPlan) -> tuple[str, ...]:
    """What `configure_dotfiles` would link or unlink, from the files on disk alone; changes nothing."""
    home, stow_file = plan.t.home, plan.dotfiles_dir / STOW_PACKAGES_FILE
    public = package_lines(stow_file) if stow_file.is_file() else []
    return (
        *(f"link {p}" for p in public if _lacks_links(plan.dotfiles_dir, p, home, _overridden_files(plan, p))),
        *(f"link {p} (overlay)" for p in overlay_packages(plan) if _lacks_links(plan.overlay_root, p, home, set())),
        *(f"unlink {p}" for p in other_preset_packages(plan) if stow_pkg_has_links(plan.overlay_root, p, home)),
    )


def overlay_override_ignores(plan: StowPlan) -> list[str]:
    """Paths the overlay overrides must be excluded from the public stow, or the two fight over them every rerun."""
    ignores = []
    for pkg in overlay_packages(plan):
        if not (plan.dotfiles_dir / pkg).is_dir():
            continue
        for file in _regular_files(plan.overlay_root / pkg):
            rel = file.relative_to(plan.overlay_root / pkg)
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


def _stow_tracked(plan: StowPlan, action: str, root: Path, args: Sequence[str], packages: Sequence[str]) -> bool:
    """Records the packages this call linked, even when it fails afterwards, so a rollback can unlink them."""
    pending = pkgs_not_yet_linked(root, plan.t.home, packages)
    stowed = stow_with_backup(plan, args, root)
    for pkg in pending:
        if stow_pkg_is_linked(root, pkg, plan.t.home):
            plan.changes.track(f"{action}:{pkg}", dry_run=False)
    return stowed


def stow_common_to_home(plan: StowPlan, ignores: list[str]) -> bool:
    logger, home = plan.t.logger, plan.t.home
    stow_file = plan.dotfiles_dir / STOW_PACKAGES_FILE
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
    common = [*ignores, f"--target={home}", VERBOSE_FLAG]
    groups = ((nofold, ["--restow", "--no-folding"]), (folded, ["--restow"]))
    for group, flags in groups:
        if group and not _stow_tracked(plan, "STOW_HOME", plan.dotfiles_dir, [*flags, *common, *group], group):
            return False
    logger.success(f"All {home} packages stowed.")
    return True


def clear_public_symlink_at_overlay_path(plan: StowPlan, pkg: str, file: Path) -> None:
    """stow --override cannot make one source dir win over a symlink another already placed, so clear it first."""
    target = plan.t.home / file.relative_to(plan.overlay_root / pkg)
    if target.is_symlink() and str(target.resolve()).startswith(f"{plan.dotfiles_dir}/"):
        target.unlink()


def unstow_other_preset_packages(plan: StowPlan) -> None:
    """Removes links a previous install under another preset left; a failure only warns."""
    packages = other_preset_packages(plan)
    if not packages:
        return
    logger, home = plan.t.logger, plan.t.home
    if dry_run_all(plan.t, f"Would unstow overlay packages scoped to other presets from {home}: {' '.join(packages)}"):
        return
    linked = [pkg for pkg in packages if stow_pkg_has_links(plan.overlay_root, pkg, home)]
    args = ["stow", "--delete", f"--target={home}", VERBOSE_FLAG, *packages]
    if logger.quiet_run(args, run=plan.t.run, cwd=plan.overlay_root).returncode != 0:
        logger.warn(f"Could not unstow {' '.join(packages)}; remove their links from {home} by hand.")
        return
    for pkg in linked:
        plan.changes.track(f"UNSTOW_PRIVATE:{pkg}", dry_run=False)


def stow_overlay_to_home(plan: StowPlan) -> bool:
    if plan.overlay_root is None:
        return True
    packages = overlay_packages(plan)
    if not packages:
        plan.t.logger.info(f"No overlay packages for preset '{plan.preset}' ({plan.overlay_root}). Skipping overlay stow.")
        return True
    return _stow_overlay_packages(plan, packages)


def _stow_overlay_packages(plan: StowPlan, packages: list[str]) -> bool:
    logger, home = plan.t.logger, plan.t.home
    logger.info(f"Stowing overlay packages to {home}: {' '.join(packages)}...")
    if dry_run_all(plan.t, f"Would stow (unfolded, from {plan.overlay_root}, overriding any public file at the "
                           f"same path) to {home}: {' '.join(packages)}"):
        return True
    for pkg in packages:
        for file in _regular_files(plan.overlay_root / pkg):
            clear_public_symlink_at_overlay_path(plan, pkg, file)
    args = ["--restow", "--no-folding", f"--target={home}", VERBOSE_FLAG, *packages]
    if not _stow_tracked(plan, "STOW_PRIVATE", plan.overlay_root, args, packages):
        return False
    logger.success("All overlay packages stowed.")
    return True


def configure_git_hooks(plan: StowPlan) -> bool:
    plan.t.logger.info("Configuring pre-commit git hooks...")
    if not (plan.dotfiles_dir / ".git").exists():
        plan.t.logger.info("The dotfiles directory is not a git checkout. Skipping the hooks path.")
        return True
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
    unstow_other_preset_packages(plan)
    ignores = overlay_override_ignores(plan)
    return (
        stow_common_to_home(plan, ignores)
        and stow_overlay_to_home(plan)
        and configure_git_hooks(plan)
    )
