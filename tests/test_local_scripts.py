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
