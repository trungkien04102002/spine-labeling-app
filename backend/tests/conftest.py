"""Test-wide settings that must not come from whoever's machine runs them."""

import pytest


@pytest.fixture(autouse=True)
def _no_admin_lock_from_the_local_env(monkeypatch):
    """Keep a developer's .env passphrase out of the test suite.

    Settings() reads backend/.env, so setting ADMIN_PASSWORD there to use the
    app locally locked every operator route under test and failed 21 tests
    that have nothing to do with the lock. An environment variable outranks
    the .env file, so blanking it here restores "no lock" for every test;
    the tests that are about the lock pass their own Settings(admin_password=...).
    """
    monkeypatch.setenv("ADMIN_PASSWORD", "")
