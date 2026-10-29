from pathlib import Path
from types import SimpleNamespace

from dotfiles_setup import rollback, tools
from dotfiles_setup.log import Logger


class Machine:
    def __init__(self, failing=()):
        self.commands = []
        self.failing = tuple(failing)

    def __call__(self, argv, **kwargs):
        self.commands.append((list(argv), kwargs.get("cwd")))
        failed = any(argv[: len(p)] == list(p) for p in self.failing)
        return SimpleNamespace(returncode=1 if failed else 0, stdout="", stderr="")

    def argvs(self):
        return [argv for argv, _ in self.commands]


def context(tmp_path, machine, private=None):
    t = tools.Tooling(Logger(dry_run=False, verbosity=1), tmp_path / "home", run=machine)
    log = rollback.RollbackLog(tmp_path / "rollback.log")
    return rollback.RollbackContext(t, log, tmp_path / "repo", private)


def test_tracking_appends_and_a_dry_run_records_nothing(tmp_path):
    log = rollback.RollbackLog(tmp_path / "log")
    log.track("STOW_HOME:a", dry_run=False)
    log.track("STOW_HOME:b", dry_run=False)
    log.track("STOW_HOME:c", dry_run=True)
    assert log.entries() == ["STOW_HOME:a", "STOW_HOME:b"]


def test_a_missing_log_has_no_entries(tmp_path):
    log = rollback.RollbackLog(tmp_path / "missing")
    assert log.entries() == []
    assert not log.has_entries()


def test_entries_are_undone_newest_first_and_the_log_is_removed(tmp_path):
    machine = Machine()
    ctx = context(tmp_path, machine, private=tmp_path / "private")
    for entry in ("STOW_HOME:a", "STOW_PRIVATE:b", "STOW_ROOT:c", "DOCKER_GROUP:ali", "FILE_CREATED:/etc/x.sources"):
        ctx.log.track(entry, dry_run=False)
    rollback.perform_rollback(ctx)
    assert machine.commands == [
        (["sudo", "rm", "-f", "/etc/x.sources"], None),
        (["sudo", "gpasswd", "-d", "ali", "docker"], None),
        (["sudo", "stow", "--delete", "--target=/", "c"], tmp_path / "repo"),
        (["stow", "--delete", f"--target={tmp_path / 'home'}", "b"], tmp_path / "private"),
        (["stow", "--delete", f"--target={tmp_path / 'home'}", "a"], tmp_path / "repo"),
    ]
    assert not ctx.log.path.exists()


def test_an_unstowed_private_package_is_restowed(tmp_path):
    machine = Machine()
    ctx = context(tmp_path, machine, private=tmp_path / "private")
    ctx.log.track("UNSTOW_PRIVATE:claude-collibra", dry_run=False)
    rollback.perform_rollback(ctx)
    assert machine.commands == [
        (["stow", "--restow", "--no-folding", f"--target={tmp_path / 'home'}", "claude-collibra"], tmp_path / "private"),
    ]


def test_a_backed_up_file_is_restored_to_its_original_name(tmp_path):
    machine = Machine()
    ctx = context(tmp_path, machine)
    backup = tmp_path / "hosts.backup-20260101"
    backup.write_text("old")
    ctx.log.track(f"FILE_BACKUP:{backup}", dry_run=False)
    rollback.perform_rollback(ctx)
    assert machine.argvs() == [["sudo", "mv", str(backup), str(tmp_path / "hosts")]]


def test_a_backup_kept_elsewhere_is_restored_to_the_recorded_original(tmp_path):
    machine = Machine()
    ctx = context(tmp_path, machine)
    backup = tmp_path / "backups" / "docker.sources.backup-1"
    backup.parent.mkdir()
    backup.write_text("old")
    original = tmp_path / "etc" / "docker.sources"
    ctx.log.track(f"FILE_BACKUP:{backup}|{original}", dry_run=False)
    rollback.perform_rollback(ctx)
    assert machine.argvs() == [["sudo", "mv", str(backup), str(original)]]


def test_a_missing_backup_file_is_skipped(tmp_path):
    machine = Machine()
    ctx = context(tmp_path, machine)
    ctx.log.track(f"FILE_BACKUP:{tmp_path}/gone.backup-1", dry_run=False)
    rollback.perform_rollback(ctx)
    assert machine.commands == []


def test_a_failing_undo_does_not_stop_the_rest(tmp_path):
    machine = Machine(failing=[("stow",)])
    ctx = context(tmp_path, machine)
    ctx.log.track("DOCKER_GROUP:ali", dry_run=False)
    ctx.log.track("STOW_HOME:a", dry_run=False)
    rollback.perform_rollback(ctx)
    assert len(machine.commands) == 2
    assert not ctx.log.path.exists()


def test_an_unknown_action_is_reported_and_skipped(tmp_path):
    machine = Machine()
    ctx = context(tmp_path, machine)
    ctx.log.track("MYSTERY:x", dry_run=False)
    rollback.perform_rollback(ctx)
    assert machine.commands == []


def test_rolling_back_an_empty_log_does_nothing(tmp_path):
    machine = Machine()
    rollback.perform_rollback(context(tmp_path, machine))
    assert machine.commands == []


def test_a_confirmed_prompt_rolls_back(tmp_path):
    machine = Machine()
    ctx = context(tmp_path, machine)
    ctx.log.track("DOCKER_GROUP:ali", dry_run=False)
    rollback.offer_rollback(ctx, interactive=True, ask=lambda prompt: "Y")
    assert len(machine.commands) == 1


def test_a_declined_prompt_keeps_the_log(tmp_path):
    machine = Machine()
    ctx = context(tmp_path, machine)
    ctx.log.track("DOCKER_GROUP:ali", dry_run=False)
    rollback.offer_rollback(ctx, interactive=True, ask=lambda prompt: "")
    assert machine.commands == []
    assert ctx.log.path.exists()


def test_a_non_interactive_run_never_prompts(tmp_path):
    ctx = context(tmp_path, Machine())
    ctx.log.track("DOCKER_GROUP:ali", dry_run=False)

    def refuse(prompt):
        raise AssertionError(prompt)

    rollback.offer_rollback(ctx, interactive=False, ask=refuse)
    assert ctx.log.path.exists()


def test_nothing_is_offered_without_a_log(tmp_path):
    def refuse(prompt):
        raise AssertionError(prompt)

    rollback.offer_rollback(context(tmp_path, Machine()), interactive=True, ask=refuse)


def test_the_default_log_lives_in_home(tmp_path):
    assert rollback.RollbackLog.for_home(Path(tmp_path)).path == tmp_path / ".dotfiles-setup-rollback.log"
