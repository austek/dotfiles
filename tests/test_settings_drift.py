import json

from dotfiles_setup import settings_drift


def _record(state_dir, settings):
    settings_drift.record_baseline(state_dir, settings_drift.render(settings))


def test_render_is_indented_json_with_trailing_newline():
    assert settings_drift.render({"a": 1}) == '{\n  "a": 1\n}\n'


def test_no_drift_without_a_baseline(tmp_path):
    target = tmp_path / "settings.json"
    target.write_text('{"hand": "edited"}')
    assert settings_drift.drift_diff(target, tmp_path / "state") == ""


def test_no_drift_when_target_is_missing(tmp_path):
    _record(tmp_path / "state", {"a": 1})
    assert settings_drift.drift_diff(tmp_path / "settings.json", tmp_path / "state") == ""


def test_no_drift_when_target_is_a_symlink(tmp_path):
    _record(tmp_path / "state", {"a": 1})
    real = tmp_path / "real.json"
    real.write_text('{"a": 2}')
    target = tmp_path / "settings.json"
    target.symlink_to(real)
    assert settings_drift.drift_diff(target, tmp_path / "state") == ""


def test_no_drift_when_target_matches_the_baseline(tmp_path):
    _record(tmp_path / "state", {"a": 1})
    target = tmp_path / "settings.json"
    target.write_text(settings_drift.render({"a": 1}))
    assert settings_drift.drift_diff(target, tmp_path / "state") == ""


def test_key_order_alone_is_not_drift(tmp_path):
    _record(tmp_path / "state", {"a": 1, "b": 2})
    target = tmp_path / "settings.json"
    target.write_text(json.dumps({"b": 2, "a": 1}))
    assert settings_drift.drift_diff(target, tmp_path / "state") == ""


def test_diff_shows_an_added_and_a_removed_key(tmp_path):
    _record(tmp_path / "state", {"a": 1, "gone": True})
    target = tmp_path / "settings.json"
    target.write_text(json.dumps({"a": 1, "new": True}))
    diff = settings_drift.drift_diff(target, tmp_path / "state")
    assert '-  "gone": true' in diff
    assert '+  "new": true' in diff


def test_invalid_json_in_target_is_reported_as_drift(tmp_path):
    _record(tmp_path / "state", {"a": 1})
    target = tmp_path / "settings.json"
    target.write_text("{not json")
    assert "{not json" in settings_drift.drift_diff(target, tmp_path / "state")