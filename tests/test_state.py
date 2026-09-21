from dotfiles_setup.state import MachineState, load_state, save_state


def _sample_state(**overrides):
    fields = {
        "preset_name": "work",
        "backend": "apt",
        "package_file": "/home/user/.config/dotfiles/packages/work.txt",
        "applied_package_names": ("curl", "zsh"),
        "overlay_root": None,
        "created_at": "2026-09-10T00:00:00",
        "updated_at": "2026-09-10T00:00:00",
    }
    fields.update(overrides)
    return MachineState(**fields)


def test_load_state_returns_none_when_file_missing(tmp_path):
    assert load_state(tmp_path / "state.json") is None


def test_save_then_load_round_trips(tmp_path):
    state_file = tmp_path / "nested" / "state.json"
    state = _sample_state()
    save_state(state, state_file)
    assert load_state(state_file) == state


def test_save_state_creates_parent_directories(tmp_path):
    state_file = tmp_path / "a" / "b" / "state.json"
    save_state(_sample_state(), state_file)
    assert state_file.is_file()


def test_round_trips_optional_overlay_root_as_none(tmp_path):
    state_file = tmp_path / "state.json"
    save_state(_sample_state(overlay_root=None), state_file)
    loaded = load_state(state_file)
    assert loaded.overlay_root is None


def test_round_trips_optional_overlay_root_when_set(tmp_path):
    state_file = tmp_path / "state.json"
    save_state(
        _sample_state(overlay_root="/home/user/.dotfiles-private"),
        state_file,
    )
    loaded = load_state(state_file)
    assert loaded.overlay_root == "/home/user/.dotfiles-private"


def test_applied_package_names_round_trips_as_a_tuple(tmp_path):
    """JSON has no tuple type — a naive MachineState(**json.loads(...)) would
    load applied_package_names back as a list, breaking dataclass equality
    against the tuple the caller saved. load_state must convert it back."""
    state_file = tmp_path / "state.json"
    save_state(_sample_state(applied_package_names=("bat", "curl", "zsh")), state_file)
    loaded = load_state(state_file)
    assert loaded.applied_package_names == ("bat", "curl", "zsh")
    assert isinstance(loaded.applied_package_names, tuple)
