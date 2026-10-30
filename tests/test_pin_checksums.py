import hashlib

import pytest
from dotfiles_setup import pin_checksums as pc

URL_A = "https://example.test/a/install.sh"
URL_B = "https://example.test/b/tool.deb"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def serving(**by_url):
    def fetch(url):
        value = by_url[url]
        if isinstance(value, Exception):
            raise value
        return value

    return fetch


def checksums(tmp_path, a=b"old-a", b=b"b"):
    path = tmp_path / "checksums.txt"
    path.write_text(f"# header\n{digest(a)}  {URL_A}\n\n# debs\n{digest(b)}  {URL_B}  # trailing\n")
    return path


def test_a_current_digest_is_left_alone(tmp_path, capsys):
    path = checksums(tmp_path, a=b"a", b=b"b")
    before = path.read_text()
    assert pc.main([], path, serving(**{URL_A: b"a", URL_B: b"b"})) == 0
    assert path.read_text() == before
    assert capsys.readouterr().out.count("ok ") == 2


def test_a_stale_digest_is_rewritten_in_place_with_comments_and_spacing_kept(tmp_path, capsys):
    path = checksums(tmp_path)
    assert pc.main([], path, serving(**{URL_A: b"new-a", URL_B: b"b"})) == 0
    assert path.read_text() == (
        f"# header\n{digest(b'new-a')}  {URL_A}\n\n# debs\n{digest(b'b')}  {URL_B}  # trailing\n"
    )
    out = capsys.readouterr().out
    assert f"STALE  {URL_A}" in out
    assert "Re-recorded 1 digest(s)" in out


def test_a_filter_limits_which_urls_are_downloaded(tmp_path):
    path = checksums(tmp_path)
    asked = []

    def fetch(url):
        asked.append(url)
        return b"b"

    assert pc.main(["tool.deb"], path, fetch) == 0
    assert asked == [URL_B]


def test_a_filter_that_matches_nothing_fails(tmp_path, capsys):
    path = checksums(tmp_path)
    assert pc.main(["nope"], path, serving()) == 1
    assert "No URL" in capsys.readouterr().out


def test_a_failed_download_leaves_its_line_untouched_and_fails_the_run(tmp_path, capsys):
    path = checksums(tmp_path)
    assert pc.main([], path, serving(**{URL_A: OSError("offline"), URL_B: b"changed"})) == 1
    text = path.read_text()
    assert f"{digest(b'old-a')}  {URL_A}" in text
    assert f"{digest(b'changed')}  {URL_B}" in text
    assert f"ERROR  {URL_A}: offline" in capsys.readouterr().out


def test_check_reports_without_writing_and_fails_on_a_stale_digest(tmp_path):
    path = checksums(tmp_path)
    before = path.read_text()
    assert pc.main(["--check"], path, serving(**{URL_A: b"new-a", URL_B: b"b"})) == 1
    assert path.read_text() == before


def test_check_passes_when_every_digest_is_current(tmp_path):
    path = checksums(tmp_path, a=b"a")
    assert pc.main(["--check"], path, serving(**{URL_A: b"a", URL_B: b"b"})) == 0


@pytest.mark.parametrize("line", ["", "# only a comment", "not-a-digest  https://example.test/x"])
def test_lines_that_are_not_digest_entries_are_never_touched(line):
    text = f"{line}\n"
    assert pc.pin_text(text, [], serving()) == (text, [])


def test_the_real_checksums_file_parses_into_entries():
    text = pc.DEFAULT_PATH.read_text()
    _, pins = pc.pin_text(text, [], lambda url: b"")
    assert len(pins) >= 5
    assert all(pin.url.startswith("https://") for pin in pins)
