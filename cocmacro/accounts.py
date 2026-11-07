"""Accounts registry and multi-account config management."""
import copy
import json
import re
from pathlib import Path
from typing import Any

from cocmacro import config
from cocmacro.config import Config

MAX_ACCOUNTS = 4
REGISTRY_FILE = "accounts.json"
FIRST_FILE = "config.json"


def valid_file_name(name: Any) -> bool:
    """True if name is a str matching config.json or config_<n>.json."""
    if not isinstance(name, str):
        return False
    return re.fullmatch(r"config(_\d+)?\.json", name) is not None


def load_registry(data_dir: Path) -> list[str]:
    """Read data_dir/accounts.json, ensuring config.json is first and valid, capped at MAX_ACCOUNTS."""
    path = Path(data_dir) / REGISTRY_FILE
    if not path.is_file():
        return [FIRST_FILE]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return [FIRST_FILE]
    if not isinstance(raw, list):
        return [FIRST_FILE]

    seen: set[str] = set()
    valid_files: list[str] = []
    for item in raw:
        if valid_file_name(item) and item not in seen:
            seen.add(item)
            valid_files.append(item)

    if FIRST_FILE not in seen:
        valid_files.insert(0, FIRST_FILE)
    elif valid_files[0] != FIRST_FILE:
        valid_files.remove(FIRST_FILE)
        valid_files.insert(0, FIRST_FILE)

    return valid_files[:MAX_ACCOUNTS]


def save_registry(data_dir: Path, files: list[str]) -> None:
    """Save the list of account config files to data_dir/accounts.json."""
    d = Path(data_dir)
    d.mkdir(parents=True, exist_ok=True)
    (d / REGISTRY_FILE).write_text(json.dumps(list(files), indent=2), encoding="utf-8")


def account_index(file: str) -> int:
    """Extract numeric index: config.json -> 1, config_3.json -> 3."""
    if file == FIRST_FILE:
        return 1
    m = re.fullmatch(r"config_(\d+)\.json", file)
    if m:
        return int(m.group(1))
    raise ValueError(f"Nombre de archivo de cuenta invalido: '{file}'")


def next_file(data_dir: Path, files: list[str]) -> str:
    """Next config_<n>.json using 1 + max index from files and disk, at least 2."""
    indices = [1]
    for f in files:
        if valid_file_name(f):
            indices.append(account_index(f))
    d = Path(data_dir)
    if d.is_dir():
        for p in d.iterdir():
            if p.is_file() and valid_file_name(p.name):
                indices.append(account_index(p.name))
    n = max(2, max(indices) + 1)
    return f"config_{n}.json"


def account_config(base: Config) -> Config:
    """Create a new Config with calibration copied from base and defaults for all other fields."""
    cfg = Config()
    cfg.buttons = copy.deepcopy(base.buttons)
    cfg.regions = copy.deepcopy(base.regions)
    cfg.tpl_size = copy.deepcopy(base.tpl_size)
    cfg.aspect = copy.deepcopy(base.aspect)
    return cfg


def add_account(data_dir: Path) -> tuple[str, Config]:
    """Add a new account copying calibration from config.json, returning (filename, cfg)."""
    d = Path(data_dir)
    files = load_registry(d)
    if len(files) >= MAX_ACCOUNTS:
        raise ValueError("max accounts")
    base = config.load(d / FIRST_FILE)
    filename = next_file(d, files)
    target_path = d / filename
    if target_path.exists():
        raise FileExistsError(f"{filename} ya existe")
    cfg = account_config(base)
    config.save(cfg, target_path)
    files.append(filename)
    save_registry(d, files)
    return filename, cfg


def remove_account(data_dir: Path, file: str) -> list[str]:
    """Remove file from registry while keeping it on disk. config.json cannot be removed."""
    if file == FIRST_FILE:
        raise ValueError("No se puede eliminar la cuenta principal (config.json)")
    d = Path(data_dir)
    files = load_registry(d)
    if file not in files:
        raise ValueError(f"La cuenta '{file}' no esta en el registro")
    files.remove(file)
    save_registry(d, files)
    return files


def account_name_from_title(title: str, fallback: str) -> str:
    """Extract player name from 'Clash of Clans - <name>' or return fallback."""
    if not title.startswith("Clash of Clans"):
        return fallback
    if " - " not in title:
        return fallback
    name = title.split(" - ", 1)[1].strip()
    return name if name else fallback


def debug_dir(data_dir: Path, file: str) -> Path:
    """Return data_dir/debug/<account_index>."""
    return Path(data_dir) / "debug" / str(account_index(file))
