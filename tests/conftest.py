from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session")
def pg() -> str:
    dsn = os.environ.get("SFM_TEST_DSN")
    if not dsn:
        pytest.skip("set SFM_TEST_DSN to a scratch PostgreSQL database to run the validation tests")
    return dsn
