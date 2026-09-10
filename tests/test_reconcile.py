from dotfiles_setup.reconcile import reconcile_package_file


def test_reconcile_creates_file_on_first_run(tmp_path):
    package_file = tmp_path / "packages" / "work.txt"
    added, changed = reconcile_package_file(package_file, ["zsh", "curl"], previous_names=None)
    assert changed is True
    assert added == ["curl", "zsh"]
    assert package_file.read_text() == "curl\nzsh\n"


def test_reconcile_noop_when_preset_unchanged(tmp_path):
    package_file = tmp_path / "work.txt"
    package_file.write_text("curl\nzsh\n")
    added, changed = reconcile_package_file(
        package_file, ["zsh", "curl"], previous_names=["curl", "zsh"]
    )
    assert added == []
    assert changed is False
    assert package_file.read_text() == "curl\nzsh\n"


def test_reconcile_appends_only_new_entries_when_preset_gains_a_package(tmp_path):
    package_file = tmp_path / "work.txt"
    package_file.write_text("curl\n# my own note\nzsh\nripgrep\n")  # ripgrep hand-added by user
    added, changed = reconcile_package_file(
        package_file, ["curl", "zsh", "bat"], previous_names=["curl", "zsh"]
    )
    assert added == ["bat"]
    assert changed is True
    text = package_file.read_text()
    assert "ripgrep" in text  # user's hand-added entry survives
    assert "bat" in text


def test_reconcile_does_not_reintroduce_a_user_removed_package(tmp_path):
    package_file = tmp_path / "work.txt"
    package_file.write_text("curl\n")  # user deleted zsh from the forked file
    added, changed = reconcile_package_file(
        package_file, ["curl", "zsh"], previous_names=["curl", "zsh"]
    )
    assert added == []
    assert changed is False
    assert "zsh" not in package_file.read_text()


def test_reconcile_does_not_reintroduce_user_removed_package_when_preset_changes_elsewhere(tmp_path):
    """Regression test for the bug an earlier version of this design had: a
    preset change unrelated to a user-deleted package (here, the preset
    drops 'bat') must not resurrect the package the user removed ('zsh')."""
    package_file = tmp_path / "work.txt"
    package_file.write_text("curl\nbat\n")  # user deleted zsh; preset still (for now) lists it
    added, _ = reconcile_package_file(
        package_file, ["curl", "zsh"], previous_names=["curl", "zsh", "bat"]
    )
    assert "zsh" not in added
    assert package_file.read_text() == "curl\nbat\n"
