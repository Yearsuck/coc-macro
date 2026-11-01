import sys

from cocmacro import paths


def test_data_dir_from_source_uses_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert paths.data_dir() == tmp_path / "data"


def test_data_dir_frozen_is_next_to_exe(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "CoCMacro.exe"))
    monkeypatch.chdir(tmp_path.parent)           # launched from somewhere else
    assert paths.data_dir() == tmp_path / "data"
