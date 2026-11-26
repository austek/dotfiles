import json
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest
from dotfiles_setup.doctor_cache import cache_path, write_cache
from dotfiles_setup.findings import Finding

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)


def _stored(path):
    return json.loads(path.read_text())


def test_path_follows_xdg_state_home(tmp_path):
    assert cache_path({"XDG_STATE_HOME": str(tmp_path)}, Path("/h")) == tmp_path / "dotfiles" / "doctor.json"


def test_path_defaults_under_the_home_directory():
    assert cache_path({}, Path("/h")) == Path("/h/.local/state/dotfiles/doctor.json")


def test_cache_holds_ids_and_text_only(tmp_path):
    path = tmp_path / "dotfiles" / "doctor.json"
    write_cache(path, {"c": (Finding("c", "t", commands=(("a",),), advice="x"),)}, NOW, merge=False)
    assert _stored(path) == {"v": 1, "checkedAt": int(NOW.timestamp()), "findings": [{"check": "c", "text": "t"}]}


def test_named_run_replaces_only_its_own_checks(tmp_path):
    path = tmp_path / "dotfiles" / "doctor.json"
    write_cache(path, {"a": (Finding("a", "old"),), "b": (Finding("b", "keep"),)}, NOW, merge=False)
    write_cache(path, {"a": ()}, NOW, merge=True)
    assert [f["check"] for f in _stored(path)["findings"]] == ["b"]


def test_full_run_replaces_everything(tmp_path):
    path = tmp_path / "dotfiles" / "doctor.json"
    write_cache(path, {"b": (Finding("b", "stale"),)}, NOW, merge=False)
    write_cache(path, {"a": ()}, NOW, merge=False)
    assert _stored(path)["findings"] == []


def test_corrupt_cache_is_treated_as_empty_on_merge(tmp_path):
    path = tmp_path / "dotfiles" / "doctor.json"
    path.parent.mkdir(parents=True)
    path.write_text("{nope")
    write_cache(path, {"a": (Finding("a", "t"),)}, NOW, merge=True)
    assert len(_stored(path)["findings"]) == 1


@pytest.mark.parametrize("document", [
    '{"findings": [1]}',
    '{"findings": "abc"}',
    '{"findings": [{"check": ["x"], "text": "t"}]}',
    '{"findings": [{"check": "keep"}]}',
    "[]",
])
def test_wrong_shaped_cache_is_treated_as_empty_on_merge(tmp_path, document):
    path = tmp_path / "dotfiles" / "doctor.json"
    path.parent.mkdir(parents=True)
    path.write_text(document)
    write_cache(path, {"b": (Finding("b", "t"),)}, NOW, merge=True)
    assert _stored(path)["findings"] == [{"check": "b", "text": "t"}]


def test_retained_entries_keep_only_check_and_text(tmp_path):
    path = tmp_path / "dotfiles" / "doctor.json"
    path.parent.mkdir(parents=True)
    extra = {"check": "keep", "text": "t", "commands": [["rm", "x"]], "advice": "y"}
    path.write_text(json.dumps({"v": 1, "checkedAt": 0, "findings": [extra]}))
    write_cache(path, {"b": ()}, NOW, merge=True)
    assert _stored(path)["findings"] == [{"check": "keep", "text": "t"}]


def test_missing_cache_is_treated_as_empty_on_merge(tmp_path):
    path = tmp_path / "dotfiles" / "doctor.json"
    write_cache(path, {"a": (Finding("a", "t"),)}, NOW, merge=True)
    assert len(_stored(path)["findings"]) == 1


def test_file_and_directory_are_owner_only(tmp_path):
    path = tmp_path / "dotfiles" / "doctor.json"
    write_cache(path, {}, NOW, merge=False)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
