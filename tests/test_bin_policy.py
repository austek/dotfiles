"""Policy: a user-level installer puts each new executable under ~/.local/bin or in an allowlisted self-managing tree, never elsewhere under $HOME."""
import ast
import io
import itertools
import os
import re
import tarfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest
from dotfiles_setup import post_apt_installers, tools, user_links
from dotfiles_setup import release_installers as ri
from dotfiles_setup.log import Logger

SOURCE_DIR = Path(__file__).parent.parent / "bin" / "dotfiles_setup"
USER_BIN = Path(".local/bin")
SELF_MANAGING_ROOTS = (".sdkman", ".nvm", ".cargo", ".oh-my-zsh", ".local/aws-cli")
SHARE_DIR = Path(".local/share")
SHARE_DEPTH = len(SHARE_DIR.parts) + 2


def allowed(relative: Path) -> bool:
    if relative.is_relative_to(USER_BIN):
        return True
    if any(relative.is_relative_to(root) for root in SELF_MANAGING_ROOTS):
        return True
    return relative.is_relative_to(SHARE_DIR) and len(relative.parts) >= SHARE_DEPTH


def is_executable_or_link(path: Path) -> bool:
    return path.is_symlink() or (path.is_file() and path.stat().st_mode & 0o111 != 0)


def executables_and_links(home: Path) -> set[Path]:
    found: set[Path] = set()
    for directory, subdirectories, files in os.walk(home, followlinks=False):
        found.update(p for p in (Path(directory) / n for n in (*subdirectories, *files)) if is_executable_or_link(p))
    return found


def violations(home: Path, before: set[Path]) -> list[str]:
    created = executables_and_links(home) - before
    return sorted(str(p.relative_to(home)) for p in created if not allowed(p.relative_to(home)))


def tarball(member: str) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        info = tarfile.TarInfo(member)
        info.size, info.mode = 3, 0o755
        archive.addfile(info, io.BytesIO(b"bin"))
    return buffer.getvalue()


def zipball(member: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        info = zipfile.ZipInfo(member)
        info.external_attr = 0o100755 << 16
        archive.writestr(info, "#!/bin/sh\n")
    return buffer.getvalue()


def payload_for(spec: ri.ReleaseSpec) -> bytes:
    if spec.kind == "zip":
        return zipball("aws/install")
    if spec.kind == "binary":
        return b"\x7fELF"
    return tarball(spec.binary or "jetbrains-toolbox")


def _executable(path: Path, content: bytes = b"\x7fELF") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    path.chmod(0o755)
    return path


class Machine:
    """Records every command and plays the tools it is asked to run: the AWS installer, pipx and cargo write where their flags say, and where their defaults put them when a flag is missing."""

    def __init__(self, home: Path):
        self.home = home
        self.commands: list[list[str]] = []

    def ran(self, name: str, *prefix: str) -> bool:
        return any(Path(c[0]).name == name and c[1 : 1 + len(prefix)] == list(prefix) for c in self.commands)

    def __call__(self, argv, **kwargs):
        self.commands.append(list(argv))
        stdout = "cargo 1.99.0" if Path(argv[0]).name == "cargo" and argv[1:2] == ["--version"] else ""
        if argv[0].endswith("aws/install"):
            self._aws(argv)
        elif argv[:2] == ["pipx", "install"]:
            _executable(self.home / ".local" / "bin" / argv[-1].split("==")[0])
        elif Path(argv[0]).name == "cargo" and argv[1:2] == ["install"]:
            self._cargo(argv)
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    def _cargo(self, argv):
        root = Path(argv[argv.index("--root") + 1]) if "--root" in argv else self.home / ".cargo"
        _executable(root / "bin" / argv[-1])

    def _aws(self, argv):
        flags = dict(zip(argv[1::2], argv[2::2], strict=False))
        root = Path(flags.get("-i", self.home / "usr/local/aws-cli"))
        bin_dir = Path(flags.get("-b", self.home / "usr/local/bin"))
        real = _executable(root / "v2" / "current" / "bin" / "aws", b"aws")
        bin_dir.mkdir(parents=True, exist_ok=True)
        for name in ("aws", "aws_completer"):
            (bin_dir / name).unlink(missing_ok=True)
            (bin_dir / name).symlink_to(real)


@pytest.fixture(autouse=True)
def stubbed_host(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr("shutil.which", lambda name, path=None: f"/usr/bin/{name}" if name in {"pipx", "cargo"} else None)
    monkeypatch.setattr("platform.machine", lambda: "x86_64")


@pytest.fixture
def home(tmp_path) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    return path


def download_artifact(url: str, dest: Path) -> None:
    payloads = {spec.resolve(None).url: payload_for(spec) for _, spec in ri.RELEASE_SPECS if spec.kind != "deb"}
    dest.write_bytes(payloads.get(url, b"x"))


SCRIPT = "#!/bin/sh\n# fake vendor script\n"


def tooling(home: Path, machine: Machine | None = None) -> tools.Tooling:
    return tools.Tooling(
        Logger(dry_run=False, verbosity=0), home, run=machine or Machine(home), fetch=lambda url: SCRIPT,
        download=download_artifact,
    )


def run_policy(home: Path, installer: Callable[[tools.Tooling], object]) -> list[str]:
    before = executables_and_links(home)
    installer(tooling(home))
    return violations(home, before)


def install_every_pinned_release(t: tools.Tooling) -> None:
    for _, spec in ri.RELEASE_SPECS:
        if spec.kind != "deb":
            ri.install_release(t, spec)


def prepare_what_the_vendor_scripts_installed(t: tools.Tooling) -> None:
    for _, _, locate in user_links.USER_LINKS:
        _executable(locate(t.home))


def link_tools(t: tools.Tooling) -> None:
    prepare_what_the_vendor_scripts_installed(t)
    user_links.link_user_tools(t, {package for package, _, _ in user_links.USER_LINKS})


def user_bin_has(*names: str) -> Callable[[Machine, Path], bool]:
    return lambda machine, home: all((home / USER_BIN / name).exists() for name in names)


def ran_script_with(shell: str) -> Callable[[Machine, Path], bool]:
    return lambda machine, home: machine.ran(shell)


RELEASE_BINARIES = {spec.binary for _, spec in ri.USER_BINARY_SPECS if spec.binary}
# The proof that each case reached its install command: a recorded command or an artifact it wrote.
INSTALLERS: dict[str, tuple[Callable[[tools.Tooling], object], Callable[[Machine, Path], bool]]] = {
    "pinned release binaries": (install_every_pinned_release, user_bin_has(*RELEASE_BINARIES, "aws_completer")),
    "user stage binaries step": (
        lambda t: ri.install_user_binaries(t, {p for p, _ in ri.USER_BINARY_SPECS}), user_bin_has(*RELEASE_BINARIES),
    ),
    "tool links": (link_tools, user_bin_has("sonar", "jetbrains-toolbox")),
    "jetbrains-toolbox": (
        dict(tools.TOOL_INSTALLERS)["jetbrains-toolbox"],
        lambda machine, home: ri._jetbrains_binary(home).is_file(),
    ),
    "oh-my-zsh": (dict(tools.TOOL_INSTALLERS)["oh-my-zsh"], ran_script_with("sh")),
    "sdkman": (dict(tools.TOOL_INSTALLERS)["sdkman"], ran_script_with("bash")),
    "nvm": (dict(tools.TOOL_INSTALLERS)["nvm"], ran_script_with("bash")),
    "coderabbit": (dict(tools.TOOL_INSTALLERS)["coderabbit"], ran_script_with("sh")),
    "sonarqube-cli": (dict(tools.TOOL_INSTALLERS)["sonarqube-cli"], ran_script_with("bash")),
    "uv": (dict(tools.TOOL_INSTALLERS)["uv"], ran_script_with("sh")),
    "ruff": (dict(post_apt_installers.POST_APT_INSTALLERS)["ruff"], user_bin_has("ruff")),
    "auditr": (dict(post_apt_installers.POST_APT_INSTALLERS)["auditr"], user_bin_has("auditr")),
    "cargo-deny": (dict(post_apt_installers.POST_APT_INSTALLERS)["cargo-deny"], user_bin_has("cargo-deny")),
    "cargo-audit": (dict(post_apt_installers.POST_APT_INSTALLERS)["cargo-audit"], user_bin_has("cargo-audit")),
}


@pytest.mark.parametrize("name", INSTALLERS)
def test_a_user_level_installer_reaches_its_install_and_writes_only_where_the_policy_allows(home, name):
    installer, reached = INSTALLERS[name]
    machine = Machine(home)
    before = executables_and_links(home)
    installer(tooling(home, machine))
    assert reached(machine, home), f"{name} never reached its install command"
    assert violations(home, before) == []


def test_every_registered_user_level_installer_has_a_case_that_proves_it_runs():
    registered = {n for n, _ in tools.TOOL_INSTALLERS} | {n for n, _ in post_apt_installers.POST_APT_INSTALLERS}
    assert registered <= set(INSTALLERS)


@pytest.mark.parametrize(("relative", "expected"), [
    (".local/bin/tool", []),
    (".local/share/tool/bin/tool", []),
    (".sdkman/candidates/java/current/bin/java", []),
    (".nvm/versions/node/v1/bin/node", []),
    (".cargo/bin/rustc", []),
    (".oh-my-zsh/tools/install.sh", []),
    (".local/aws-cli/v2/current/bin/aws", []),
    (".local/sbin/tool", [".local/sbin/tool"]),
    ("bin/tool", ["bin/tool"]),
    (".local/share/tool", [".local/share/tool"]),
    (".local/tool", [".local/tool"]),
    ("tool", ["tool"]),
    ("opt/tool/bin/tool", ["opt/tool/bin/tool"]),
])
def test_the_checker_flags_exactly_the_executables_outside_the_allowlist(home, relative, expected):
    def bad_installer(t):
        path = t.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        path.chmod(0o755)

    assert run_policy(home, bad_installer) == expected


def test_the_checker_flags_a_new_symlink_outside_the_allowlist(home):
    def bad_installer(t):
        (t.home / "bin").mkdir()
        (t.home / "bin" / "tool").symlink_to(t.home)

    assert run_policy(home, bad_installer) == ["bin/tool"]


def test_the_checker_ignores_plain_files_and_executables_that_were_already_there(home):
    old = home / "old-tool"
    old.write_bytes(b"x")
    old.chmod(0o755)

    def installer(t):
        (t.home / "notes.txt").write_text("data")

    assert run_policy(home, installer) == []


def test_an_awscli_installer_that_forgets_the_bin_dir_flag_is_caught(home):
    def forgetful(t):
        t.run([str(home / "staged" / "aws" / "install"), "-i", str(t.home / ".local" / "aws-cli")])

    assert run_policy(home, forgetful) == ["usr/local/bin/aws", "usr/local/bin/aws_completer"]


SUDO_COMMAND = re.compile(r"^\s*sudo(\s|$)")
SUDO_WRITE = re.compile(r"\bsudo\s+(-\S+\s+)*(install|cp|mv|ln|tee|rsync)\b")
# Modules whose sudo calls belong to the system stage, a root-owned GUI app, or the rollback of one.
DYNAMIC = "*"  # a verb the scan cannot read: a splatted argv, or a bare ["sudo"] prefix.
# Each exempt module may run sudo only with the verbs declared here.
PRIVILEGED_MODULES: dict[str, tuple[str, frozenset[str]]] = {
    "antigravity.py": (
        "system stage: root-owned /opt install with a setuid sandbox; `_sudo(t, *link)` carries ln",
        frozenset({"rm", "mkdir", "cp", "chown", "chmod", "mv", "gtk-update-icon-cache", "tee",
                   "update-desktop-database", DYNAMIC}),
    ),
    "apt_packages.py": ("system stage: apt and dpkg", frozenset({"rm", "apt-get", "dpkg"})),
    "apt_sources.py": (
        "system stage: apt source and key files under /etc",
        frozenset({"tee", "gpg", "timeout", "stow", "mv", "mkdir", "rm"}),
    ),
    "deb_helpers.py": ("system stage: dpkg-owned vendor debs", frozenset({"dpkg", "apt-get"})),
    "desktop_defaults.py": (
        "system stage: login shell and default terminal", frozenset({"usermod", "update-alternatives"}),
    ),
    "removals.py": ("system stage: apt removals", frozenset({"apt-get"})),
    "rollback.py": (
        "undoes system-stage changes; `_unstow` adds the sudo prefix conditionally",
        frozenset({"mv", "gpasswd", "rm", "apt-get", DYNAMIC}),
    ),
    "system_steps.py": (
        "system stage: system config, backed up before editing",
        frozenset({"apt-get", "snap", "stow", "cp", "sed", "groupadd", "usermod", "true", "-v"}),
    ),
}


def sudo_uses(source: str) -> list[int]:
    """Lines of string literals that are `sudo`, start a command with it, or run it before a file-writing verb, and of names `sudo` or `_sudo`."""
    hits = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value == "sudo" or SUDO_COMMAND.match(node.value) or SUDO_WRITE.search(node.value):
                hits.add(node.lineno)
        elif getattr(node, "id", getattr(node, "attr", None)) in {"sudo", "_sudo"}:
            hits.add(node.lineno)
    return sorted(hits)


@pytest.mark.parametrize("source", [
    't.run(["sudo", "install", str(binary), "/usr/local/bin"])',
    't.run(["sudo", "-n", "install", str(binary), "/usr/local/bin"])',
    'run(("sudo", "cp", "-a", src, dst))',
    'ctx.quiet("sudo", "mv", a, b)',
    '_sudo(t, "ln", "-sfn", a, b)',
    'prefix = ["sudo"]\nt.run([*prefix, "install", a, b])',
    'sudo = "sudo"\nt.run([sudo, "install", a, b])',
    't.run(["bash", "-c", "sudo install a /usr/local/bin"])',
    't.run(["sh", "-c", f"sudo -n install {binary} /usr/local/bin"])',
    't.run(["sh", "-c", f"sudo {verb} a b"])',
    't.run(["sudo", script])',
    't.run(["sudo", "apt-get", "install", "-y", name])',
], ids=[
    "install", "option before verb", "tuple cp", "quiet call mv", "_sudo helper", "splatted prefix", "sudo in a variable",
    "bash -c", "sh -c f-string", "sh -c f-string verb", "sudo script", "apt-get install",
])
def test_the_scanner_catches_every_form_of_a_sudo_call(source):
    assert sudo_uses(source) != []


@pytest.mark.parametrize("source", [
    't.run(["install", str(binary), str(target)])',
    '"""Keeps sudo credentials fresh for the length of a run."""',
    't.logger.info("remove it with sudo when convenient.")',
    'parser.add_argument("--system", help="Always run the sudo steps.")',
])
def test_the_scanner_ignores_mentions_of_sudo(source):
    assert sudo_uses(source) == []


def user_bin_spellings(source: str) -> list[int]:
    """Lines that spell the user bin dir as a path: a whitespace-free literal that ends in or runs through `.local/bin`, or `.local` then `bin` as consecutive path parts."""
    hits = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and PATH_LITERAL.match(node.value):
            hits.add(node.lineno)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            inner = node.left.right if isinstance(node.left, ast.BinOp) else node.left
            if [getattr(n, "value", None) for n in (inner, node.right)] == [".local", "bin"]:
                hits.add(node.lineno)
        if isinstance(node, ast.Call):
            parts = [getattr(a, "value", None) for a in node.args]
            if any(pair == (".local", "bin") for pair in itertools.pairwise(parts)):
                hits.add(node.lineno)
    return sorted(hits)


# Modules that may spell the path, with the reason. Everything else resolves it through user_bin_dir.
SPELLING_ALLOWLIST = {
    "release_installers.py": "defines user_bin_dir",
    "foothold.py": "systemd expands the %h specifier in the unit's PATH; there is no Tooling to resolve it",
}


@pytest.mark.parametrize("source", [
    'home / ".local/bin" / crate',
    'home / ".local" / "bin"',
    'f"{home / \'.local/bin\'}:{path}"',
    'Path(".local/bin/uv")',
    'Path("~/.local/bin")',
    'run("$HOME/.local/bin/uv")',
    'f"{home}/.local/bin"',
    'os.path.join(home, ".local", "bin")',
    'home.joinpath(".local", "bin")',
    'Path(".local", "bin")',
    'PATH_DIRS = ("%h/.local/bin",)',
], ids=[
    "div literal", "div parts", "f-string expression", "relative literal", "tilde", "$HOME", "f-string suffix",
    "os.path.join", "joinpath", "Path parts", "systemd specifier",
])
def test_the_spelling_scanner_catches_a_hand_built_user_bin_path(source):
    assert user_bin_spellings(source) != []


@pytest.mark.parametrize("source", [
    't.logger.warn("it will resolve once ~/.local/bin is sourced")',
    '"""Creates `~/.local/bin` (mode 0755)."""',
    'home / ".local" / "share" / "tool"',
    'Path(".local", "share")',
])
def test_the_spelling_scanner_ignores_prose_and_other_local_paths(source):
    assert user_bin_spellings(source) == []


def test_only_the_resolver_and_the_declared_specifier_spell_the_user_bin_dir():
    offenders = {
        name: user_bin_spellings(path.read_text(encoding="utf-8")) for name, path in _modules().items()
        if name not in SPELLING_ALLOWLIST
    }
    assert {name: lines for name, lines in offenders.items() if lines} == {}


def test_every_allowlisted_spelling_is_still_needed():
    modules = _modules()
    assert [n for n in SPELLING_ALLOWLIST if not user_bin_spellings(modules[n].read_text(encoding="utf-8"))] == []


def _modules() -> dict[str, Path]:
    return {p.relative_to(SOURCE_DIR).as_posix(): p for p in sorted(SOURCE_DIR.rglob("*.py"))}


def test_no_module_outside_the_declared_privileged_set_uses_sudo():
    offenders = {
        name: sudo_uses(path.read_text(encoding="utf-8")) for name, path in _modules().items()
        if name not in PRIVILEGED_MODULES
    }
    assert {name: lines for name, lines in offenders.items() if lines} == {}


ENV_ASSIGNMENT = re.compile(r"^\w+=")
PATH_LITERAL = re.compile(r"^\S*\.local/bin(/\S*)?$")


def _verb(rest: list[ast.expr]) -> str:
    options = []
    for item in rest:
        if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
            return DYNAMIC
        if item.value.startswith("-"):
            options.append(item.value)
        elif not ENV_ASSIGNMENT.match(item.value):
            return item.value
    return options[-1] if options else DYNAMIC


def sudo_verbs(source: str) -> set[str]:
    """The verbs of every list, tuple or call whose argv starts with `sudo`, and of `_sudo(t, verb, ...)` calls."""
    verbs = set()
    for node in ast.walk(ast.parse(source)):
        items = node.elts if isinstance(node, ast.List | ast.Tuple) else node.args if isinstance(node, ast.Call) else []
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_sudo":
            verbs.add(_verb(node.args[1:]))
        elif items and isinstance(items[0], ast.Constant) and items[0].value == "sudo":
            verbs.add(_verb(items[1:]))
    return verbs


def unapproved_sudo(module: str, source: str) -> list[str]:
    """Sudo uses a module may not make: any use outside the exempt set, or an undeclared verb or `sudo <write verb>` string inside it."""
    if module not in PRIVILEGED_MODULES:
        return [f"line {line}" for line in sudo_uses(source)]
    allowed = PRIVILEGED_MODULES[module][1]
    strings = [n.value for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    written = [s for s in strings if SUDO_WRITE.search(s)]
    return sorted(sudo_verbs(source) - allowed) + written


@pytest.mark.parametrize(("source", "expected"), [
    ('t.run(["sudo", "dpkg", "-i", deb])', {"dpkg"}),
    ('t.run(["sudo", "-n", "install", a, b])', {"install"}),
    ('ctx.quiet("sudo", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install")', {"apt-get"}),
    ('_sudo(t, "cp", "-r", a, b)', {"cp"}),
    ('_sudo(t, *link)', {"*"}),
    ('t.run(["sudo", "-v"])', {"-v"}),
    ('x = ("sudo", "timeout", "45", "add-apt-repository")', {"timeout"}),
    ('t.run(["dpkg", "-i", deb])', set()),
])
def test_the_verb_extraction_reads_what_sudo_runs(source, expected):
    assert sudo_verbs(source) == expected


@pytest.mark.parametrize(("module", "source"), [
    ("apt_packages.py", 't.run(["sudo", "install", a, "/usr/local/bin"])'),
    ("apt_packages.py", 't.run(["sudo", "-n", "cp", a, b])'),
    ("deb_helpers.py", 't.run(["sudo", "tee", path])'),
    ("removals.py", 'ctx.quiet("sudo", "apt-get", "remove", name); ctx.quiet("sudo", "mv", a, b)'),
    ("desktop_defaults.py", 't.run(["bash", "-c", "sudo install a /usr/local/bin"])'),
    ("antigravity.py", '_sudo(t, "rsync", a, b)'),
])
def test_an_exempt_module_is_still_caught_on_a_verb_it_did_not_declare(module, source):
    assert unapproved_sudo(module, source) != []


@pytest.mark.parametrize(("module", "source"), [
    ("apt_packages.py", 't.run(["sudo", "dpkg", "-i", deb]); t.run(["sudo", "rm", "-f", p])'),
    ("antigravity.py", '_sudo(t, "cp", "--", a, b); _sudo(t, *link)'),
])
def test_an_exempt_module_may_use_its_declared_verbs(module, source):
    assert unapproved_sudo(module, source) == []


def test_every_exempt_module_uses_only_its_declared_verbs():
    modules = _modules()
    offenders = {n: unapproved_sudo(n, modules[n].read_text(encoding="utf-8")) for n in PRIVILEGED_MODULES}
    assert {n: bad for n, bad in offenders.items() if bad} == {}


def test_every_declared_verb_is_still_used():
    modules = _modules()
    stale = {n: sorted(v - sudo_verbs(modules[n].read_text(encoding="utf-8"))) for n, (_, v) in PRIVILEGED_MODULES.items()}
    assert {n: verbs for n, verbs in stale.items() if verbs} == {}


def test_every_declared_privileged_module_still_uses_sudo():
    modules = _modules()
    assert [n for n in PRIVILEGED_MODULES if n not in modules or not sudo_uses(modules[n].read_text())] == []
