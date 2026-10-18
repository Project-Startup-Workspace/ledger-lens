"""Smoke test that the package imports."""

import ledger_lens


def test_package_imports() -> None:
    assert ledger_lens.__doc__
