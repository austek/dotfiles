from collections.abc import Callable, Collection, Sequence


def wanted(
    combined: Sequence[str], optouts: Collection[str], resolve: Callable[[str], str]
) -> frozenset[str]:
    return frozenset(combined) - {resolve(o) for o in optouts}


def pending_removals(
    applied: Sequence[str] | None, wanted_names: Collection[str]
) -> tuple[str, ...]:
    if applied is None:
        return ()
    return tuple(sorted(set(applied) - set(wanted_names)))


def stale_optouts(
    optouts: Collection[str], combined: Sequence[str], resolve: Callable[[str], str]
) -> tuple[str, ...]:
    listed = set(combined)
    return tuple(sorted(o for o in optouts if resolve(o) not in listed))
