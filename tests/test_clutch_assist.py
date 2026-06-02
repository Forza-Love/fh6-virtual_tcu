import time
from unittest.mock import MagicMock, call

import pytest
from virtual_tcu.config.store import ConfigStore
from virtual_tcu.input.gamepad_output import GamepadOutput
from virtual_tcu.input.keyboard_output import KeyboardOutput
from virtual_tcu.state.shift_history import ShiftHistory
from virtual_tcu.telemetry.model import Telemetry


@pytest.fixture
def mock_keyboard(monkeypatch):
    mock_press = MagicMock()
    mock_release = MagicMock()
    monkeypatch.setattr("keyboard.press", mock_press)
    monkeypatch.setattr("keyboard.release", mock_release)
    monkeypatch.setattr("time.sleep", MagicMock())
    return mock_press, mock_release


def test_keyboard_output_no_clutch(mock_keyboard):
    mock_press, mock_release = mock_keyboard
    config = ConfigStore()
    config.set("feat_clutch_assist", False)
    config.set("shift_key_up", "e")

    kb = KeyboardOutput(config)
    kb._press_release_bare = kb._press_release  # Store original method
    kb._press_release("e")

    mock_press.assert_called_once_with("e")
    mock_release.assert_called_once_with("e")


def test_keyboard_output_with_clutch(mock_keyboard):
    mock_press, mock_release = mock_keyboard
    config = ConfigStore()
    config.set("feat_clutch_assist", True)
    config.set("clutch_key", "shift")

    kb = KeyboardOutput(config)
    kb._press_release_with_clutch("e")

    assert mock_press.call_args_list == [call("shift"), call("e")]
    assert mock_release.call_args_list == [call("e"), call("shift")]
    assert kb.is_self_press("shift")
    assert kb.is_self_press("e")


@pytest.fixture
def mock_vgamepad(monkeypatch):
    import sys

    mock_pad = MagicMock()
    mock_class = MagicMock(return_value=mock_pad)

    mock_vg = MagicMock()
    mock_vg.VX360Gamepad = mock_class
    # Provide necessary constants for the button map
    mock_vg.XUSB_BUTTON.XUSB_GAMEPAD_A = 0x1000
    mock_vg.XUSB_BUTTON.XUSB_GAMEPAD_B = 0x2000
    mock_vg.XUSB_BUTTON.XUSB_GAMEPAD_X = 0x4000
    mock_vg.XUSB_BUTTON.XUSB_GAMEPAD_Y = 0x8000
    mock_vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER = 0x0100
    mock_vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER = 0x0200
    mock_vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP = 0x0001
    mock_vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN = 0x0002
    mock_vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT = 0x0004
    mock_vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT = 0x0008
    mock_vg.XUSB_BUTTON.XUSB_GAMEPAD_START = 0x0010
    mock_vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK = 0x0020
    mock_vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB = 0x0040
    mock_vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB = 0x0080

    monkeypatch.setitem(sys.modules, "vgamepad", mock_vg)
    monkeypatch.setattr("virtual_tcu.input.gamepad_output.time.sleep", MagicMock())

    # Force rebuild of the button map using the mocked vgamepad
    from virtual_tcu.input import gamepad_output
    gamepad_output._BUTTON_MAP = gamepad_output._build_button_map()

    return mock_pad, mock_vg


def test_gamepad_output_with_clutch(mock_vgamepad):
    mock_pad, vg = mock_vgamepad
    config = ConfigStore()
    config.set("feat_clutch_assist", True)
    config.set("gamepad_clutch_btn", "LB")
    config.set("gamepad_shift_up", "B")

    gp = GamepadOutput(config)
    mock_pad.reset_mock()  # Clear __init__ wake-device calls

    gp._press_release("B")

    assert mock_pad.press_button.call_count == 2
    assert mock_pad.press_button.call_args_list == [
        call(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER),
        call(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_B),
    ]

    assert mock_pad.release_button.call_count == 2
    assert mock_pad.release_button.call_args_list == [
        call(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_B),
        call(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER),
    ]
    assert mock_pad.update.call_count == 4


def test_gamepad_output_no_clutch_btn(mock_vgamepad):
    mock_pad, vg = mock_vgamepad
    config = ConfigStore()
    config.set("feat_clutch_assist", True)
    config.set("gamepad_clutch_btn", "")  # Empty string disables clutch
    config.set("gamepad_shift_up", "B")

    gp = GamepadOutput(config)
    mock_pad.reset_mock()  # Clear __init__ wake-device calls

    gp._press_release("B")

    assert mock_pad.press_button.call_count == 1
    assert mock_pad.press_button.call_args_list == [call(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_B)]


def test_shift_history_sent_at():
    sh = ShiftHistory()
    td = Telemetry()
    td.gear = 2
    
    now = time.time()
    sh.record("UP", td, sent_at=now)
    
    snapshot = sh.snapshot()
    assert len(snapshot) == 1
    assert "shift_sent_at" in snapshot[0]
    assert snapshot[0]["shift_sent_at"] == now
