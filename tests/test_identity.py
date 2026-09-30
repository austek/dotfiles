from dotfiles_setup.identity import ensure_git_identity


def _fake_prompt(answers):
    def prompt(label):
        return answers[label]
    return prompt


def test_writes_gitconfig_local_from_prompted_values(tmp_path):
    target = tmp_path / ".gitconfig.local"
    prompt = _fake_prompt({
        "Git user.name: ": "Ada Lovelace",
        "Git user.email: ": "ada@example.com",
        "SSH signing key path (blank to skip commit signing): ": "",
    })
    result = ensure_git_identity(gitconfig_local=target, prompt=prompt)
    assert result == target
    text = target.read_text()
    assert "name = Ada Lovelace" in text
    assert "email = ada@example.com" in text


def test_skips_prompting_when_file_already_exists(tmp_path):
    target = tmp_path / ".gitconfig.local"
    target.write_text("[user]\n\tname = Existing\n\temail = existing@example.com\n")

    def prompt(label):
        raise AssertionError(f"should not prompt when file exists, asked: {label}")

    result = ensure_git_identity(gitconfig_local=target, prompt=prompt)
    assert result == target
    assert "Existing" in target.read_text()


def test_force_reprompts_even_when_file_exists(tmp_path):
    target = tmp_path / ".gitconfig.local"
    target.write_text("[user]\n\tname = Old\n\temail = old@example.com\n")
    prompt = _fake_prompt({
        "Git user.name: ": "New Name",
        "Git user.email: ": "new@example.com",
        "SSH signing key path (blank to skip commit signing): ": "",
    })
    ensure_git_identity(gitconfig_local=target, prompt=prompt, force=True)
    text = target.read_text()
    assert "New Name" in text
    assert "Old" not in text


def test_strips_whitespace_from_prompted_values(tmp_path):
    target = tmp_path / ".gitconfig.local"
    prompt = _fake_prompt({
        "Git user.name: ": "  Padded Name  ",
        "Git user.email: ": " pad@example.com ",
        "SSH signing key path (blank to skip commit signing): ": "",
    })
    ensure_git_identity(gitconfig_local=target, prompt=prompt)
    text = target.read_text()
    assert "name = Padded Name\n" in text
    assert "email = pad@example.com\n" in text


def test_writes_signing_block_only_when_signing_key_given(tmp_path):
    target = tmp_path / ".gitconfig.local"
    prompt = _fake_prompt({
        "Git user.name: ": "Ada Lovelace",
        "Git user.email: ": "ada@example.com",
        "SSH signing key path (blank to skip commit signing): ": "~/.ssh/id_ed25519.pub",
    })
    ensure_git_identity(gitconfig_local=target, prompt=prompt)
    text = target.read_text()
    assert "signingkey = ~/.ssh/id_ed25519.pub" in text
    assert "[commit]\n\tgpgsign = true\n[gpg]\n\tformat = ssh\n" in text


def test_omits_signing_block_when_signing_key_blank(tmp_path):
    target = tmp_path / ".gitconfig.local"
    prompt = _fake_prompt({
        "Git user.name: ": "Ada Lovelace",
        "Git user.email: ": "ada@example.com",
        "SSH signing key path (blank to skip commit signing): ": "",
    })
    ensure_git_identity(gitconfig_local=target, prompt=prompt)
    text = target.read_text()
    assert "signingkey" not in text
    assert "[commit]" not in text
    assert "[gpg]" not in text


def _unreachable_prompt(label):
    raise AssertionError(f"should not prompt when overlay provides identity, asked: {label}")


def test_symlinks_to_overlay_identity_without_prompting(tmp_path):
    target = tmp_path / ".gitconfig.local"
    overlay_root = tmp_path / "dotfiles-private"
    (overlay_root / "git").mkdir(parents=True)
    overlay_identity = overlay_root / "git" / "gitconfig.local"
    overlay_identity.write_text("[user]\n\tname = Overlay Name\n\temail = overlay@example.com\n")

    result = ensure_git_identity(gitconfig_local=target, prompt=_unreachable_prompt, overlay_root=overlay_root)
    assert result == target
    assert target.is_symlink()
    assert target.resolve() == overlay_identity.resolve()


def test_overlay_identity_replaces_existing_plain_file(tmp_path):
    target = tmp_path / ".gitconfig.local"
    target.write_text("[user]\n\tname = Stale\n\temail = stale@example.com\n")
    overlay_root = tmp_path / "dotfiles-private"
    (overlay_root / "git").mkdir(parents=True)
    overlay_identity = overlay_root / "git" / "gitconfig.local"
    overlay_identity.write_text("[user]\n\tname = Overlay Name\n\temail = overlay@example.com\n")

    ensure_git_identity(gitconfig_local=target, prompt=_unreachable_prompt, overlay_root=overlay_root)
    assert target.is_symlink()
    assert "Overlay Name" in target.read_text()


def test_overlay_identity_symlink_is_idempotent(tmp_path):
    target = tmp_path / ".gitconfig.local"
    overlay_root = tmp_path / "dotfiles-private"
    (overlay_root / "git").mkdir(parents=True)
    overlay_identity = overlay_root / "git" / "gitconfig.local"
    overlay_identity.write_text("[user]\n\tname = Overlay Name\n\temail = overlay@example.com\n")

    ensure_git_identity(gitconfig_local=target, prompt=_unreachable_prompt, overlay_root=overlay_root)
    ensure_git_identity(gitconfig_local=target, prompt=_unreachable_prompt, overlay_root=overlay_root)
    assert target.is_symlink()
    assert target.resolve() == overlay_identity.resolve()


def test_falls_back_to_prompt_when_overlay_lacks_identity_file(tmp_path):
    target = tmp_path / ".gitconfig.local"
    overlay_root = tmp_path / "dotfiles-private"
    overlay_root.mkdir()
    prompt = _fake_prompt({
        "Git user.name: ": "Ada Lovelace",
        "Git user.email: ": "ada@example.com",
        "SSH signing key path (blank to skip commit signing): ": "",
    })
    result = ensure_git_identity(gitconfig_local=target, prompt=prompt, overlay_root=overlay_root)
    assert not result.is_symlink()
    assert "Ada Lovelace" in result.read_text()
