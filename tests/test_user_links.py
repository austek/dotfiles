import pytest
from dotfiles_setup import release_installers as ri
from dotfiles_setup import tools, user_links
from dotfiles_setup.log import Logger

JETBRAINS = ".local/share/JetBrains/Toolbox/bin/jetbrains-toolbox"
SONAR = ".local/share/sonarqube-cli/bin/sonar"


class Tracker:
    def __init__(self):
        self.entries = []

    def track(self, entry, *, dry_run):
        self.entries.append(entry)


def tooling(home, dry_run=False):
    return tools.Tooling(Logger(dry_run=dry_run, verbosity=1), home)


def real_tool(home, relative):
    path = home / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\x7fELF")
    return path


def user_bin(home):
    return home / ".local" / "bin"


@pytest.mark.parametrize(("package", "relative", "name"), [
    ("jetbrains-toolbox", JETBRAINS, "jetbrains-toolbox"),
    ("sonarqube-cli", SONAR, "sonar"),
])
def test_an_installed_tool_is_linked_into_the_user_bin_dir(tmp_path, package, relative, name):
    real = real_tool(tmp_path, relative)
    assert user_links.link_user_tools(tooling(tmp_path), {package}) is True
    assert (user_bin(tmp_path) / name).is_symlink()
    assert (user_bin(tmp_path) / name).resolve() == real.resolve()


def test_an_unwanted_tool_is_not_linked(tmp_path):
    real_tool(tmp_path, SONAR)
    user_links.link_user_tools(tooling(tmp_path), {"vim"})
    assert not user_bin(tmp_path).exists()


def test_a_tool_whose_installer_left_nothing_creates_no_link_and_no_directory(tmp_path):
    user_links.link_user_tools(tooling(tmp_path), {"sonarqube-cli", "jetbrains-toolbox"})
    assert not user_bin(tmp_path).exists()


def test_a_second_run_changes_nothing_and_tracks_nothing(tmp_path):
    real_tool(tmp_path, SONAR)
    user_links.link_user_tools(tooling(tmp_path), {"sonarqube-cli"}, Tracker())
    tracker = Tracker()
    assert user_links.link_user_tools(tooling(tmp_path), {"sonarqube-cli"}, tracker) is True
    assert tracker.entries == []
    assert [p.name for p in user_bin(tmp_path).iterdir()] == ["sonar"]


def test_a_stale_symlink_is_replaced_and_not_tracked(tmp_path):
    real = real_tool(tmp_path, SONAR)
    user_bin(tmp_path).mkdir(parents=True)
    (user_bin(tmp_path) / "sonar").symlink_to(tmp_path / "gone")
    tracker = Tracker()
    user_links.link_user_tools(tooling(tmp_path), {"sonarqube-cli"}, tracker)
    assert (user_bin(tmp_path) / "sonar").resolve() == real.resolve()
    assert tracker.entries == []


def test_a_regular_file_is_kept_and_reported_without_failing_the_step(tmp_path, capsys):
    real_tool(tmp_path, SONAR)
    user_bin(tmp_path).mkdir(parents=True)
    (user_bin(tmp_path) / "sonar").write_bytes(b"mine")
    tracker = Tracker()
    assert user_links.link_user_tools(tooling(tmp_path), {"sonarqube-cli"}, tracker) is True
    assert (user_bin(tmp_path) / "sonar").read_bytes() == b"mine"
    assert tracker.entries == []
    captured = capsys.readouterr()
    assert f"{user_bin(tmp_path) / 'sonar'} exists and is not a symlink" in captured.out + captured.err


def test_a_blocked_sonar_link_warns_what_sonar_on_path_is(tmp_path, capsys):
    real_tool(tmp_path, SONAR)
    user_bin(tmp_path).mkdir(parents=True)
    (user_bin(tmp_path) / "sonar").write_bytes(b"mine")
    user_links.link_user_tools(tooling(tmp_path), {"sonarqube-cli"})
    captured = capsys.readouterr()
    assert "`sonar` on PATH is not the SonarQube CLI" in captured.out + captured.err


def test_a_missing_bin_dir_warns_that_the_plugin_will_not_find_sonar(tmp_path, capsys):
    real_tool(tmp_path, SONAR)
    user_bin(tmp_path).symlink_to(tmp_path / "nowhere")
    user_links.link_user_tools(tooling(tmp_path), {"sonarqube-cli"})
    captured = capsys.readouterr()
    assert "`sonar` on PATH is not the SonarQube CLI" in captured.out + captured.err


def test_a_blocked_toolbox_link_names_its_own_consequence(tmp_path, capsys):
    real_tool(tmp_path, JETBRAINS)
    user_bin(tmp_path).mkdir(parents=True)
    (user_bin(tmp_path) / "jetbrains-toolbox").write_bytes(b"mine")
    user_links.link_user_tools(tooling(tmp_path), {"jetbrains-toolbox"})
    captured = capsys.readouterr()
    assert "`jetbrains-toolbox` on PATH is not the Toolbox launcher" in captured.out + captured.err


def test_every_linked_tool_has_a_consequence_sentence():
    assert {name for _, name, _ in user_links.USER_LINKS} == set(user_links.CONSEQUENCES)


def test_a_new_link_and_directory_are_tracked_for_rollback(tmp_path):
    real = real_tool(tmp_path, SONAR)
    tracker = Tracker()
    user_links.link_user_tools(tooling(tmp_path), {"sonarqube-cli"}, tracker)
    assert tracker.entries == [
        f"DIR_CREATED:{user_bin(tmp_path)}",
        f"LINK_INSTALLED:{real.parent}|{user_bin(tmp_path) / 'sonar'}",
    ]


def test_an_existing_directory_is_not_tracked_as_created(tmp_path):
    real_tool(tmp_path, SONAR)
    user_bin(tmp_path).mkdir(parents=True)
    tracker = Tracker()
    user_links.link_user_tools(tooling(tmp_path), {"sonarqube-cli"}, tracker)
    assert [e.split(":")[0] for e in tracker.entries] == ["LINK_INSTALLED"]


def test_a_dry_run_creates_nothing_and_says_what_it_would_link(tmp_path, capsys):
    real_tool(tmp_path, SONAR)
    tracker = Tracker()
    user_links.link_user_tools(tooling(tmp_path, dry_run=True), {"sonarqube-cli"}, tracker)
    assert not user_bin(tmp_path).exists()
    assert tracker.entries == []
    assert f"Would link {user_bin(tmp_path) / 'sonar'}" in capsys.readouterr().out


def test_an_uncreatable_directory_warns_and_does_not_fail_the_step(tmp_path, capsys):
    real_tool(tmp_path, SONAR)
    user_bin(tmp_path).parent.joinpath("bin").symlink_to(tmp_path / "nowhere")
    assert user_links.link_user_tools(tooling(tmp_path), {"sonarqube-cli"}) is True
    captured = capsys.readouterr()
    assert "Could not create" in captured.out + captured.err


def test_the_linked_tools_are_jetbrains_toolbox_and_sonar():
    assert [(package, name) for package, name, _ in user_links.USER_LINKS] == [
        ("jetbrains-toolbox", "jetbrains-toolbox"), ("sonarqube-cli", "sonar"),
    ]


def test_the_links_land_where_the_release_installer_resolver_says(tmp_path):
    real_tool(tmp_path, SONAR)
    user_links.link_user_tools(tooling(tmp_path), {"sonarqube-cli"})
    assert (ri.user_bin_dir(tooling(tmp_path)) / "sonar").is_symlink()
