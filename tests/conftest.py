import os
from pathlib import Path

import pytest


@pytest.fixture
def appdata_tmp(tmp_path, monkeypatch):
    root = tmp_path / "AppData"
    root.mkdir()
    monkeypatch.setenv("APPDATA", str(root))
    return root
