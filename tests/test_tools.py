import json
from types import SimpleNamespace

from dotfiles_setup import tools
from dotfiles_setup.log import Logger


class Recorder:
    def __init__(self, returncodes=None):
        self.calls = []
        self.returncodes = list(returncodes or [])

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        return SimpleNamespace(returncode=self.returncodes.pop(0) if self.returncodes else 0)


def tooling(tmp_path, run, fetch=lambda url: "#script", dry_run=False):
    return tools.Tooling(Logger(dry_run=dry_run, verbosity=1), tmp_path, run=run, fetch=fetch)


def test_sdkman_pipes_the_download_into_bash_without_rc_update(tmp_path):
    urls = []
    run = Recorder()
    assert tools.install_sdkman(tooling(tmp_path, run, fetch=lambda url: urls.append(url) or "#sdk"))
    assert urls == [tools.SDKMAN_URL]
    assert "rcupdate=false" in urls[0]
    assert run.calls[0][0] == ["bash"] and run.calls[0][1]["input"] == "#sdk"


def test_omz_keeps_zshrc_and_skips_shell_switch(tmp_path):
    run = Recorder()
    assert tools.install_omz(tooling(tmp_path, run))
    env = run.calls[0][1]["env"]
    assert (env["KEEP_ZSHRC"], env["RUNZSH"], env["CHSH"]) == ("yes", "no", "no")
    assert run.calls[0][0][-1] == "--unattended"


def test_installed_tools_are_skipped(tmp_path):
    (tmp_path / ".sdkman").mkdir()
    (tmp_path / ".oh-my-zsh").mkdir()
    (tmp_path / ".nvm").mkdir()
    run = Recorder()
    assert tools.install_tools(tooling(tmp_path, run), {"sdkman", "oh-my-zsh", "nvm"})
    assert run.calls == []


def test_dry_run_downloads_and_runs_nothing(tmp_path):
    def refuse(url):
        raise AssertionError(url)

    run = Recorder()
    assert tools.install_tools(tooling(tmp_path, run, fetch=refuse, dry_run=True), {"sdkman", "oh-my-zsh", "nvm"})
    assert run.calls == []


def test_failed_sdkman_script_fails_the_install(tmp_path):
    assert not tools.install_sdkman(tooling(tmp_path, Recorder([1])))


def test_failed_download_fails_sdkman(tmp_path):
    def broken(url):
        raise OSError("offline")

    assert not tools.install_sdkman(tooling(tmp_path, Recorder(), fetch=broken))


def nvm_fetch(url):
    if url == tools.NVM_RELEASE_API:
        return json.dumps({"assets": [{"browser_download_url": "https://example.com/install.sh"}]})
    return "#nvm"


def test_nvm_uses_the_latest_release_script_then_installs_node_lts(tmp_path):
    def run(argv, **kwargs):
        if kwargs.get("input"):
            (tmp_path / ".nvm").mkdir()
            (tmp_path / ".nvm" / "nvm.sh").write_text("")
        calls.append(argv)
        return SimpleNamespace(returncode=0)

    calls = []
    assert tools.install_nvm(tooling(tmp_path, run, fetch=nvm_fetch))
    assert calls[0] == ["bash"]
    assert calls[1][:2] == ["bash", "-c"] and "nvm install --lts" in calls[1][2]


def test_nvm_falls_back_to_pinned_script_when_release_lookup_fails(tmp_path):
    urls = []

    def fetch(url):
        urls.append(url)
        if url == tools.NVM_RELEASE_API:
            raise OSError("rate limited")
        return "#nvm"

    assert tools.install_nvm(tooling(tmp_path, Recorder(), fetch=fetch))
    assert urls[-1] == tools.NVM_FALLBACK_URL


def test_nvm_script_failure_warns_and_continues(tmp_path):
    run = Recorder([1])
    assert tools.install_nvm(tooling(tmp_path, run, fetch=nvm_fetch))
    assert len(run.calls) == 1


def test_node_lts_failure_warns_and_continues(tmp_path):
    def run(argv, **kwargs):
        if kwargs.get("input"):
            (tmp_path / ".nvm").mkdir()
            (tmp_path / ".nvm" / "nvm.sh").write_text("")
            return SimpleNamespace(returncode=0)
        return SimpleNamespace(returncode=1)

    assert tools.install_nvm(tooling(tmp_path, run, fetch=nvm_fetch))


def test_install_tools_runs_selected_tools_in_shell_order(tmp_path):
    order = []
    run = Recorder()
    t = tooling(tmp_path, run, fetch=lambda url: order.append(url) or "#")
    tools.install_tools(t, {"sdkman", "oh-my-zsh"})
    assert order == [tools.OMZ_URL, tools.SDKMAN_URL]


def test_install_tools_stops_at_the_first_failure(tmp_path):
    run = Recorder([1])
    assert not tools.install_tools(tooling(tmp_path, run), {"oh-my-zsh", "sdkman"})
    assert len(run.calls) == 1
