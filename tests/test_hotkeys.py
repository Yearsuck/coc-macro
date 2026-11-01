from cocmacro import hotkeys


class FakeListener:
    def __init__(self, mapping):
        self.mapping = mapping
        self.stopped = False

    def start(self):
        pass

    def stop(self):
        self.stopped = True


def test_hotkeys_calls_stop_and_end_record():
    calls, made = [], []

    def factory(mapping):
        made.append(FakeListener(mapping))
        return made[-1]

    unregister = hotkeys.start(lambda: calls.append("stop"), lambda: calls.append("end"),
                               listener_factory=factory)
    made[0].mapping["<f8>"]()
    made[0].mapping["<f9>"]()
    assert calls == ["stop", "end"]
    unregister()
    assert made[0].stopped is True
