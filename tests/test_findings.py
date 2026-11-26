from dotfiles_setup.findings import CheckOutcome, Finding


def test_finding_is_fixable_only_with_commands():
    assert Finding("c", "t", commands=(("a", "b"),)).fixable
    assert not Finding("c", "t", advice="rm x").fixable


def test_to_dict_uses_lists_for_json():
    f = Finding("c", "t", affects=("p",), commands=(("a", "b"),), advice="x")
    assert f.to_dict() == {"check": "c", "text": "t", "affects": ["p"], "commands": [["a", "b"]], "advice": "x"}


def test_outcome_defaults_to_nothing_found_and_not_skipped():
    assert CheckOutcome() == CheckOutcome(findings=(), skipped=None)
