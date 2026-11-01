"""Global hotkeys: F8 emergency stop, F9 end deployment recording."""
from typing import Callable

from pynput import keyboard


def start(on_stop: Callable[[], None], on_end_record: Callable[[], None],
          listener_factory=keyboard.GlobalHotKeys) -> Callable[[], None]:
    listener = listener_factory({"<f8>": on_stop, "<f9>": on_end_record})
    listener.start()
    return listener.stop
