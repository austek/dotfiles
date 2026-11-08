"""Characterization table: what each Claude Code hook decides for the same command, end to end.

Each row is (command, block-dangerous-rm verdict, allow-compound-bash verdict). The hooks run as
subprocesses with a throwaway HOME so the table never reads the real ~/.claude/settings.json.
A refactor must leave every row unchanged; a hardening change edits the rows it changes.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parent.parent / "claude" / ".claude" / "hooks"
SETTINGS = {
    "permissions": {
        "allow": ["Bash(git *)", "Bash(gh *)", "Bash(find *)", "Bash(xargs *)"],
        "deny": ["Bash(git push * main*)"],
    },
}

VERDICTS = [
    ("ls | grep foo && echo done", "none", "allow"),
    ("git status && git diff", "none", "allow"),
    ("git status; echo =====; git diff", "none", "allow"),
    ("git push origin main", "none", "none"),
    ("echo hi > /tmp/out.txt", "none", "allow"),
    ("echo hi > ~/file", "none", "none"),
    ("cat README.md | head -5", "none", "allow"),
    ("cat ~/.ssh/id_rsa", "none", "none"),
    ("cat ~/.config/gcloud/credentials.db", "none", "none"),
    ("sort ~/.config/gcloud/credentials.db", "none", "none"),
    ("cut -c1-5 ~/.docker/config.json", "none", "none"),
    ("cat .dockerignore", "none", "allow"),
    ("cat ~/.config/gh/hosts.yml", "none", "none"),
    ("cat /etc/shadow", "none", "none"),
    ("cat ~/.docker/config.json", "none", "none"),
    ("cat ~/.kube/config", "none", "none"),
    ("cat ~/.local/share/keyrings/login.keyring", "none", "none"),
    ("jq -f /etc/passwd x.json", "none", "none"),
    ("jq -nf prog.jq", "none", "none"),
    ("jq --rawfile x /etc/passwd .", "none", "none"),
    ("jq --arg a b .a x.json", "none", "allow"),
    ("jq . x.json", "none", "allow"),
    ("grep -f /etc/shadow x && ls", "none", "none"),
    ("grep foo bar.txt", "none", "allow"),
    ("sort -o out.txt in.txt", "none", "none"),
    ("date -s '2020-01-01'", "none", "none"),
    ("printf -v x hi", "none", "none"),
    ("find . -name '*.py' -delete", "none", "none"),
    ("find . -name '*.py' -exec rm {} \\;", "none", "none"),
    ("xargs rm < files.txt", "none", "none"),
    ("for f in a b; do echo $f; done", "none", "none"),
    ("FOO=bar ls", "none", "none"),
    ("PATH=/tmp ls", "none", "none"),
    ("echo $(ls)", "none", "allow"),
    ("echo $((1+2))", "none", "none"),
    ("echo `ls`", "none", "none"),
    ("cat <<EOF\nhi\nEOF", "none", "none"),
    ("echo $'a\\nb'", "none", "none"),
    ("echo ${HOME}", "none", "none"),
    ("echo ${x@P}", "none", "none"),
    ("echo {a,b}", "none", "none"),
    ("echo {1..3}", "none", "none"),
    ("git log --format='{a,b}'", "none", "allow"),
    ('git commit -m "fix {a,b}"', "none", "allow"),
    ("git log ${BASE}..HEAD", "none", "allow"),
    ("git log $BASE..HEAD", "none", "allow"),
    ("git log \\{a,b\\}", "none", "allow"),
    ("{ ls; }", "none", "none"),
    ("ls; { echo hi; }", "none", "none"),
    ('echo "$(cat ~/.ssh/id_rsa)"', "none", "none"),
    ("ls ~/.ssh", "none", "none"),
    ("wc -l *.py", "none", "none"),
    ("cat /etc/pas*", "none", "none"),
    ("./gradlew test --tests Foo", "none", "allow"),
    ("./gradlew build", "none", "none"),
    ("rm -rf /", "deny", "none"),
    ("rm -rf ~", "deny", "none"),
    ("rm -rf ~/", "deny", "none"),
    ("rm -rf $HOME", "deny", "none"),
    ('rm -rf "$VAR"/*', "deny", "none"),
    ("rm -rf /home/user", "deny", "none"),
    ("rm -rf /home/user/.ssh", "deny", "none"),
    ("rm -rf ~/.ssh", "deny", "none"),
    ("rm -rf ~/Workspace", "deny", "none"),
    ("rm -rf ~/Workspace/project", "none", "none"),
    ("rm -rf ~/.cache/pip", "none", "none"),
    ("rm -rf ~/.config", "deny", "none"),
    ("rm -rf ~/.gnupg", "deny", "none"),
    ("rm -rf /home/user/Documents", "deny", "none"),
    ("rm -rf /home/user/Documents/old", "none", "none"),
    *[
        (f"rm -rf {root}/{name}", "deny", "none")
        for root in ("/home/user", "/root", "~", "~root")
        for name in (
            ".ssh", ".gnupg", ".aws", ".kube", ".docker", ".config", ".local", ".claude", ".dotfiles",
            ".dotfiles-private", "Workspace", "Documents", "Desktop", "Pictures", "Music", "Videos",
        )
    ],
    ("rm -rf /root/.cache/x", "none", "none"),
    ("rm -rf ~/scratchpad", "none", "none"),
    ("rm -rf ~root", "deny", "none"),
    ("rm -rf ~/Work*", "deny", "none"),
    ("rm -rf ~/.ss?", "deny", "none"),
    ("rm -rf ~/{Workspace,x}", "deny", "none"),
    ("rm -rf $TMPDIR/../x", "deny", "none"),
    ("git clean -x", "deny", "allow"),
    ("git clean -fdx\ngit clean -n", "deny", "allow"),
    ("git clean -fdx & git clean -n", "deny", "none"),
    ("git clean -fdx -e -n", "deny", "allow"),
    ("git clean -fdxe -n", "deny", "allow"),
    ("git clean -fdx # -n", "deny", "allow"),
    ("git clean -fdx --exclude=a", "deny", "allow"),
    ("git -c clean.requireForce=0 clean -dx", "deny", "allow"),
    ("sudo git clean -fdx", "deny", "none"),
    ("GIT_DIR=x git clean -fdx", "deny", "none"),
    ("git clean -fdx -- -n", "deny", "allow"),
    ("echo a\\ #; rm -rf ~/.ssh", "deny", "none"),
    ("echo a\\ # b\nrm -rf ~/.ssh", "deny", "none"),
    ("echo $'it\\'s'\nrm -rf ~/Documents # '", "deny", "none"),
    ("echo hi # rm -rf ~/.ssh", "none", "allow"),
    ("echo $'a\\'b'; rm -rf ~/Documents", "deny", "none"),
    ("IFS=$'\\t' read -r a b; rm file.txt", "none", "none"),
    ("git checkout -q -- . && git clean -fdq && IFS=$'\\t' read -r a", "none", "none"),
    ("env -u FOO git clean -fdx", "deny", "none"),
    ("timeout 5 git clean -fdx", "deny", "none"),
    ("timeout -s KILL 5 git clean -fdx", "deny", "none"),
    ("sudo -u root git clean -fdx", "deny", "none"),
    ("git --config-env clean.requireForce=X clean -fdx", "deny", "allow"),
    ("git --config-env=clean.requireForce=X clean -fdx", "deny", "allow"),
    ("git clean -fdx --excl -n", "deny", "allow"),
    ("git clean -fdx --ex=-n", "deny", "allow"),
    ("git clean -fdx --dry", "none", "allow"),
    ("git clean --dry-run -fdx", "none", "allow"),
    ("git clean -n -fdx --no-dry-run", "deny", "allow"),
    ("git clean -n -x", "none", "allow"),
    ("git clean -nfdx -e a", "none", "allow"),
    ("git clean -fd", "none", "allow"),
    ("echo git clean -fdx", "none", "allow"),
    ("git log --grep='git clean -fdx'", "none", "allow"),
    ("ls\n# git clean -fdx\nls", "none", "allow"),
    ("git status\nrm -rf /", "deny", "none"),
    ("sleep 1 & rm -rf /", "deny", "none"),
    ("echo 'a\nrm -rf b'", "none", "allow"),
    ("echo $#", "none", "none"),
    ("echo ${#x}", "none", "none"),
    ("/usr/bin/git clean -fdx", "deny", "none"),
    ("git -c clean.requireForce=false clean -dx", "deny", "allow"),
    ("rm -rf ./build", "none", "none"),
    ("rm -rf /tmp/x", "none", "none"),
    ("rm -rf .", "deny", "none"),
    ("rm -rf ..", "deny", "none"),
    ("rm -rf *", "none", "none"),
    ("rm -rf /etc", "deny", "none"),
    ("rm -rf /var/lib/foo", "none", "none"),
    ("rm -r -f /usr", "deny", "none"),
    ("rm --recursive --force /opt", "deny", "none"),
    ("rm -rf $(pwd)", "deny", "none"),
    ("rm -rf `pwd`", "deny", "none"),
    ("echo x | xargs rm -rf", "deny", "none"),
    ('bash -c "rm -rf /"', "deny", "none"),
    ("sudo rm -rf /", "deny", "none"),
    ("find / -delete", "deny", "none"),
    ("find ~ -delete", "deny", "none"),
    ("find . -delete", "none", "none"),
    ("git clean -fdx", "deny", "allow"),
    ("git clean -fdX", "deny", "allow"),
    ("git clean --force -dx", "deny", "allow"),
    ("git clean -x --force", "deny", "allow"),
    ("cat ~/.docker config.json", "none", "none"),
    ("git clean -f -d -x", "deny", "allow"),
    ("git clean -nfdx", "none", "allow"),
    ("git clean --dry-run -fdx", "none", "allow"),
    ("git clean -fd", "none", "allow"),
    ("git clean -n", "none", "allow"),
    ("git reset --hard", "none", "allow"),
    ("git checkout -- .", "none", "allow"),
    ("rm -f file.txt", "none", "none"),
    ("rm file.txt", "none", "none"),
    ("rm -rf 'unterminated", "deny", "none"),
    ("git push origin $'main'", "none", "none"),
    ('git push origin "main"', "none", "none"),
    ("git push origin ma\\in", "none", "none"),
    ("git log {a,b}", "none", "none"),
    ("git status ${x@P}", "none", "none"),
    ('git status "${x@P}"', "none", "none"),
    ("git log $'x'", "none", "none"),
    ('git log $"x"', "none", "none"),
    ("git -C ~/.ssh status", "none", "none"),
    ("echo ~root", "none", "allow"),
    ("cat ~/.s{s,}h/id_rsa", "none", "none"),
    ("cat ~/.ss?/id_rsa", "none", "none"),
    ("cat ~/x/../.ssh/id_rsa", "none", "none"),
    ("gh api user", "none", "allow"),
    ("gh auth token", "none", "allow"),
]


@pytest.fixture(scope="module")
def home(tmp_path_factory):
    path = tmp_path_factory.mktemp("home")
    (path / ".claude").mkdir()
    (path / ".claude" / "settings.json").write_text(json.dumps(SETTINGS))
    return path


def decide(hook, command, home):
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(home)})
    done = subprocess.run(
        [sys.executable, "-I", str(HOOKS / hook)], input=payload, capture_output=True, text=True,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"}, cwd=home, check=True,
    )
    return json.loads(done.stdout)["hookSpecificOutput"]["permissionDecision"] if done.stdout.strip() else "none"


@pytest.mark.parametrize(("command", "rm", "allow"), VERDICTS, ids=[row[0] for row in VERDICTS])
def test_each_hook_keeps_its_verdict(home, command, rm, allow):
    assert decide("block-dangerous-rm.py", command, home) == rm
    assert decide("allow-compound-bash.py", command, home) == allow
