"""Where the app keeps its settings, templates and recordings."""
import sys
from pathlib import Path


def data_dir() -> Path:
    """Next to the .exe when packaged; ./data when run from source."""
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()
    return base / "data"
