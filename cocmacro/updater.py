"""Update from GitHub releases.

Trust model: the download URL must be an asset of this repo's releases over https and the file
must match the SHA-256 GitHub publishes for it (asset digest, or the hash in the release notes).
That detects corruption and a swapped file; it does not defend against a compromised GitHub
account, so nothing is ever installed without the user saying yes.
"""
import hashlib
import json
import os
import re
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

REPO = "Yearsuck/coc-macro"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
ASSET_NAME = "CoCMacro.exe"
TIMEOUT = 15
_HASH = re.compile(r"[0-9a-f]{64}")


class UpdateError(Exception):
    pass


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    url: str
    sha256: str
    size: int | None
    notes: str


def parse_version(tag: str) -> tuple[int, int, int]:
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", tag.strip())
    if not m:
        raise ValueError(f"Version invalida: '{tag}'")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def is_newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def _sha_for(asset: dict, body: str) -> str | None:
    digest = str(asset.get("digest") or "")
    if digest.startswith("sha256:") and _HASH.fullmatch(digest[7:].lower()):
        return digest[7:].lower()
    m = re.search(r"SHA-256:\s*`?([0-9a-fA-F]{64})`?", body or "")
    return m.group(1).lower() if m else None


def find_update(release: dict, current: str) -> UpdateInfo | None:
    """Pure decision over a GitHub 'latest release' payload."""
    if release.get("draft") or release.get("prerelease"):
        return None
    tag = str(release.get("tag_name", ""))
    try:
        if not is_newer(tag, current):
            return None
    except ValueError:
        return None
    for asset in release.get("assets", []):
        url = str(asset.get("browser_download_url", ""))
        if asset.get("name") != ASSET_NAME or not url.startswith(DOWNLOAD_PREFIX):
            continue
        sha = _sha_for(asset, release.get("body", ""))
        if sha:
            return UpdateInfo(tag.lstrip("v"), url, sha, asset.get("size"), release.get("body", ""))
    return None


def _http_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "CoCMacro-updater",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.load(r)


def _http_download(url: str, dest: Path, progress: Callable[[int], None]) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "CoCMacro-updater"})
    done = 0
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r, open(dest, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
            done += len(chunk)
            progress(done)


def check(current: str, fetch_json: Callable[[str], dict] = _http_json) -> UpdateInfo | None:
    return find_update(fetch_json(API_URL), current)


def download(info: UpdateInfo, dest: Path, fetch_to=_http_download,
             progress: Callable[[int], None] | None = None) -> Path:
    dest = Path(dest)
    fetch_to(info.url, dest, progress or (lambda n: None))
    if hashlib.sha256(dest.read_bytes()).hexdigest() != info.sha256:
        dest.unlink(missing_ok=True)
        raise UpdateError("La descarga no coincide con el hash publicado; no se instala")
    return dest


def _sibling(exe: Path, tag: str) -> Path:
    return exe.with_name(f"{exe.stem}.{tag}{exe.suffix}")


def new_path_for(current_exe: Path) -> Path:
    return _sibling(Path(current_exe), "new")


def _launch(path: Path) -> None:
    env = {**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"}   # let the new onefile exe unpack itself
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([str(path)], env=env, close_fds=True, creationflags=flags)


def apply_update(new_exe: Path, current_exe: Path, launch: Callable[[Path], None] = _launch) -> None:
    """A running exe can be renamed but not overwritten: move it aside, put the new one in place."""
    new_exe, current_exe = Path(new_exe), Path(current_exe)
    old = _sibling(current_exe, "old")
    old.unlink(missing_ok=True)
    os.replace(current_exe, old)
    try:
        os.replace(new_exe, current_exe)
    except OSError as e:
        os.replace(old, current_exe)
        raise UpdateError(f"No se pudo instalar la actualizacion: {e}") from e
    launch(current_exe)


def cleanup_old(current_exe: Path) -> None:
    for tag in ("old", "new"):
        try:
            _sibling(Path(current_exe), tag).unlink(missing_ok=True)
        except OSError:
            pass
