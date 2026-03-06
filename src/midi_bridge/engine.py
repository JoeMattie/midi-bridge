from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

import mido

from .models import AppConfig, DeviceConfig, Mapping


@dataclass
class MidiEvent:
    timestamp: float
    direction: str          # "IN" or "OUT"
    device_name: str
    message: mido.Message
    matched: bool = False


EventCallback = Callable[[MidiEvent], None]


class MidiEngine:
    def __init__(self, config: AppConfig, on_event: EventCallback) -> None:
        self._config = config
        self._on_event = on_event
        self._lock = threading.Lock()

        # name -> open mido port object
        self._input_ports: dict[str, mido.ports.BaseInput] = {}
        self._output_ports: dict[str, mido.ports.BaseOutput] = {}

        # name -> reader thread
        self._threads: dict[str, threading.Thread] = {}
        self._running = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._running = True
        self._sync_ports(self._config)

    def stop(self) -> None:
        self._running = False
        with self._lock:
            for port in self._input_ports.values():
                try:
                    port.close()
                except Exception:
                    pass
            for port in self._output_ports.values():
                try:
                    port.close()
                except Exception:
                    pass
            self._input_ports.clear()
            self._output_ports.clear()
            self._threads.clear()

    def reload(self, config: AppConfig) -> None:
        with self._lock:
            self._config = config
        self._sync_ports(config)

    # ------------------------------------------------------------------
    # Port lifecycle
    # ------------------------------------------------------------------

    def _sync_ports(self, config: AppConfig) -> None:
        desired_inputs: dict[str, str] = {}   # name -> port string
        desired_outputs: dict[str, str] = {}

        for name, dev in config.devices.items():
            if dev.direction == "input":
                desired_inputs[name] = dev.port
            else:
                desired_outputs[name] = dev.port

        with self._lock:
            # Close removed/changed inputs
            for name in list(self._input_ports.keys()):
                if name not in desired_inputs or self._input_ports[name].name != desired_inputs[name]:
                    try:
                        self._input_ports[name].close()
                    except Exception:
                        pass
                    del self._input_ports[name]
                    self._threads.pop(name, None)

            # Close removed/changed outputs
            for name in list(self._output_ports.keys()):
                if name not in desired_outputs or self._output_ports[name].name != desired_outputs[name]:
                    try:
                        self._output_ports[name].close()
                    except Exception:
                        pass
                    del self._output_ports[name]

            # Open new outputs
            for name, port_str in desired_outputs.items():
                if name not in self._output_ports:
                    try:
                        self._output_ports[name] = mido.open_output(port_str)
                    except Exception as exc:
                        print(f"[engine] could not open output {port_str!r}: {exc}")

            # Open new inputs and start reader threads
            for name, port_str in desired_inputs.items():
                if name not in self._input_ports:
                    try:
                        port = mido.open_input(port_str)
                        self._input_ports[name] = port
                        t = threading.Thread(
                            target=self._reader_loop,
                            args=(name, port),
                            daemon=True,
                            name=f"midi-reader-{name}",
                        )
                        self._threads[name] = t
                        t.start()
                    except Exception as exc:
                        print(f"[engine] could not open input {port_str!r}: {exc}")

    # ------------------------------------------------------------------
    # Reader thread
    # ------------------------------------------------------------------

    def _reader_loop(self, device_name: str, port: mido.ports.BaseInput) -> None:
        while self._running:
            try:
                for msg in port:
                    if not self._running:
                        break
                    self._handle_message(device_name, msg)
            except Exception:
                # Port closed — exit thread
                break

    def _handle_message(self, device_name: str, msg: mido.Message) -> None:
        with self._lock:
            config = self._config

        matched_any = False
        for mapping in config.mappings:
            if mapping.input_device != device_name:
                continue
            if not self._message_matches(msg, mapping):
                continue

            matched_any = True
            self._fire_event(device_name, msg, matched=True)
            self._send_output(mapping, msg)
            return  # fire IN event once even if multiple mappings match first

        if not matched_any:
            self._fire_event(device_name, msg, matched=False)

    def _message_matches(self, msg: mido.Message, mapping: Mapping) -> bool:
        # Map mido type names to our type names
        type_map = {
            "program_change": "program_change",
            "control_change": "control_change",
            "note_on": "note_on",
            "note_off": "note_off",
            "sysex": "sysex",
        }
        if type_map.get(msg.type) != mapping.input_type:
            return False

        if msg.type == "sysex":
            return True  # basic match; could add prefix matching later

        # Channel check (mido channels are 0-based internally)
        msg_channel = getattr(msg, "channel", 0) + 1  # convert to 1-based
        if msg_channel != mapping.input_channel:
            return False

        if mapping.input_value == -1:
            return True

        # Value check by message type
        if msg.type == "program_change":
            return msg.program == mapping.input_value
        elif msg.type == "control_change":
            return msg.control == mapping.input_value
        elif msg.type in ("note_on", "note_off"):
            return msg.note == mapping.input_value

        return True

    def _send_output(self, mapping: Mapping, incoming: mido.Message) -> None:
        with self._lock:
            out_port = self._output_ports.get(mapping.output_device)

        if out_port is None:
            return

        out_msg = self._build_output_message(mapping, incoming)
        if out_msg is None:
            return

        try:
            out_port.send(out_msg)
        except Exception as exc:
            print(f"[engine] send error: {exc}")
            return

        self._fire_event(mapping.output_device, out_msg, matched=True, direction="OUT")

        if mapping.momentary:
            delay_s = mapping.momentary_delay_ms / 1000.0
            follow_up = self._build_zero_message(mapping)
            if follow_up is not None:
                t = threading.Timer(delay_s, self._send_follow_up, args=(mapping.output_device, follow_up))
                t.daemon = True
                t.start()

    def _send_follow_up(self, device_name: str, msg: mido.Message) -> None:
        with self._lock:
            out_port = self._output_ports.get(device_name)
        if out_port is None:
            return
        try:
            out_port.send(msg)
        except Exception:
            pass
        self._fire_event(device_name, msg, matched=True, direction="OUT")

    def _build_output_message(self, mapping: Mapping, incoming: mido.Message) -> mido.Message | None:
        ch = mapping.output_channel - 1  # mido is 0-based
        otype = mapping.output_type

        if mapping.output_value_mode == "passthrough":
            value = self._extract_input_value(incoming)
        else:
            value = mapping.output_value

        try:
            if otype == "control_change":
                return mido.Message("control_change", channel=ch, control=mapping.output_control, value=value)
            elif otype == "program_change":
                return mido.Message("program_change", channel=ch, program=value)
            elif otype == "note_on":
                return mido.Message("note_on", channel=ch, note=mapping.output_control, velocity=value)
            elif otype == "note_off":
                return mido.Message("note_off", channel=ch, note=mapping.output_control, velocity=0)
            elif otype == "sysex":
                if incoming.type == "sysex":
                    return incoming  # forward as-is
        except Exception as exc:
            print(f"[engine] build message error: {exc}")
        return None

    @staticmethod
    def _extract_input_value(msg: mido.Message) -> int:
        t = msg.type
        if t == "program_change":
            return msg.program
        elif t == "control_change":
            return msg.value
        elif t in ("note_on", "note_off"):
            return msg.velocity
        return 0

    def _build_zero_message(self, mapping: Mapping) -> mido.Message | None:
        ch = mapping.output_channel - 1
        otype = mapping.output_type
        try:
            if otype == "control_change":
                return mido.Message("control_change", channel=ch, control=mapping.output_control, value=0)
            elif otype == "note_on":
                return mido.Message("note_off", channel=ch, note=mapping.output_control, velocity=0)
        except Exception:
            pass
        return None

    def _fire_event(self, device_name: str, msg: mido.Message, matched: bool, direction: str = "IN") -> None:
        event = MidiEvent(
            timestamp=time.time(),
            direction=direction,
            device_name=device_name,
            message=msg,
            matched=matched,
        )
        try:
            self._on_event(event)
        except Exception:
            pass


def list_input_ports() -> list[str]:
    try:
        return mido.get_input_names()
    except Exception:
        return []


def list_output_ports() -> list[str]:
    try:
        return mido.get_output_names()
    except Exception:
        return []
