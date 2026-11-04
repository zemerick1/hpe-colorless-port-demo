"""Keep the poller off and point tests at a throwaway database."""

import os

os.environ["COLORLESS_POLL"] = "0"

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "colorless.db"


@pytest.fixture
def client(db_path):
    app = create_app(db_path)
    with TestClient(app) as test_client:
        yield test_client
