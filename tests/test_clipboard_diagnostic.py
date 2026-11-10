import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "clipboard-diagnostic.sh"
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None, reason="bash not installed")


def _stub(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(0o755)


def _run(tmp_path: Path, tools: dict[str, str], env: dict[str, str]):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub(bin_dir, "date", "echo 1700000000")
    (bin_dir / "cat").symlink_to(shutil.which("cat"))
    for name, body in tools.items():
        _stub(bin_dir, name, body)
    result = subprocess.run(
        [BASH, str(SCRIPT)], env={"PATH": str(bin_dir), **env}, capture_output=True, text=True, check=False,
    )
    return result


def _record(tmp_path: Path) -> str:
    return f'echo "$0 $*" > "{tmp_path}/used"; cat > "{tmp_path}/copied"'


def test_no_clipboard_tool_fails_and_says_so(tmp_path):
    result = _run(tmp_path, {}, {})
    assert result.returncode == 1
    assert "Environment: Headless or Unknown" in result.stdout
    assert "NONE FOUND" in result.stdout
    assert "No clipboard utilities installed" in result.stderr


def test_wayland_copies_the_test_string_with_wl_copy(tmp_path):
    result = _run(tmp_path, {"wl-copy": _record(tmp_path)}, {"WAYLAND_DISPLAY": "wayland-0"})
    assert result.returncode == 0
    assert "Environment: Wayland detected (wayland-0)" in result.stdout
    assert (tmp_path / "copied").read_text() == "Clipboard_Test_1700000000\n"
    assert "Action: Please press CTRL+V" in result.stdout


def test_x11_prefers_xclip_with_the_clipboard_selection(tmp_path):
    tools = {"xclip": _record(tmp_path), "xsel": f'echo xsel > "{tmp_path}/used"; cat >/dev/null'}
    result = _run(tmp_path, tools, {"DISPLAY": ":0"})
    assert result.returncode == 0
    assert "Environment: X11 detected (:0)" in result.stdout
    assert (tmp_path / "used").read_text().endswith("xclip -selection clipboard\n")


def test_x11_falls_back_to_xsel(tmp_path):
    result = _run(tmp_path, {"xsel": _record(tmp_path)}, {"DISPLAY": ":0"})
    assert result.returncode == 0
    assert (tmp_path / "used").read_text().endswith("xsel --clipboard --input\n")


def test_pbcopy_wins_over_the_display_tools(tmp_path):
    tools = {"pbcopy": _record(tmp_path), "xclip": f'echo xclip > "{tmp_path}/used"; cat >/dev/null'}
    result = _run(tmp_path, tools, {"DISPLAY": ":0"})
    assert result.returncode == 0
    assert (tmp_path / "used").read_text().strip().endswith("/pbcopy")


def test_a_tool_that_does_not_match_the_session_fails(tmp_path):
    result = _run(tmp_path, {"xclip": _record(tmp_path)}, {})
    assert result.returncode == 1
    assert "Could not map environment to a tool" in result.stdout
    assert not (tmp_path / "copied").exists()
