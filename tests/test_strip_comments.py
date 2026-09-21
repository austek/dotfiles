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
