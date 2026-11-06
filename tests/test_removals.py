from types import SimpleNamespace

from dotfiles_setup import removals
from dotfiles_setup.log import Logger
from dotfiles_setup.rollback import RollbackLog
from dotfiles_setup.system_steps import SystemContext
from dotfiles_setup.tooling import Tooling


class Machine:
    def __init__(self, simulations=None, failing=(), installed_apt=(), installed_flatpak=()):
        self.commands = []
        self.simulations = simulations or {}
        self.failing = tuple(failing)
        self.installed_apt = installed_apt
        self.installed_flatpak = set(installed_flatpak)

    def __call__(self, argv, **kwargs):
        self.commands.append(list(argv))
        if argv[:3] == ["apt-get", "-s", "remove"]:
            return SimpleNamespace(returncode=0, stdout=self.simulations.get(argv[-1], ""), stderr="")
        if argv[0] == "dpkg-query":
            listing = "".join(f"ii  {name}\n" for name in self.installed_apt)
            return SimpleNamespace(returncode=0, stdout=listing, stderr="")
        if argv[:3] == ["flatpak", "info", "--user"]:
            return SimpleNamespace(returncode=0 if argv[3] in self.installed_flatpak else 1, stdout="", stderr="")
        failed = any(argv[: len(p)] == list(p) for p in self.failing)
        return SimpleNamespace(returncode=1 if failed else 0, stdout="", stderr="")

    def ran(self, *prefix):
        return any(c[: len(prefix)] == list(prefix) for c in self.commands)


class Capture(Logger):
    def __init__(self):
        super().__init__(dry_run=False, verbosity=1)
        self.warnings = []

    def warn(self, message):
        self.warnings.append(message)


def tooling(tmp_path, machine, logger=None):
    return Tooling(logger or Logger(dry_run=False, verbosity=1), tmp_path, run=machine)


def system_context(tmp_path, machine, logger=None):
    log = RollbackLog(tmp_path / "rollback.log")
    return SystemContext(tooling(tmp_path, machine, logger), tmp_path, [], log)


def test_split_routes_by_prefix_and_custom():
    split = removals.split_removals(["vim", "flatpak:com.slack.Slack", "slack-desktop", "htop"])
    assert split == removals.Split(apt=("vim", "htop"), flatpak=("com.slack.Slack",), manual=("slack-desktop",))


def test_installed_only_filters_apt_and_flatpak(tmp_path):
    machine = Machine(installed_apt=["vim"], installed_flatpak=["com.a.A"])
    split = removals.Split(apt=("vim", "emacs"), flatpak=("com.a.A", "com.b.B"), manual=("x",))
    kept = removals.installed_only(tooling(tmp_path, machine), split)
    assert kept == removals.Split(apt=("vim",), flatpak=("com.a.A",), manual=("x",))


def test_remove_apt_runs_after_clean_simulation(tmp_path):
    machine = Machine(simulations={"slack-desktop": "Remv slack-desktop [4.0]\n"})
    ctx = system_context(tmp_path, machine)
    assert removals.remove_apt(ctx, ["slack-desktop"]) == ["slack-desktop"]
    assert machine.ran("sudo", "apt-get", "remove", "-y", "slack-desktop")
    assert not machine.ran("sudo", "apt-get", "autoremove")


def test_remove_apt_skips_when_simulation_cascades(tmp_path):
    machine = Machine(simulations={"slack-desktop": "Remv slack-desktop [4.0]\nRemv libfoo [1.0]\n"})
    logger = Capture()
    ctx = system_context(tmp_path, machine, logger)
    assert removals.remove_apt(ctx, ["slack-desktop"]) == []
    assert not machine.ran("sudo", "apt-get", "remove")
    assert any("libfoo" in warning for warning in logger.warnings)


def test_remove_apt_tracks_undo(tmp_path):
    machine = Machine(simulations={"vim": "Remv vim [1]\n"})
    ctx = system_context(tmp_path, machine)
    removals.remove_apt(ctx, ["vim"])
    assert ctx.changes.entries() == ["APT_REMOVED:vim"]


def test_failed_apt_removal_is_not_returned_and_does_not_stop_others(tmp_path):
    machine = Machine(
        simulations={"a": "Remv a\n", "b": "Remv b\n"},
        failing=[("sudo", "apt-get", "remove", "-y", "a")],
    )
    ctx = system_context(tmp_path, machine)
    assert removals.remove_apt(ctx, ["a", "b"]) == ["b"]
    assert ctx.changes.entries() == ["APT_REMOVED:b"]


def test_remove_flatpaks_tracks_undo(tmp_path):
    machine = Machine(failing=[("flatpak", "uninstall", "--user", "-y", "--noninteractive", "com.bad.Bad")])
    changes = RollbackLog(tmp_path / "rollback.log")
    removed = removals.remove_flatpaks(tooling(tmp_path, machine), changes, ["com.bad.Bad", "com.slack.Slack"])
    assert removed == ["com.slack.Slack"]
    assert machine.ran("flatpak", "uninstall", "--user", "-y", "--noninteractive", "com.slack.Slack")
    assert changes.entries() == ["FLATPAK_REMOVED:com.slack.Slack"]
