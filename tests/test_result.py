from dotfiles_setup.result import Err, Ok


def test_ok_map_transforms_value():
    assert Ok(2).map(lambda n: n + 1) == Ok(3)


def test_ok_and_then_chains_results():
    assert Ok(2).and_then(lambda n: Ok(n * 5)) == Ok(10)
    assert Ok(2).and_then(lambda n: Err("bad")) == Err("bad")


def test_err_short_circuits_map_and_and_then():
    err = Err("boom")
    assert err.map(lambda n: n + 1) is err
    assert err.and_then(lambda n: Ok(n)) is err
