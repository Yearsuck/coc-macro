import hashlib
from pathlib import Path

import pytest

import cocmacro
from cocmacro import updater

GOOD_URL = "https://github.com/Yearsuck/coc-macro/releases/download/v0.2.0/CoCMacro.exe"
SHA = "a" * 64


def release(tag="v0.2.0", url=GOOD_URL, digest=f"sha256:{SHA}", body="", draft=False,
            prerelease=False, name="CoCMacro.exe"):
    asset = {"name": name, "browser_download_url": url, "size": 123}
    if digest is not None:
        asset["digest"] = digest
    return {"tag_name": tag, "body": body, "draft": draft, "prerelease": prerelease, "assets": [asset]}


def test_version_matches_pyproject():
    text = (Path(__file__).parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    assert f'version = "{cocmacro.__version__}"' in text


@pytest.mark.parametrize("tag,expected", [("v0.1.0", (0, 1, 0)), ("1.2.3", (1, 2, 3)), ("v10.0.7", (10, 0, 7))])
def test_parse_version(tag, expected):
    assert updater.parse_version(tag) == expected


@pytest.mark.parametrize("bad", ["", "latest", "v1.2", "v1.2.x", "v1.2.3-beta"])
def test_parse_version_rejects(bad):
    with pytest.raises(ValueError):
        updater.parse_version(bad)


def test_is_newer():
    assert updater.is_newer("v0.2.0", "0.1.0") is True
    assert updater.is_newer("v0.10.0", "0.9.9") is True       # numeric, not alphabetical
    assert updater.is_newer("v0.1.0", "0.1.0") is False
    assert updater.is_newer("v0.0.9", "0.1.0") is False


def test_find_update_uses_asset_digest():
    info = updater.find_update(release(), "0.1.0")
    assert info == updater.UpdateInfo("0.2.0", GOOD_URL, SHA, 123, "")


def test_find_update_falls_back_to_hash_in_notes():
    body = f"Notes\n\nSHA-256: `{'b' * 64}`\n"
    info = updater.find_update(release(digest=None, body=body), "0.1.0")
    assert info.sha256 == "b" * 64


def test_no_update_when_not_newer_or_no_hash():
    assert updater.find_update(release(tag="v0.1.0"), "0.1.0") is None
    assert updater.find_update(release(digest=None, body="no hash here"), "0.1.0") is None


@pytest.mark.parametrize("kw", [
    {"url": "https://evil.example/CoCMacro.exe"},
    {"url": "http://github.com/Yearsuck/coc-macro/releases/download/v0.2.0/CoCMacro.exe"},
    {"url": "https://github.com/someone-else/coc-macro/releases/download/v0.2.0/CoCMacro.exe"},
    {"name": "other.exe"},
    {"draft": True},
    {"prerelease": True},
    {"tag": "latest"},
])
def test_find_update_refuses_untrusted_or_unfit_releases(kw):
    assert updater.find_update(release(**kw), "0.1.0") is None


def test_check_uses_injected_fetch():
    calls = []
    info = updater.check("0.1.0", fetch_json=lambda url: calls.append(url) or release())
    assert calls == [updater.API_URL]
    assert info.version == "0.2.0"


def make_info(data: bytes) -> updater.UpdateInfo:
    return updater.UpdateInfo("0.2.0", GOOD_URL, hashlib.sha256(data).hexdigest(), len(data), "")


def test_download_verifies_hash(tmp_path):
    data = b"new exe bytes"
    dest = tmp_path / "CoCMacro.new.exe"
    seen = []
    updater.download(make_info(data), dest, fetch_to=lambda url, p, cb: (p.write_bytes(data), cb(len(data))),
                     progress=seen.append)
    assert dest.read_bytes() == data and seen == [len(data)]


def test_download_deletes_file_on_hash_mismatch(tmp_path):
    dest = tmp_path / "CoCMacro.new.exe"
    with pytest.raises(updater.UpdateError):
        updater.download(make_info(b"expected"), dest,
                         fetch_to=lambda url, p, cb: p.write_bytes(b"tampered"))
    assert not dest.exists()


def test_apply_swaps_files_and_launches(tmp_path):
    cur, new = tmp_path / "CoCMacro.exe", tmp_path / "CoCMacro.new.exe"
    cur.write_bytes(b"old")
    new.write_bytes(b"new")
    launched = []
    updater.apply_update(new, cur, launch=lambda path: launched.append(path))
    assert cur.read_bytes() == b"new"
    assert (tmp_path / "CoCMacro.old.exe").read_bytes() == b"old"
    assert not new.exists() and launched == [cur]


def test_apply_rolls_back_if_swap_fails(tmp_path):
    cur, new = tmp_path / "CoCMacro.exe", tmp_path / "CoCMacro.new.exe"
    cur.write_bytes(b"old")                      # the new file is missing: second step fails
    with pytest.raises(updater.UpdateError):
        updater.apply_update(new, cur, launch=lambda p: None)
    assert cur.read_bytes() == b"old"
    assert not (tmp_path / "CoCMacro.old.exe").exists()


def test_cleanup_old_removes_leftovers(tmp_path):
    cur = tmp_path / "CoCMacro.exe"
    cur.write_bytes(b"x")
    (tmp_path / "CoCMacro.old.exe").write_bytes(b"o")
    (tmp_path / "CoCMacro.new.exe").write_bytes(b"n")
    updater.cleanup_old(cur)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["CoCMacro.exe"]
