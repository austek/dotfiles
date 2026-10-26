import os
import shutil
import subprocess
from pathlib import Path

import pytest

BIN = Path(__file__).resolve().parent.parent / "local" / ".local" / "bin"


def _stub(stubs: Path, name: str, body: str) -> None:
    path = stubs / name
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(0o755)


@pytest.fixture
def sandbox(tmp_path):
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    env = {
        "PATH": f"{stubs}:{BIN}:{os.environ['PATH']}",
        "HOME": str(home),
        "STUB_LOG": str(tmp_path / "calls.log"),
    }
    return tmp_path, stubs, home, env


def _run(script, args, env, cwd=None, timeout=120):
    return subprocess.run(
        [str(BIN / script), *args], env=env, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
    )


def _calls(env):
    log = Path(env["STUB_LOG"])
    return log.read_text().splitlines() if log.exists() else []


def _logging_stub(stubs, name, extra=""):
    _stub(stubs, name, f'echo "{name} $*" >> "$STUB_LOG"\n{extra}\n')


def _path_without(tmp_path, stubs, *names):
    """A PATH of `stubs` plus every system binary except `names`, to simulate a missing dependency."""
    farm = tmp_path / "farm"
    farm.mkdir(exist_ok=True)
    for directory in ("/usr/bin", "/bin"):
        for entry in os.scandir(directory):
            link = farm / entry.name
            if entry.name not in names and not link.is_symlink():
                link.symlink_to(entry.path)
    return f"{stubs}:{farm}"


def test_term_notify_strips_control_characters():
    out = subprocess.run(
        [str(BIN / "term-notify"), "hi\x1b]52;x\x07there"],
        env={"PATH": os.environ["PATH"]}, capture_output=True, text=True, check=False,
    ).stdout
    assert out == "\x1b]9;hi]52;xthere\x07"


def test_term_notify_defaults_message_and_wraps_for_tmux():
    out = subprocess.run(
        [str(BIN / "term-notify")],
        env={"PATH": os.environ["PATH"], "TMUX": "1"}, capture_output=True, text=True, check=False,
    ).stdout
    assert out == "\x1bPtmux;\x1b\x1b]9;Claude Code\x07\x1b\\"


def test_gradle_prop_reads_value_after_first_equals(sandbox):
    _, _, home, env = sandbox
    (home / ".gradle").mkdir()
    (home / ".gradle" / "gradle.properties").write_text("other=1\ndockerUsername=a=b\n")
    assert _run("gradle_prop", ["dockerUsername"], env).stdout == "a=b\n"


def test_gradle_prop_missing_key_prints_nothing(sandbox):
    _, _, home, env = sandbox
    (home / ".gradle").mkdir()
    (home / ".gradle" / "gradle.properties").write_text("a=1\n")
    assert _run("gradle_prop", ["nope"], env).stdout == ""


def test_gradle_prop_requires_argument(sandbox):
    result = _run("gradle_prop", [], sandbox[3])
    assert result.returncode == 1
    assert "Usage" in result.stderr


def test_iload_opens_first_matching_project(sandbox):
    _, stubs, home, env = sandbox
    (home / "Workspace" / "grp" / "proj").mkdir(parents=True)
    _logging_stub(stubs, "idea")
    assert _run("iload", ["proj"], env).returncode == 0
    assert _calls(env) == [f"idea {home}/Workspace/grp/proj"]


def test_iload_reports_missing_project(sandbox):
    _, _, home, env = sandbox
    (home / "Workspace").mkdir()
    result = _run("iload", ["ghost"], env)
    assert result.returncode == 1
    assert "not found" in result.stdout


def _kdev_stubs(stubs, helm_extra=""):
    _logging_stub(stubs, "kind")
    _logging_stub(stubs, "kubectl")
    _logging_stub(stubs, "helm", helm_extra)
    _stub(stubs, "gradle_prop", 'echo "$1-value"\n')


def test_kdev_without_command_prints_usage(sandbox):
    result = _run("kdev", [], sandbox[3])
    assert result.returncode == 1
    assert "Usage: kdev" in result.stdout


def test_kdev_load_requires_image_and_forwards_to_kind(sandbox):
    _, stubs, _, env = sandbox
    _kdev_stubs(stubs)
    assert _run("kdev", ["load"], env).returncode == 1
    assert _run("kdev", ["load", "img:1"], env).returncode == 0
    assert _calls(env) == ["kind load docker-image img:1 --name dev-cluster"]


def test_kdev_down_deletes_cluster(sandbox):
    _, stubs, _, env = sandbox
    _kdev_stubs(stubs)
    assert _run("kdev", ["down"], env).returncode == 0
    assert _calls(env) == ["kind delete cluster --name dev-cluster"]


def test_kdev_up_installs_pinned_ingress_manifest(sandbox):
    _, stubs, _, env = sandbox
    _kdev_stubs(stubs)
    assert _run("kdev", ["up"], env).returncode == 0
    apply = next(c for c in _calls(env) if " apply " in c)
    assert "ingress-nginx/controller-v" in apply
    assert "/main/" not in apply


def test_kdev_up_generates_ingress_ready_loopback_config(sandbox):
    _, stubs, home, env = sandbox
    _kdev_stubs(stubs)
    assert _run("kdev", ["up"], env).returncode == 0
    cfg = (home / ".config" / "kdev" / "kind-config.yaml").read_text()
    assert 'node-labels: "ingress-ready=true"' in cfg
    mappings = [line for line in cfg.splitlines() if "containerPort" in line]
    assert mappings
    assert all('listenAddress: "127.0.0.1"' in line for line in mappings)


def test_kdev_up_replaces_dangling_config_symlink(sandbox):
    tmp, stubs, home, env = sandbox
    _kdev_stubs(stubs)
    link = home / ".config" / "kdev" / "kind-config.yaml"
    link.parent.mkdir(parents=True)
    link.symlink_to(tmp / "removed" / "kind-config.yaml")
    assert _run("kdev", ["up"], env).returncode == 0
    assert not link.is_symlink()
    assert 'node-labels: "ingress-ready=true"' in link.read_text()


def test_kdev_up_stops_when_config_generation_fails(sandbox):
    _, stubs, home, env = sandbox
    _kdev_stubs(stubs)
    (home / ".config" / "kdev" / "kind-config.yaml").mkdir(parents=True)
    result = _run("kdev", ["up"], env)
    assert result.returncode == 1
    assert "Environment Ready" not in result.stdout
    assert not any(c.startswith(("kubectl", "kind create")) for c in _calls(env))


def test_kdev_repos_adds_each_repo_including_unterminated_last_line(sandbox):
    _, stubs, home, env = sandbox
    _kdev_stubs(stubs)
    cfg = home / ".config" / "kdev"
    cfg.mkdir(parents=True)
    (cfg / "helm-repos.txt").write_text("# comment\nfirst https://a.example\nsecond https://b.example")
    assert _run("kdev", ["repos"], env).returncode == 0
    adds = [c for c in _calls(env) if c.startswith("helm repo add")]
    assert [a.split()[3] for a in adds] == ["first", "second"]
    assert "helm repo update" in _calls(env)


def test_kdev_repos_fails_when_helm_repo_add_fails(sandbox):
    _, stubs, home, env = sandbox
    _kdev_stubs(stubs, helm_extra='[[ "$2" == add ]] && exit 7; exit 0')
    cfg = home / ".config" / "kdev"
    cfg.mkdir(parents=True)
    (cfg / "helm-repos.txt").write_text("first https://a.example\n")
    assert _run("kdev", ["repos"], env).returncode != 0
    assert "helm repo update" not in _calls(env)


def test_kdev_up_fails_when_kind_create_fails(sandbox):
    _, stubs, _, env = sandbox
    _kdev_stubs(stubs)
    _logging_stub(stubs, "kind", '[[ "$1" == create ]] && exit 9\nexit 0')
    result = _run("kdev", ["up"], env)
    assert result.returncode == 1
    assert "Environment Ready" not in result.stdout
    assert not any(c.startswith("kubectl") for c in _calls(env))


def test_kdev_up_fails_when_the_api_server_wait_fails(sandbox):
    _, stubs, _, env = sandbox
    _kdev_stubs(stubs)
    _logging_stub(stubs, "kubectl", "exit 5")
    result = _run("kdev", ["up"], env)
    assert result.returncode == 1
    assert "Installing Ingress Controller" not in result.stdout
    assert len([c for c in _calls(env) if c.startswith("kubectl")]) == 1


def test_kdev_up_fails_when_the_ingress_manifest_fails_to_apply(sandbox):
    _, stubs, _, env = sandbox
    _kdev_stubs(stubs)
    _logging_stub(stubs, "kubectl", '[[ " $* " == *" apply "* ]] && exit 6\nexit 0')
    result = _run("kdev", ["up"], env)
    assert result.returncode == 1
    assert "Waiting for Ingress" not in result.stdout
    assert "Environment Ready" not in result.stdout


def test_kdev_up_fails_when_the_ingress_wait_fails(sandbox):
    _, stubs, _, env = sandbox
    _kdev_stubs(stubs)
    _logging_stub(stubs, "kubectl", '[[ " $* " == *" ingress-nginx "* ]] && exit 6\nexit 0')
    result = _run("kdev", ["up"], env)
    assert result.returncode == 1
    assert "Waiting for Ingress" in result.stdout
    assert "Environment Ready" not in result.stdout


def test_kdev_load_returns_the_failure_status_of_kind(sandbox):
    _, stubs, _, env = sandbox
    _kdev_stubs(stubs)
    _logging_stub(stubs, "kind", "exit 4")
    assert _run("kdev", ["load", "img:1"], env).returncode == 4


def _kdev_repos_file(home, content="first https://a.example\n"):
    cfg = home / ".config" / "kdev"
    cfg.mkdir(parents=True)
    (cfg / "helm-repos.txt").write_text(content)


def test_kdev_repos_fails_when_helm_is_not_installed(sandbox):
    tmp, stubs, _, env = sandbox
    result = _run("kdev", ["repos"], {**env, "PATH": _path_without(tmp, stubs, "helm")})
    assert result.returncode == 1
    assert "'helm' is not installed" in result.stdout


def test_kdev_repos_fails_when_the_repos_file_is_missing(sandbox):
    _, stubs, _, env = sandbox
    _kdev_stubs(stubs)
    result = _run("kdev", ["repos"], env)
    assert result.returncode == 1
    assert "No helm repos configured" in result.stdout


def test_kdev_repos_fails_when_gradle_prop_is_missing(sandbox):
    tmp, stubs, home, env = sandbox
    _logging_stub(stubs, "helm")
    _kdev_repos_file(home)
    result = _run("kdev", ["repos"], {**env, "PATH": _path_without(tmp, stubs, "gradle_prop")})
    assert result.returncode == 1
    assert "'gradle_prop' script not found" in result.stdout
    assert _calls(env) == []


def test_kdev_repos_fails_when_credentials_are_empty(sandbox):
    _, stubs, home, env = sandbox
    _kdev_stubs(stubs)
    _stub(stubs, "gradle_prop", "exit 0\n")
    _kdev_repos_file(home)
    result = _run("kdev", ["repos"], env)
    assert result.returncode == 1
    assert "Could not fetch credentials" in result.stdout
    assert _calls(env) == []


def _flaky_sandbox(sandbox, gradle_body):
    tmp, stubs, _, env = sandbox
    _stub(
        stubs,
        "systemd-run",
        'wd=.\nwhile [[ $# -gt 0 ]]; do\n  case "$1" in\n'
        '    --working-directory=*) wd="${1#*=}" ;;\n    --) shift; break ;;\n  esac\n  shift\ndone\n'
        'cd "$wd" && exec "$@"\n',
    )
    _stub(stubs, "systemctl", "exit 0\n")
    repo = tmp / "repo"
    repo.mkdir()
    gradlew = repo / "gradlew"
    gradlew.write_text("#!/usr/bin/env bash\n" + gradle_body)
    gradlew.chmod(0o755)
    out = tmp / "out"
    out.mkdir()
    return repo, {**env, "OUT_BASE": str(out)}, out


def test_flaky_it_requires_gradlew(sandbox):
    result = _run("flaky-it", [], sandbox[3], cwd=sandbox[0])
    assert result.returncode == 2
    assert "gradlew" in result.stderr


def test_flaky_it_help_exits_zero(sandbox):
    repo, env, _ = _flaky_sandbox(sandbox, "exit 0\n")
    result = _run("flaky-it", ["--help"], env, cwd=repo)
    assert result.returncode == 0
    assert "Usage:" in result.stdout


def test_flaky_it_rejects_unknown_order(sandbox):
    repo, env, _ = _flaky_sandbox(sandbox, "exit 0\n")
    result = _run("flaky-it", ["-n", "1", "--order", "bogus"], env, cwd=repo)
    assert result.returncode == 2
    assert "unknown --order" in result.stderr


@pytest.mark.skipif(shutil.which("systemd-run") is None and False, reason="stubbed")
def test_flaky_it_passing_run_exits_zero_and_escapes_groovy(sandbox):
    repo, env, out = _flaky_sandbox(sandbox, 'echo "BUILD SUCCESSFUL in 1s"\n')
    result = _run("flaky-it", ["-n", "1", "--jvm-args", "-Dx=it's", "--order", "classname"], env, cwd=repo)
    assert result.returncode == 0, result.stderr
    assert "Passed: 1 / 1" in result.stdout
    init = next(out.glob("*/flaky-it-init.gradle")).read_text()
    assert "'-Dx=it\\'s'" in init


def test_flaky_it_failing_run_exits_nonzero(sandbox):
    repo, env, _ = _flaky_sandbox(sandbox, 'echo "BUILD FAILED in 1s"\nexit 1\n')
    result = _run("flaky-it", ["-n", "1"], env, cwd=repo)
    assert result.returncode == 1
    assert "Failed: 1 / 1" in result.stdout


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--times", "abc"], "--times requires a non-negative integer"),
        (["--times=-1"], "--times requires a non-negative integer"),
        (["--suite"], "--suite requires a value"),
        (["--scope-prop", "noequals"], "--scope-prop requires a KEY=VALUE argument"),
        (["--cpus"], "--cpus requires a value"),
        (["--order"], "--order requires a value"),
        (["--jvm-args"], "--jvm-args requires a value"),
    ],
)
def test_flaky_it_rejects_a_malformed_option(sandbox, args, message):
    repo, env, _ = _flaky_sandbox(sandbox, "exit 0\n")
    result = _run("flaky-it", args, env, cwd=repo)
    assert result.returncode == 2
    assert message in result.stderr


def test_flaky_it_fails_fast_without_a_systemd_user_session(sandbox):
    repo, env, _ = _flaky_sandbox(sandbox, "exit 0\n")
    _stub(sandbox[1], "systemd-run", "exit 1\n")
    result = _run("flaky-it", ["-n", "1"], env, cwd=repo)
    assert result.returncode == 2
    assert "requires a systemd user session" in result.stderr


def test_flaky_it_fails_when_cpus_is_given_without_taskset(sandbox):
    repo, env, _ = _flaky_sandbox(sandbox, "exit 0\n")
    tmp, stubs, _, _ = sandbox
    result = _run("flaky-it", ["-n", "1", "--cpus", "0"], {**env, "PATH": _path_without(tmp, stubs, "taskset")}, cwd=repo)
    assert result.returncode == 2
    assert "taskset not found" in result.stderr
