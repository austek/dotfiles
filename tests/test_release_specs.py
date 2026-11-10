import json

import pytest
from dotfiles_setup import release_installers as ri
from dotfiles_setup import release_specs as rs
from dotfiles_setup.result import Err, Ok

LEGACY = {
    "lazydocker": (
        "lazydocker", "0.25.2",
        "https://github.com/jesseduffield/lazydocker/releases/download/v0.25.2/lazydocker_0.25.2_Linux_x86_64.tar.gz",
        "0.25.2.tar.gz", "targz",
    ),
    "zoom": ("Zoom", "7.2.5.6661", "https://cdn.zoom.us/prod/7.2.5.6661/zoom_amd64.deb", "zoom_amd64-7.2.5.6661.deb", "deb"),
    "slack-desktop": (
        "Slack", "4.53.276",
        "https://downloads.slack-edge.com/desktop-releases/linux/x64/4.53.276/slack-desktop-4.53.276-amd64.deb",
        "slack-desktop-4.53.276-amd64.deb", "deb",
    ),
    "jetbrains-toolbox": (
        "JetBrains Toolbox", "3.9.1.89198", "https://download.jetbrains.com/toolbox/jetbrains-toolbox-3.9.1.89198.tar.gz",
        "jetbrains-toolbox-3.9.1.89198.tar.gz", "targz",
    ),
    "istioctl": (
        "istioctl", "1.31.4", "https://github.com/istio/istio/releases/download/1.31.4/istio-1.31.4-linux-amd64.tar.gz",
        "istio-1.31.4-linux-amd64.tar.gz", "targz",
    ),
    "awscli": (
        "AWS CLI", "2.39.6", "https://awscli.amazonaws.com/awscli-exe-linux-x86_64-2.39.6.zip", "awscliv2-2.39.6.zip", "zip",
    ),
    "zizmor": (
        "zizmor", "v1.32.0",
        "https://github.com/zizmorcore/zizmor/releases/download/v1.32.0/zizmor-x86_64-unknown-linux-gnu.tar.gz",
        "zizmor-v1.32.0.tar.gz", "targz",
    ),
    "mcp-grafana": (
        "mcp-grafana", "v2.2.0",
        "https://github.com/grafana/mcp-grafana/releases/download/v2.2.0/mcp-grafana_Linux_x86_64.tar.gz",
        "mcp-grafana-v2.2.0.tar.gz", "targz",
    ),
}
GOOD = {
    "package": "tool", "name": "Tool", "version": "1.0", "url": "https://example.com/{version}/tool.tgz",
    "cache_key": "tool-{version}.tgz", "kind": "targz",
}


def parse(*entries):
    return rs.parse_specs(json.dumps(list(entries)))


def test_release_specs_keep_the_order_the_installer_runs_them_in():
    assert [package for package, _ in ri.RELEASE_SPECS] == list(LEGACY)


@pytest.mark.parametrize("package", list(LEGACY))
def test_each_spec_resolves_to_the_pinned_download_the_constants_used_to_build(package):
    name, version, url, cache_key, kind = LEGACY[package]
    spec = dict(ri.RELEASE_SPECS)[package]
    resolved = spec.resolve(None)
    assert (spec.name, resolved.version, resolved.url, resolved.cache_key, spec.kind) == (name, version, url, cache_key, kind)


def test_a_well_formed_spec_loads():
    assert parse(GOOD) == Ok((rs.SpecData(**GOOD),))


def test_the_binary_field_is_optional_and_kept():
    assert parse({**GOOD, "binary": "tool"}).value[0].binary == "tool"


@pytest.mark.parametrize("field", rs.REQUIRED_FIELDS)
def test_a_missing_required_field_is_rejected(field):
    entry = {k: v for k, v in GOOD.items() if k != field}
    assert isinstance(parse(entry), Err)


@pytest.mark.parametrize("bad", [{"kind": "rpm"}, {"url": "http://example.com/{version}"}, {"name": " "}, {"extra": "x"}])
def test_a_malformed_spec_is_rejected(bad):
    assert isinstance(parse({**GOOD, **bad}), Err)


@pytest.mark.parametrize("field", ["url", "cache_key"])
def test_a_template_with_another_placeholder_is_rejected(field):
    assert isinstance(parse({**GOOD, field: "https://example.com/{arch}/x" if field == "url" else "{arch}"}), Err)


def test_repeated_packages_are_rejected():
    assert "repeat packages: tool" in parse(GOOD, GOOD).error


@pytest.mark.parametrize("text", ["not json", "{}", "[]", "[1]"])
def test_a_file_that_is_not_a_list_of_specs_is_rejected(text):
    assert isinstance(rs.parse_specs(text), Err)


def test_an_unreadable_file_is_an_error_value(tmp_path):
    assert isinstance(rs.load_specs(tmp_path / "missing.json"), Err)


def test_every_pinned_url_has_a_digest_in_checksums_txt():
    recorded = ri.SPECS_FILE.parent.joinpath("checksums.txt").read_text()
    assert [d.package for d in ri.SPEC_DATA.values() if d.download_url not in recorded] == []
