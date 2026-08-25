from waypoint.state_machine import CompanionController, CompanionState


def test_starts_idle():
    controller = CompanionController()
    assert controller.state == CompanionState.IDLE


def test_press_while_idle_moves_to_listening():
    controller = CompanionController()
    controller.on_hotkey_press()
    assert controller.state == CompanionState.LISTENING


def test_release_while_listening_moves_to_processing():
    controller = CompanionController()
    controller.on_hotkey_press()
    controller.on_hotkey_release(b"audio-bytes")
    assert controller.state == CompanionState.PROCESSING


def test_release_while_busy_enqueues_instead_of_processing():
    controller = CompanionController()
    controller.on_hotkey_press()
    controller.on_hotkey_release(b"first")  # -> PROCESSING
    controller.on_hotkey_press()
    controller.on_hotkey_release(b"second")  # busy -> enqueued
    assert controller.state == CompanionState.PROCESSING
    assert list(controller._queue) == [b"second"]


def test_finish_turn_returns_to_idle_when_queue_empty():
    controller = CompanionController()
    controller.on_hotkey_press()
    controller.on_hotkey_release(b"only")
    controller.start_responding()
    next_buffer = controller.finish_turn()
    assert next_buffer is None
    assert controller.state == CompanionState.IDLE


def test_finish_turn_drains_queue_in_order():
    controller = CompanionController()
    controller.on_hotkey_press()
    controller.on_hotkey_release(b"first")
    controller.on_hotkey_press()
    controller.on_hotkey_release(b"second")
    controller.start_responding()
    next_buffer = controller.finish_turn()
    assert next_buffer == b"second"
    assert controller.state == CompanionState.PROCESSING
