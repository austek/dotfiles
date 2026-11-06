from dotfiles_setup.package_sets import pending_removals, stale_optouts, wanted

ALIASES = {"batcat": "bat"}


def resolve(name: str) -> str:
    return ALIASES.get(name, name)


def test_wanted_subtracts_resolved_optout():
    assert wanted(("bat", "jq"), {"batcat"}, resolve) == frozenset({"jq"})


def test_pending_none_applied_is_empty():
    assert pending_removals(None, {"a"}) == ()


def test_pending_is_applied_minus_wanted():
    assert pending_removals(("a", "b", "c"), {"b"}) == ("a", "c")


def test_stale_optouts_reports_unlisted():
    assert stale_optouts({"batcat", "gone"}, ("bat", "jq"), resolve) == ("gone",)
