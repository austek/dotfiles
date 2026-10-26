from types import SimpleNamespace

import pytest
from dotfiles_setup import apt_sources as aps
from dotfiles_setup import system_steps as ss
from dotfiles_setup import tools
from dotfiles_setup.log import Logger
from dotfiles_setup.rollback import RollbackLog


class Machine:
    def __init__(self, failing=(), outputs=None):
        self.commands = []
        self.inputs = {}
        self.failing = tuple(failing)
        self.outputs = outputs or {}

    def __call__(self, argv, **kwargs):
        self.commands.append(list(argv))
        if kwargs.get("input") is not None:
            self.inputs[tuple(argv)] = kwargs["input"]
        failed = any(argv[: len(p)] == list(p) for p in self.failing)
        out = next((v for p, v in self.outputs.items() if argv[: len(p)] == list(p)), "")
        return SimpleNamespace(returncode=1 if failed else 0, stdout=out, stderr="")

    def ran(self, *prefix):
        return any(c[: len(prefix)] == list(prefix) for c in self.commands)

    def input_for(self, *argv):
        return self.inputs[tuple(argv)]


def make(tmp_path, machine, packages=(), dry_run=False, fetch=lambda url: f"KEY:{url}", fetch_bytes=None):
    fetch_bytes = fetch_bytes or (lambda url: f"KEY:{url}".encode())
    t = tools.Tooling(Logger(dry_run=dry_run, verbosity=1), tmp_path, run=machine, fetch=fetch, fetch_bytes=fetch_bytes)
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    return ss.SystemContext(t, repo, frozenset(packages), RollbackLog(tmp_path / "rollback.log"))


def test_each_selected_package_gets_its_signing_key_dearmored_into_its_keyring(tmp_path):
    machine = Machine()
    ctx = make(tmp_path, machine, packages=["google-chrome-stable", "code", "docker-ce", "gh"])
    assert aps.download_apt_gpg_keys(ctx)
    for destination, url in (
        ("/usr/share/keyrings/google-chrome-keyring.gpg", "https://dl.google.com/linux/linux_signing_key.pub"),
        ("/usr/share/keyrings/packages.microsoft.gpg", "https://packages.microsoft.com/keys/microsoft.asc"),
        ("/usr/share/keyrings/docker.gpg", "https://download.docker.com/linux/ubuntu/gpg"),
        ("/usr/share/keyrings/githubcli-archive-keyring.gpg",
         "https://cli.github.com/packages/githubcli-archive-keyring.gpg"),
    ):
        assert machine.input_for("sudo", "gpg", "--dearmor", "--yes", "-o", destination) == f"KEY:{url}".encode()


def test_1password_writes_its_key_to_both_keyrings(tmp_path):
    machine = Machine()
    assert aps.download_apt_gpg_keys(make(tmp_path, machine, packages=["1password"]))
    assert machine.ran("sudo", "gpg", "--dearmor", "--yes", "-o", "/usr/share/keyrings/1password-archive-keyring.gpg")
    assert machine.ran("sudo", "gpg", "--dearmor", "--yes", "-o", "/usr/share/debsig/keyrings/AC2D62742012EA22/debsig.gpg")


def test_prefix_matched_packages_select_their_keys(tmp_path):
    machine = Machine()
    ctx = make(tmp_path, machine, packages=["pgadmin4-desktop", "postgresql-16", "teleport-ent"])
    assert aps.download_apt_gpg_keys(ctx)
    destinations = {c[-1] for c in machine.commands if c[:3] == ["sudo", "gpg", "--dearmor"]}
    assert destinations == {
        "/usr/share/keyrings/pgadmin4-archive-keyring.gpg",
        "/usr/share/keyrings/postgresql-archive-keyring.gpg",
        "/usr/share/keyrings/teleport-archive-keyring.gpg",
    }


def test_unselected_packages_download_no_keys(tmp_path):
    machine = Machine()
    assert aps.download_apt_gpg_keys(make(tmp_path, machine, packages=["vim"]))
    assert machine.commands == []


def test_a_key_download_failure_stops_the_step(tmp_path):
    def broken(url):
        raise OSError("offline")

    assert not aps.download_apt_gpg_keys(make(tmp_path, Machine(), packages=["gh"], fetch_bytes=broken))


def test_a_binary_keyring_is_passed_to_gpg_unchanged(tmp_path):
    keyring = bytes(range(256))
    machine = Machine()
    ctx = make(tmp_path, machine, packages=["gh"], fetch_bytes=lambda url: keyring)
    assert aps.download_apt_gpg_keys(ctx)
    destination = "/usr/share/keyrings/githubcli-archive-keyring.gpg"
    assert machine.input_for("sudo", "gpg", "--dearmor", "--yes", "-o", destination) == keyring


def test_a_failed_gpg_dearmor_stops_the_step(tmp_path):
    machine = Machine(failing=[("sudo", "gpg")])
    assert not aps.download_apt_gpg_keys(make(tmp_path, machine, packages=["gh"]))


def test_keys_are_not_downloaded_in_a_dry_run(tmp_path):
    machine = Machine()
    assert aps.download_apt_gpg_keys(make(tmp_path, machine, packages=["gh", "1password"], dry_run=True))
    assert machine.commands == []


def test_firefox_gets_its_ppa_and_a_pin(tmp_path):
    machine = Machine()
    assert aps.configure_apt_ppas(make(tmp_path, machine, packages=["firefox"]))
    assert machine.ran("sudo", "add-apt-repository", "-y", "ppa:mozillateam/ppa")
    pin = machine.input_for("sudo", "tee", "/etc/apt/preferences.d/mozillateam-firefox-pin")
    assert pin == "\nPackage: firefox*\nPin: release o=LP-PPA-mozillateam\nPin-Priority: 1001\n\n"


def test_ghostty_gets_its_ppa(tmp_path):
    machine = Machine()
    assert aps.configure_apt_ppas(make(tmp_path, machine, packages=["ghostty"]))
    assert machine.ran("sudo", "add-apt-repository", "-y", "ppa:mkasberg/ghostty-ubuntu")


def test_1password_gets_its_debsig_policy(tmp_path):
    machine = Machine()
    assert aps.configure_apt_ppas(make(tmp_path, machine, packages=["1password"]))
    policy = machine.input_for("sudo", "tee", "/etc/debsig/policies/AC2D62742012EA22/1password.pol")
    assert policy == "KEY:https://downloads.1password.com/linux/debian/debsig/1password.pol"


def test_a_failed_ppa_add_stops_the_step(tmp_path):
    machine = Machine(failing=[("sudo", "add-apt-repository")])
    assert not aps.configure_apt_ppas(make(tmp_path, machine, packages=["ghostty"]))


def test_ppas_are_not_added_in_a_dry_run(tmp_path):
    machine = Machine()
    assert aps.configure_apt_ppas(make(tmp_path, machine, packages=["firefox", "ghostty", "1password"], dry_run=True))
    assert machine.commands == []


def test_unneeded_source_files_are_ignored_by_the_apt_stow(tmp_path):
    machine = Machine()
    ctx = make(tmp_path, machine, packages=["gh"])
    assert aps.stow_apt_source_files(ctx)
    argv = machine.commands[0]
    assert r"--ignore=1password\.sources$" in argv
    assert r"--ignore=vscode\.sources$" in argv
    assert not any("github-cli" in arg for arg in argv)
    assert argv[:4] == ["sudo", "stow", f"--dir={tmp_path / 'repo'}", "--restow"]
    assert ctx.changes.entries() == ["STOW_ROOT:apt"]


def test_stow_conflicts_are_backed_up_then_the_stow_is_retried(tmp_path, monkeypatch):
    monkeypatch.setattr(aps, "FS_ROOT", tmp_path / "fs")
    monkeypatch.setattr(aps, "STOW_BACKUP_ROOT", tmp_path / "backups")
    conflict = tmp_path / "fs/etc/apt/sources.list.d/docker.sources"
    conflict.parent.mkdir(parents=True)
    conflict.write_text("old")
    (tmp_path / "backups").mkdir()

    class Stowing(Machine):
        def __call__(self, argv, **kwargs):
            if argv[:2] == ["sudo", "stow"] and "--restow" in argv and not self.commands_with("--restow"):
                self.commands.append(list(argv))
                return SimpleNamespace(returncode=1, stdout="", stderr="conflict")
            if "--no" in argv:
                self.commands.append(list(argv))
                line = "  * existing target is neither a link nor a directory: etc/apt/sources.list.d/docker.sources"
                return SimpleNamespace(returncode=1, stdout="", stderr=line)
            if argv[:2] == ["sudo", "mv"]:
                self.commands.append(list(argv))
                conflict.rename(argv[3])
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            return super().__call__(argv, **kwargs)

        def commands_with(self, flag):
            return [c for c in self.commands if flag in c]

    machine = Stowing()
    ctx = make(tmp_path, machine, packages=["gh"])
    assert aps.stow_apt_source_files(ctx)
    entries = ctx.changes.entries()
    assert entries[0].startswith(f"FILE_BACKUP:{tmp_path / 'backups'}/docker.sources.backup-")
    assert entries[0].endswith(f"|{conflict}")
    assert entries[1] == "STOW_ROOT:apt"
    assert not conflict.exists()
    assert len([c for c in machine.commands if "--restow" in c]) == 2


def test_a_stow_failure_with_no_recognisable_conflict_is_not_tracked(tmp_path):
    machine = Machine(failing=[("sudo", "stow")])
    ctx = make(tmp_path, machine, packages=["gh"])
    assert aps.stow_apt_source_files(ctx)
    assert ctx.changes.entries() == []


def test_a_failing_backup_move_stops_the_step(tmp_path, monkeypatch):
    monkeypatch.setattr(aps, "FS_ROOT", tmp_path / "fs")
    conflict = tmp_path / "fs/etc/x.sources"
    conflict.parent.mkdir(parents=True)
    conflict.write_text("old")
    line = "  * existing target is neither a link nor a directory: etc/x.sources"
    machine = Machine(failing=[("sudo", "stow"), ("sudo", "mv")], outputs={("sudo", "stow"): line})
    assert not aps.stow_apt_source_files(make(tmp_path, machine, packages=["gh"]))


def test_conflict_paths_are_read_from_both_stow_message_styles():
    text = (
        "  * existing target is not owned by stow: etc/a.sources\n"
        "  * cannot stow x over existing target etc/b.sources since neither a link nor a directory\n"
        "unrelated line"
    )
    assert aps._conflicting_files(text) == ["etc/a.sources", "etc/b.sources"]


def test_the_codename_comes_from_os_release(tmp_path):
    release = tmp_path / "os-release"
    release.write_text('NAME="Ubuntu"\nVERSION_CODENAME=resolute\n')
    assert aps.detect_ubuntu_codename(make(tmp_path, Machine()), release) == "resolute"


def test_a_quoted_codename_loses_its_quotes(tmp_path):
    release = tmp_path / "os-release"
    release.write_text('VERSION_CODENAME="plucky"\n')
    assert aps.detect_ubuntu_codename(make(tmp_path, Machine()), release) == "plucky"


@pytest.mark.parametrize("content", [None, 'NAME="Ubuntu"\n', "VERSION_CODENAME=\n"])
def test_a_missing_codename_falls_back_to_noble(tmp_path, content, capsys):
    release = tmp_path / "os-release"
    if content is not None:
        release.write_text(content)
    assert aps.detect_ubuntu_codename(make(tmp_path, Machine()), release) == "noble"
    assert "defaulting to 'noble'" in capsys.readouterr().out


def write_templates(ctx):
    templates = ctx.dotfiles_dir / "apt-templates"
    templates.mkdir()
    for name in ("docker", "pgadmin4", "postgresql", "teleport"):
        (templates / f"{name}.sources.template").write_text(f"Suites: @CODENAME@\n# {name}\n")


def test_selected_templates_are_rendered_for_the_host_codename_and_tracked(tmp_path):
    machine = Machine()
    ctx = make(tmp_path, machine, packages=["docker-ce", "postgresql-16"])
    write_templates(ctx)
    release = tmp_path / "os-release"
    release.write_text("VERSION_CODENAME=noble\n")
    sources = tmp_path / "sources.list.d"
    assert aps.generate_templated_apt_sources(ctx, sources, release)
    assert machine.input_for("sudo", "tee", str(sources / "docker.sources")) == "Suites: noble\n# docker\n"
    assert machine.input_for("sudo", "tee", str(sources / "postgresql.sources")) == "Suites: noble\n# postgresql\n"
    assert ctx.changes.entries() == [f"FILE_CREATED:{sources}/docker.sources", f"FILE_CREATED:{sources}/postgresql.sources"]


def test_deselected_rendered_sources_are_removed_but_hand_made_ones_are_kept(tmp_path):
    sources = tmp_path / "sources.list.d"
    sources.mkdir()
    (sources / "pgadmin4.sources").write_text(f"{aps.RENDERED_MARKER}\nTypes: deb\n")
    (sources / "docker.sources").write_text(f"{aps.RENDERED_MARKER}\nTypes: deb\n")
    (sources / "postgresql.sources").write_text("Types: deb\n")
    machine = Machine()
    ctx = make(tmp_path, machine, packages=["docker-ce"])
    write_templates(ctx)
    aps.generate_templated_apt_sources(ctx, sources, tmp_path / "os-release")
    assert machine.ran("sudo", "rm", "-f", str(sources / "pgadmin4.sources"))
    assert not machine.ran("sudo", "rm", "-f", str(sources / "postgresql.sources"))
    assert not machine.ran("sudo", "rm", "-f", str(sources / "docker.sources"))


def test_nothing_is_rendered_when_no_templated_package_is_selected(tmp_path):
    machine = Machine()
    ctx = make(tmp_path, machine, packages=["vim"])
    assert aps.generate_templated_apt_sources(ctx, tmp_path / "s", tmp_path / "os-release")
    assert machine.commands == []


def test_the_whole_step_runs_directories_keys_ppas_stow_then_templates(tmp_path):
    machine = Machine()
    ctx = make(tmp_path, machine, packages=["gh"])
    assert aps.configure_apt_sources(ctx, tmp_path / "s", tmp_path / "os-release")
    kinds = [c[1] for c in machine.commands]
    assert kinds[0] == "mkdir"
    assert kinds.index("gpg") < kinds.index("stow")


def test_the_whole_step_stops_when_a_part_fails(tmp_path):
    machine = Machine(failing=[("sudo", "mkdir")])
    assert not aps.configure_apt_sources(make(tmp_path, machine, packages=["gh"]))
    assert len(machine.commands) == 1


def test_the_step_changes_nothing_in_a_dry_run(tmp_path):
    machine = Machine()
    ctx = make(tmp_path, machine, packages=["gh", "docker-ce", "firefox"], dry_run=True)
    assert aps.configure_apt_sources(ctx)
    assert machine.commands == []
