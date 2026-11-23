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
    "jetbrains-toolbox": (
        "JetBrains Toolbox", "3.9.1.89198", "https://download.jetbrains.com/toolbox/jetbrains-toolbox-3.9.1.89198.tar.gz",
        "jetbrains-toolbox-3.9.1.89198.tar.gz", "targz",
    ),
    "istioctl": (
        "istioctl", "1.32.0", "https://github.com/istio/istio/releases/download/1.32.0/istio-1.32.0-linux-amd64.tar.gz",
        "istio-1.32.0-linux-amd64.tar.gz", "targz",
    ),
    "awscli": (
        "AWS CLI", "2.40.3", "https://awscli.amazonaws.com/awscli-exe-linux-x86_64-2.40.3.zip", "awscliv2-2.40.3.zip", "zip",
    ),
    "zizmor": (
        "zizmor", "v1.32.0",
        "https://github.com/zizmorcore/zizmor/releases/download/v1.32.0/zizmor-x86_64-unknown-linux-gnu.tar.gz",
        "zizmor-v1.32.0.tar.gz", "targz",
    ),
    "mcp-grafana": (
        "mcp-grafana", "v2.3.0",
        "https://github.com/grafana/mcp-grafana/releases/download/v2.3.0/mcp-grafana_Linux_x86_64.tar.gz",
        "mcp-grafana-v2.3.0.tar.gz", "targz",
    ),
    "chip": (
        "chip", "0.0.67", "https://github.com/collibra/chip/releases/download/v0.0.67/chip-0.0.67-linux-amd64",
        "chip-0.0.67", "binary",
    ),
    "kubectl": (
        "kubectl", "v1.36.6", "https://dl.k8s.io/release/v1.36.6/bin/linux/amd64/kubectl", "kubectl-v1.36.6", "binary",
    ),
    "helm": (
        "helm", "v4.3.2", "https://get.helm.sh/helm-v4.3.2-linux-amd64.tar.gz", "helm-v4.3.2.tar.gz", "targz",
    ),
    "flux": (
        "flux", "2.10.0", "https://github.com/fluxcd/flux2/releases/download/v2.10.0/flux_2.10.0_linux_amd64.tar.gz",
        "flux-2.10.0.tar.gz", "targz",
    ),
    "kubeconform": (
        "kubeconform", "v0.8.0",
        "https://github.com/yannh/kubeconform/releases/download/v0.8.0/kubeconform-linux-amd64.tar.gz",
        "kubeconform-v0.8.0.tar.gz", "targz",
    ),
    "cargo-deny": (
        "cargo-deny", "0.22.0",
        "https://github.com/EmbarkStudios/cargo-deny/releases/download/0.22.0/cargo-deny-0.22.0-x86_64-unknown-linux-musl.tar.gz",
        "cargo-deny-0.22.0.tar.gz", "targz",
    ),
    "sops": (
        "sops", "v3.13.3", "https://github.com/getsops/sops/releases/download/v3.13.3/sops-v3.13.3.linux.amd64",
        "sops-v3.13.3", "binary",
    ),
    "kind": (
        "kind", "v0.33.0", "https://github.com/kubernetes-sigs/kind/releases/download/v0.33.0/kind-linux-amd64",
        "kind-v0.33.0", "binary",
    ),
    "actionlint": (
        "actionlint", "1.7.12",
        "https://github.com/rhysd/actionlint/releases/download/v1.7.12/actionlint_1.7.12_linux_amd64.tar.gz",
        "actionlint-1.7.12.tar.gz", "targz",
    ),
    "gitleaks": (
        "gitleaks", "8.30.1",
        "https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_linux_x64.tar.gz",
        "gitleaks-8.30.1.tar.gz", "targz",
    ),
    "yq": (
        "yq", "v4.54.3", "https://github.com/mikefarah/yq/releases/download/v4.54.3/yq_linux_amd64",
        "yq-v4.54.3", "binary",
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


def test_a_binary_kind_needs_the_binary_field():
    assert isinstance(parse({**GOOD, "kind": "binary"}), Err)
    assert isinstance(parse({**GOOD, "kind": "binary", "binary": "tool"}), Ok)


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
