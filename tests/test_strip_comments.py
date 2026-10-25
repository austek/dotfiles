from strip_comments import strip_comments, strip_hash_comments, strip_python_comments


def test_python_strips_standalone_and_inline_comments():
    source = "# header\nx = 1  # inline\n"
    assert strip_python_comments(source) == "\nx = 1\n"


def test_python_preserves_shebang():
    source = "#!/usr/bin/env python3\n# real comment\nx = 1\n"
    result = strip_python_comments(source)
    assert result.startswith("#!/usr/bin/env python3\n")
    assert "# real comment" not in result


def test_python_leaves_strings_and_docstrings_untouched():
    source = '"""Doc with # not a comment."""\nx = "# also not a comment"\n'
    assert strip_python_comments(source) == source


def test_python_returns_source_unchanged_on_syntax_error():
    source = "def broken(:\n"
    assert strip_python_comments(source) == source


def test_c_style_strips_line_and_block_comments():
    source = "a; // line\nb; /* block */ c;\n"
    result = strip_comments(source, "js")
    assert "//" not in result
    assert "/*" not in result
    assert "line" not in result
    assert "block" not in result


def test_c_style_block_comment_keeps_adjacent_tokens_separated():
    assert strip_comments("a/*x*/b;", "js") == "a b;"


def test_c_style_block_comment_preserves_newlines_inside_it():
    source = "foo();\n/* multi\nline */\nbar();\n"
    result = strip_comments(source, "js")
    assert result.count("\n") == source.count("\n")


def test_c_style_respects_strings_containing_comment_markers():
    source = 'x = "// not a comment";\n'
    assert strip_comments(source, "js") == source


def test_hash_style_strips_comments():
    source = "# header\necho hi # inline\n"
    result = strip_hash_comments(source)
    assert "header" not in result
    assert "inline" not in result
    assert "echo hi" in result


def test_hash_style_preserves_shebang():
    source = "#!/usr/bin/env bash\n# real comment\necho hi\n"
    result = strip_hash_comments(source)
    assert result.startswith("#!/usr/bin/env bash\n")
    assert "# real comment" not in result


def test_hash_style_respects_strings_containing_hash():
    source = 'echo "# not a comment"\n'
    assert strip_hash_comments(source) == source


def test_unknown_extension_passes_through_unchanged():
    source = "whatever content\n"
    assert strip_comments(source, "xyz") == source


def test_c_style_handles_escaped_quotes_in_strings():
    source = 'x = "a \\" // still string"; // gone\n'
    assert strip_comments(source, "js") == 'x = "a \\" // still string"; \n'


def test_c_style_rust_lifetime_does_not_open_a_string():
    source = "fn f<'a>(x: &'a str) {} // gone\nlet y = 1;\n"
    assert strip_comments(source, "rs") == "fn f<'a>(x: &'a str) {} \nlet y = 1;\n"


def test_c_style_char_literal_with_slashes_is_kept():
    assert strip_comments("c = '/'; // x\n", "java") == "c = '/'; \n"


def test_c_style_triple_quoted_string_is_kept():
    source = 'val s = """// not a comment"""\n'
    assert strip_comments(source, "kt") == source


def test_c_style_preserves_crlf_line_endings():
    assert strip_comments("a; // c\r\nb;\r\n", "js") == "a; \r\nb;\r\n"


def test_c_style_keeps_directive_comments():
    source = "//go:build linux\n// @ts-ignore\n//nolint:errcheck\n// plain\n"
    assert strip_comments(source, "go") == "//go:build linux\n// @ts-ignore\n//nolint:errcheck\n\n"


def test_python_keeps_directive_comments():
    source = "import os  # noqa: F401\nx = 1  # plain\ny: int = 2  # type: ignore\n"
    assert strip_python_comments(source) == "import os  # noqa: F401\nx = 1\ny: int = 2  # type: ignore\n"


def test_hash_style_keeps_shell_parameter_expansions():
    source = 'echo ${#arr[@]} $# ${v#pre} http://x/#frag # gone\n'
    assert strip_hash_comments(source) == 'echo ${#arr[@]} $# ${v#pre} http://x/#frag \n'


def test_hash_style_keeps_directive_comments():
    source = "# shellcheck disable=SC2016\necho 'x' # narrative\n# noqa: E501\n"
    assert strip_hash_comments(source) == "# shellcheck disable=SC2016\necho 'x' \n# noqa: E501\n"


def test_hash_style_respects_shell_escaped_quotes():
    for source in ("echo 'it'\\''s # x'\n", "echo $'a\\'b # c'\n", "echo \\# not a comment\n"):
        assert strip_hash_comments(source) == source


def test_c_style_block_comment_keeps_crlf_line_breaks():
    assert strip_comments("a /* x\r\ny */ b\r\n", "js") == "a  \r\n b\r\n"


def test_hash_style_preserves_crlf():
    assert strip_hash_comments("echo a # c\r\necho b\r\n") == "echo a \r\necho b\r\n"


def test_cli_reports_missing_file_without_traceback(tmp_path, capsys):
    import strip_comments as sc

    assert sc._strip_file(str(tmp_path / "missing.js")) == 1
    assert "missing.js" in capsys.readouterr().err


def test_cli_preserves_crlf_when_rewriting(tmp_path):
    import strip_comments as sc

    f = tmp_path / "a.js"
    f.write_bytes(b"a; // c\r\nb;\r\n")
    assert sc._strip_file(str(f)) == 0
    assert f.read_bytes() == b"a; \r\nb;\r\n"
