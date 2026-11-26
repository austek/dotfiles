"""Runs the doctor checks and prints, caches and fixes their findings."""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from dotfiles_setup import state
from dotfiles_setup.doctor_cache import cache_path, write_cache
from dotfiles_setup.doctor_checks import CHECKS, CheckContext
from dotfiles_setup.env import Env
from dotfiles_setup.findings import CheckOutcome, Finding
from dotfiles_setup.log import Logger
from dotfiles_setup.plan_confirm import DECLINED_EXIT_CODE, NEEDS_YES_EXIT_CODE, PROMPT
from dotfiles_setup.tooling import Tooling

EXIT_FINDINGS = 1
EXIT_UNKNOWN_CHECK = 2


@dataclass(frozen=True)
class Report:
    outcomes: dict[str, CheckOutcome]

    @property
    def findings(self) -> tuple[Finding, ...]:
        return tuple(f for outcome in self.outcomes.values() for f in outcome.findings)


def _run_one(name: str, ctx: CheckContext) -> CheckOutcome:
    try:
        return CHECKS[name](ctx)
    except Exception as error:  # noqa: BLE001
        return CheckOutcome((Finding(name, f"check {name} crashed: {error}"),))


def run_checks(ctx: CheckContext, names: Sequence[str]) -> Report:
    selected = [name for name in CHECKS if not names or name in names]
    return Report({name: _run_one(name, ctx) for name in selected})


def _render_finding(finding: Finding, emit: Callable[[str], None]) -> None:
    emit(f"! {finding.text}")
    for argv in finding.commands:
        emit(f"  fix: {shlex.join(argv)}")
    if finding.advice:
        emit(f"  {finding.advice}")


def render(report: Report, *, emit: Callable[[str], None], emit_skipped: Callable[[str], None]) -> None:
    for name, outcome in report.outcomes.items():
        if outcome.skipped:
            emit_skipped(f"skipped {name}: {outcome.skipped}")
        for finding in outcome.findings:
            _render_finding(finding, emit)


def hint_line(findings: Sequence[Finding]) -> str | None:
    if not findings:
        return None
    total, fixable = len(findings), sum(f.fixable for f in findings)
    noun = "problem" if total == 1 else "problems"
    if fixable == 0:
        return f"{total} {noun} found, none fixable by `dfctl doctor fix`. Run `dfctl doctor` for details."
    detail = f", {fixable} of {total} fixable" if fixable < total else ""
    return f"{total} {noun} found{detail}. Run `dfctl doctor` for details, `dfctl doctor fix` to apply the fixes."


def build_context(logger: Logger, env: Env) -> CheckContext:
    saved = state.load_state(state.state_file(env.state_dir))
    packages = None if saved is None else tuple(saved.applied_package_names)
    return CheckContext(Tooling(logger, env.home, run=env.run), packages)


def _store(logger: Logger, env: Env, report: Report, *, merge: bool) -> None:
    results = {name: o.findings for name, o in report.outcomes.items() if o.skipped is None}
    try:
        write_cache(cache_path(os.environ, env.home), results, env.clock(), merge=merge)
    except OSError as error:
        logger.warn(f"Could not write the doctor cache: {error}")


def _print_report(logger: Logger, report: Report, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps({"findings": [f.to_dict() for f in report.findings]}, indent=2))
        return
    render(report, emit=logger.say, emit_skipped=logger.say)
    logger.say(hint_line(report.findings) or "No problems found.")


def _has_unknown(logger: Logger, names: Sequence[str]) -> bool:
    unknown = [name for name in names if name not in CHECKS]
    if unknown:
        logger.error(f"No check named {', '.join(unknown)}; run `dfctl doctor --list-checks`.")
    return bool(unknown)


def run_doctor(args: argparse.Namespace, env: Env) -> int:
    logger = Logger(dry_run=args.dry_run, verbosity=args.verbosity)
    if args.list_checks:
        print("\n".join(CHECKS))
        return 0
    if _has_unknown(logger, args.names):
        return EXIT_UNKNOWN_CHECK
    report = run_checks(build_context(logger, env), args.names)
    _store(logger, env, report, merge=bool(args.names))
    _print_report(logger, report, as_json=args.json)
    return EXIT_FINDINGS if report.findings else 0


def _said_yes(ask: Callable[[str], str]) -> bool:
    try:
        return ask(PROMPT).strip().lower() in ("y", "yes")
    except EOFError:
        return False


def _confirmed(logger: Logger, *, yes: bool, interactive: bool, ask: Callable[[str], str]) -> int | None:
    if yes:
        return None
    if not interactive:
        logger.warn("The fixes change this machine; pass --yes to run them.")
        return NEEDS_YES_EXIT_CODE
    if _said_yes(ask):
        return None
    logger.warn("Declined; no fix ran.")
    return DECLINED_EXIT_CODE


def _run_fix(t: Tooling, finding: Finding) -> None:
    for argv in finding.commands:
        t.logger.info(f"Running: {shlex.join(argv)}")
        result = t.run(list(argv), capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if result.returncode != 0:
            reason = (result.stderr or result.stdout or "").strip()
            t.logger.warn(f"Could not run `{shlex.join(argv)}`: {reason}")
            return


def _finish(logger: Logger, env: Env, report: Report, names: Sequence[str]) -> int:
    _store(logger, env, report, merge=bool(names))
    render(report, emit=logger.say, emit_skipped=logger.say)
    logger.say(hint_line(report.findings) or "No problems found.")
    return EXIT_FINDINGS if report.findings else 0


def _fix_all(ctx: CheckContext, fixable: Sequence[Finding], stop: int | None) -> int | None:
    if stop is None:
        for finding in fixable:
            _run_fix(ctx.t, finding)
    return stop


def run_doctor_fix(
    args: argparse.Namespace, env: Env, *, interactive: bool, ask: Callable[[str], str] = input
) -> int:
    logger, names = Logger(dry_run=args.dry_run, verbosity=args.verbosity), args.names[1:]
    if _has_unknown(logger, names):
        return EXIT_UNKNOWN_CHECK
    ctx = build_context(logger, env)
    report = run_checks(ctx, names)
    fixable = [f for f in report.findings if f.fixable]
    if fixable:
        render(report, emit=logger.say, emit_skipped=logger.say)
        if logger.dry_run_notice(f"Would run {sum(len(f.commands) for f in fixable)} fix command(s)."):
            return 0
        stop = _fix_all(ctx, fixable, _confirmed(logger, yes=args.yes, interactive=interactive, ask=ask))
        if stop is not None:
            return stop
        report = run_checks(ctx, names)
    return _finish(logger, env, report, names)
