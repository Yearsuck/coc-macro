import tkinter as tk

import pytest


@pytest.fixture(scope="session")
def tk_root():
    """One Tk root for the whole run: creating a second one after destroying the first fails at random on
    Windows, which used to skip every GUI test of the later module."""
    try:
        root = tk.Tk()
    except tk.TclError as e:
        pytest.skip(f"no display: {e}")
    yield root
    root.destroy()
