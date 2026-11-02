import pytest

from telltale.core.library import Library


@pytest.fixture
def library(tmp_path, monkeypatch):
    # A fresh, empty library in a temporary folder for each test.
    monkeypatch.setenv("TELLTALE_DATA_DIR", str(tmp_path / "data"))
    return Library()


@pytest.fixture
def videos(tmp_path):
    d = tmp_path / "videos"
    d.mkdir()
    return d
