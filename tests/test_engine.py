"""
Tests for MidiEngine internal logic.

Real MIDI ports are never opened — the engine's internal methods are tested
directly, and port/thread machinery is bypassed via a fake port fixture.
"""
import threading
import time
from unittest.mock import MagicMock, patch

import mido
import pytest

from midi_bridge.engine import MidiEngine, MidiEvent
from midi_bridge.models import AppConfig, DeviceConfig, Mapping


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _engine(config=None, events=None):
    """Return a MidiEngine with mocked port-opening so no real MIDI is needed."""
    cfg = config or AppConfig()
    captured = events if events is not None else []

    def cb(ev):
        captured.append(ev)

    engine = MidiEngine(cfg, cb)
    return engine, captured


def _mapping(**kwargs) -> Mapping:
    defaults = dict(
        name="test",
        input_device="pad",
        input_type="program_change",
        input_channel=1,
        input_value=-1,
        output_device="synth",
        output_type="control_change",
        output_channel=1,
        output_control=64,
        output_value=127,
        momentary=False,
        momentary_delay_ms=100,
    )
    defaults.update(kwargs)
    return Mapping(**defaults)


# ---------------------------------------------------------------------------
# _message_matches
# ---------------------------------------------------------------------------

class TestMessageMatches:
    def setup_method(self):
        self.engine, _ = _engine()

    def _matches(self, msg, mapping):
        return self.engine._message_matches(msg, mapping)

    # --- type matching ---

    def test_type_mismatch_returns_false(self):
        msg = mido.Message("control_change", channel=0, control=1, value=10)
        m = _mapping(input_type="program_change")
        assert not self._matches(msg, m)

    def test_correct_type_matches(self):
        msg = mido.Message("program_change", channel=0, program=5)
        m = _mapping(input_type="program_change", input_channel=1, input_value=-1)
        assert self._matches(msg, m)

    # --- channel matching ---

    def test_channel_mismatch_returns_false(self):
        msg = mido.Message("program_change", channel=1, program=5)  # ch 2 (1-based)
        m = _mapping(input_type="program_change", input_channel=1, input_value=-1)
        assert not self._matches(msg, m)

    def test_channel_match(self):
        msg = mido.Message("program_change", channel=0, program=5)  # ch 1 (1-based)
        m = _mapping(input_type="program_change", input_channel=1, input_value=-1)
        assert self._matches(msg, m)

    # --- input_value = -1 (wildcard) ---

    def test_wildcard_value_matches_any_program(self):
        for prog in [0, 64, 127]:
            msg = mido.Message("program_change", channel=0, program=prog)
            m = _mapping(input_type="program_change", input_channel=1, input_value=-1)
            assert self._matches(msg, m)

    # --- program_change value ---

    def test_program_change_exact_match(self):
        msg = mido.Message("program_change", channel=0, program=7)
        assert self._matches(msg, _mapping(input_type="program_change", input_channel=1, input_value=7))

    def test_program_change_no_match(self):
        msg = mido.Message("program_change", channel=0, program=8)
        assert not self._matches(msg, _mapping(input_type="program_change", input_channel=1, input_value=7))

    # --- control_change value (CC number) ---

    def test_control_change_matches_on_control_number(self):
        msg = mido.Message("control_change", channel=0, control=64, value=127)
        assert self._matches(msg, _mapping(input_type="control_change", input_channel=1, input_value=64))

    def test_control_change_wrong_control(self):
        msg = mido.Message("control_change", channel=0, control=65, value=127)
        assert not self._matches(msg, _mapping(input_type="control_change", input_channel=1, input_value=64))

    # --- note_on / note_off ---

    def test_note_on_matches_note_number(self):
        msg = mido.Message("note_on", channel=0, note=60, velocity=100)
        assert self._matches(msg, _mapping(input_type="note_on", input_channel=1, input_value=60))

    def test_note_off_matches_note_number(self):
        msg = mido.Message("note_off", channel=0, note=60, velocity=0)
        assert self._matches(msg, _mapping(input_type="note_off", input_channel=1, input_value=60))

    def test_note_on_wrong_note(self):
        msg = mido.Message("note_on", channel=0, note=61, velocity=100)
        assert not self._matches(msg, _mapping(input_type="note_on", input_channel=1, input_value=60))

    # --- sysex ---

    def test_sysex_always_matches_type(self):
        msg = mido.Message("sysex", data=[0x41, 0x10])
        m = _mapping(input_type="sysex")
        assert self._matches(msg, m)


# ---------------------------------------------------------------------------
# _build_output_message
# ---------------------------------------------------------------------------

class TestBuildOutputMessage:
    def setup_method(self):
        self.engine, _ = _engine()
        self.dummy_in = mido.Message("program_change", channel=0, program=5)

    def _build(self, mapping):
        return self.engine._build_output_message(mapping, self.dummy_in)

    def test_build_control_change(self):
        m = _mapping(output_type="control_change", output_channel=2, output_control=64, output_value=127)
        msg = self._build(m)
        assert msg is not None
        assert msg.type == "control_change"
        assert msg.channel == 1      # 2 - 1
        assert msg.control == 64
        assert msg.value == 127

    def test_build_program_change(self):
        m = _mapping(output_type="program_change", output_channel=1, output_value=10)
        msg = self._build(m)
        assert msg is not None
        assert msg.type == "program_change"
        assert msg.program == 10

    def test_build_note_on(self):
        m = _mapping(output_type="note_on", output_channel=1, output_control=60, output_value=100)
        msg = self._build(m)
        assert msg is not None
        assert msg.type == "note_on"
        assert msg.note == 60
        assert msg.velocity == 100

    def test_build_note_off(self):
        m = _mapping(output_type="note_off", output_channel=1, output_control=60)
        msg = self._build(m)
        assert msg is not None
        assert msg.type == "note_off"
        assert msg.velocity == 0

    def test_build_sysex_forwards_incoming(self):
        sysex_in = mido.Message("sysex", data=[0x41, 0x10])
        m = _mapping(input_type="sysex", output_type="sysex")
        result = self.engine._build_output_message(m, sysex_in)
        assert result is sysex_in

    def test_build_sysex_from_non_sysex_returns_none(self):
        m = _mapping(output_type="sysex")
        result = self._build(m)
        assert result is None


# ---------------------------------------------------------------------------
# _build_zero_message
# ---------------------------------------------------------------------------

class TestBuildZeroMessage:
    def setup_method(self):
        self.engine, _ = _engine()

    def test_cc_zero_message(self):
        m = _mapping(output_type="control_change", output_channel=1, output_control=64)
        msg = self.engine._build_zero_message(m)
        assert msg is not None
        assert msg.type == "control_change"
        assert msg.control == 64
        assert msg.value == 0

    def test_note_on_zero_is_note_off(self):
        m = _mapping(output_type="note_on", output_channel=1, output_control=60)
        msg = self.engine._build_zero_message(m)
        assert msg is not None
        assert msg.type == "note_off"
        assert msg.note == 60
        assert msg.velocity == 0

    def test_program_change_has_no_zero_message(self):
        m = _mapping(output_type="program_change")
        msg = self.engine._build_zero_message(m)
        assert msg is None


# ---------------------------------------------------------------------------
# _handle_message / routing
# ---------------------------------------------------------------------------

class TestHandleMessage:
    """Tests for the routing logic using fake in-memory ports."""

    def _make_engine_with_fake_ports(self, config, events):
        engine = MidiEngine(config, lambda ev: events.append(ev))
        # Inject a fake output port so _send_output can write to it
        fake_out = MagicMock()
        fake_out.name = "FakeOut"
        engine._output_ports["synth"] = fake_out
        return engine, fake_out

    def test_unmatched_message_fires_unmatched_in_event(self):
        cfg = AppConfig(mappings=[])
        events = []
        engine, _ = self._make_engine_with_fake_ports(cfg, events)

        msg = mido.Message("program_change", channel=0, program=5)
        engine._handle_message("pad", msg)

        assert len(events) == 1
        assert events[0].direction == "IN"
        assert events[0].matched is False

    def test_matched_message_fires_in_and_out_events(self):
        m = _mapping(input_type="program_change", input_channel=1, input_value=5,
                     output_type="control_change", output_channel=1, output_control=64, output_value=127)
        cfg = AppConfig(mappings=[m])
        events = []
        engine, fake_out = self._make_engine_with_fake_ports(cfg, events)

        msg = mido.Message("program_change", channel=0, program=5)
        engine._handle_message("pad", msg)

        in_events = [e for e in events if e.direction == "IN"]
        out_events = [e for e in events if e.direction == "OUT"]
        assert len(in_events) == 1
        assert in_events[0].matched is True
        assert len(out_events) == 1
        assert out_events[0].message.type == "control_change"
        assert out_events[0].message.value == 127
        fake_out.send.assert_called_once()

    def test_wrong_device_does_not_match(self):
        m = _mapping(input_device="other", input_type="program_change", input_channel=1, input_value=5)
        cfg = AppConfig(mappings=[m])
        events = []
        engine, fake_out = self._make_engine_with_fake_ports(cfg, events)

        engine._handle_message("pad", mido.Message("program_change", channel=0, program=5))

        assert events[0].matched is False
        fake_out.send.assert_not_called()

    def test_missing_output_port_sends_nothing(self):
        m = _mapping(output_device="missing")
        cfg = AppConfig(mappings=[m])
        events = []
        engine = MidiEngine(cfg, lambda ev: events.append(ev))
        # no output ports injected

        msg = mido.Message("program_change", channel=0, program=0)
        engine._handle_message("pad", msg)
        # should not raise; only an IN unmatched event (device mismatch)

    def test_wildcard_value_routes_any_program(self):
        m = _mapping(input_type="program_change", input_channel=1, input_value=-1,
                     output_type="control_change", output_control=10, output_value=64)
        cfg = AppConfig(mappings=[m])
        events = []
        engine, fake_out = self._make_engine_with_fake_ports(cfg, events)

        for prog in [0, 50, 127]:
            events.clear()
            fake_out.reset_mock()
            engine._handle_message("pad", mido.Message("program_change", channel=0, program=prog))
            assert any(e.direction == "OUT" for e in events)
            fake_out.send.assert_called_once()


# ---------------------------------------------------------------------------
# Momentary
# ---------------------------------------------------------------------------

class TestMomentary:
    def test_momentary_sends_follow_up_zero(self):
        m = _mapping(
            input_type="program_change", input_channel=1, input_value=1,
            output_type="control_change", output_channel=1, output_control=64, output_value=127,
            momentary=True, momentary_delay_ms=50,
        )
        cfg = AppConfig(mappings=[m])
        events = []
        engine = MidiEngine(cfg, lambda ev: events.append(ev))
        fake_out = MagicMock()
        fake_out.name = "FakeOut"
        engine._output_ports["synth"] = fake_out

        engine._handle_message("pad", mido.Message("program_change", channel=0, program=1))

        # First send: value=127
        assert fake_out.send.call_count == 1
        first_msg = fake_out.send.call_args_list[0][0][0]
        assert first_msg.value == 127

        # Wait for Timer to fire
        time.sleep(0.15)

        assert fake_out.send.call_count == 2
        second_msg = fake_out.send.call_args_list[1][0][0]
        assert second_msg.value == 0
        assert second_msg.control == 64

    def test_non_momentary_sends_no_follow_up(self):
        m = _mapping(
            input_type="program_change", input_channel=1, input_value=1,
            output_type="control_change", momentary=False,
        )
        cfg = AppConfig(mappings=[m])
        events = []
        engine = MidiEngine(cfg, lambda ev: events.append(ev))
        fake_out = MagicMock()
        fake_out.name = "FakeOut"
        engine._output_ports["synth"] = fake_out

        engine._handle_message("pad", mido.Message("program_change", channel=0, program=1))
        time.sleep(0.15)

        assert fake_out.send.call_count == 1
